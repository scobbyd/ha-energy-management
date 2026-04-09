#!/usr/bin/env python3
"""
EMS State Machine Simulation — Algorithm Verification

Mirrors the HA YAML logic in Python and runs test scenarios to verify:
- Ideal state selection (correct state for given prices)
- Parallel timer behavior (SLOW/FAST/INSTANT, cancel logic)
- SELL bypass (always instant)
- DUMP prerequisites (gen_port, SOC)
- SOC fallback
- State entry actions
"""

from dataclasses import dataclass, field
from typing import Optional
import json

# ── Configuration (mirrors energy_helpers.yaml defaults) ──────────────────

@dataclass
class EMSConfig:
    provider_fee: float = 20.0          # EUR/MWh (= 2ct/kWh)
    dumpload_profit: float = 7.0      # ct/kWh
    sell_spike_spread: float = 30.0   # ct
    sell_spike_floor: float = 40.0    # ct
    dump_soc_entry: float = 70.0      # %
    dump_soc_fallback: float = 60.0   # %
    hysteresis: float = 2.0           # ct
    fast_spread: float = 4.0          # ct
    instant_spread: float = 15.0      # ct
    slow_duration: float = 300        # seconds (5 min)
    fast_duration: float = 60         # seconds (1 min)


# ── Timer ─────────────────────────────────────────────────────────────────

@dataclass
class Timer:
    name: str
    duration: float = 0
    _started_at: Optional[float] = None

    @property
    def is_idle(self): return self._started_at is None

    @property
    def is_active(self): return self._started_at is not None

    def start(self, at_time: float, duration: float):
        """Start fresh (only if idle)."""
        if self.is_idle:
            self._started_at = at_time
            self.duration = duration

    def cancel(self):
        self._started_at = None

    def is_finished(self, at_time: float) -> bool:
        if self._started_at is None:
            return False
        return (at_time - self._started_at) >= self.duration

    def remaining(self, at_time: float) -> float:
        if self._started_at is None:
            return float('inf')
        return max(0, self.duration - (at_time - self._started_at))


# ── State Machine ─────────────────────────────────────────────────────────

STATES = ["SELL", "NORMAL", "SELF_CONSUME", "GRID_USE", "DUMP"]

CONTROL_LEVERS = {
    "SELL":         {"pv": 13000, "discharge": 240, "charge_current": 0,   "grid_charge": False, "export": True,  "dumpload": False},
    "NORMAL":       {"pv": 13000, "discharge": 240, "charge_current": None,"grid_charge": False, "export": True,  "dumpload": False},
    "SELF_CONSUME": {"pv": 13000, "discharge": 240, "charge_current": None,"grid_charge": False, "export": False, "dumpload": False},
    "GRID_USE":     {"pv": 400,   "discharge": 0,   "charge_current": None,"grid_charge": False, "export": False, "dumpload": False},
    "DUMP":         {"pv": 400,   "discharge": 0,   "charge_current": None,"grid_charge": False, "export": False, "dumpload": True},
}


@dataclass
class EMSState:
    current: str = "NORMAL"
    config: EMSConfig = field(default_factory=EMSConfig)
    slow_timer: Timer = field(default_factory=lambda: Timer("SLOW"))
    fast_timer: Timer = field(default_factory=lambda: Timer("FAST"))
    levers: dict = field(default_factory=dict)
    log: list = field(default_factory=list)

    def compute_ideal(self, sell: float, buy: float, soc: float,
                      gen_port: str, pv_power: float, sell_avg: float) -> str:
        """Compute ideal state from current conditions. All prices in EUR/MWh."""
        cfg = self.config
        spike_spread_eur = cfg.sell_spike_spread * 10
        spike_floor_eur = cfg.sell_spike_floor * 10
        dump_threshold = -(cfg.dumpload_profit * 10 + cfg.provider_fee)
        fee = cfg.provider_fee

        # Priority: SELL > DUMP > GRID_USE > SELF_CONSUME > NORMAL
        if sell > (sell_avg + spike_spread_eur) and sell > spike_floor_eur and pv_power > 3000:
            return "SELL"
        elif buy < dump_threshold and soc > cfg.dump_soc_entry and gen_port == "SmartLoad":
            return "DUMP"
        elif buy < -fee:
            return "GRID_USE"
        elif sell < fee:
            return "SELF_CONSUME"
        else:
            return "NORMAL"

    def compute_spread(self, ideal: str, sell: float, buy: float,
                       sell_avg: float) -> float:
        """Compute transition spread in ct. Always positive when transition warranted."""
        if ideal == self.current:
            return 0.0

        cfg = self.config
        fee = cfg.provider_fee
        profit_eur = cfg.dumpload_profit * 10
        spike_spread_eur = cfg.sell_spike_spread * 10

        # SELL transitions
        if self.current == "SELL":
            threshold = sell_avg + spike_spread_eur
            return round((threshold - sell) / 10, 2)
        elif ideal == "SELL":
            threshold = sell_avg + spike_spread_eur
            return round((sell - threshold) / 10, 2)

        # DUMP exit
        elif self.current == "DUMP":
            threshold = -(profit_eur + fee)
            return round((buy - threshold) / 10, 2)

        # GRID_USE exit upward
        elif self.current == "GRID_USE" and ideal in ["NORMAL", "SELF_CONSUME"]:
            return round((buy - (-fee)) / 10, 2)

        # GRID_USE → DUMP deepening
        elif self.current == "GRID_USE" and ideal == "DUMP":
            threshold = -(profit_eur + fee)
            return round((threshold - buy) / 10, 2)

        # Entering buy-driven from NORMAL/SELF_CONSUME
        elif ideal in ["GRID_USE", "DUMP"]:
            threshold = -(profit_eur + fee) if ideal == "DUMP" else -fee
            return round((threshold - buy) / 10, 2)

        # Sell-driven: NORMAL ↔ SELF_CONSUME
        elif ideal == "NORMAL":
            return round((sell - fee) / 10, 2)
        else:
            return round((fee - sell) / 10, 2)

    def evaluate(self, t: float, sell: float, buy: float, soc: float,
                 gen_port: str, pv_power: float, sell_avg: float) -> Optional[str]:
        """Run one evaluation cycle. Returns new state if transition happened."""
        ideal = self.compute_ideal(sell, buy, soc, gen_port, pv_power, sell_avg)
        spread = self.compute_spread(ideal, sell, buy, sell_avg)
        cfg = self.config
        transition_to = None

        if ideal == self.current:
            self.slow_timer.cancel()
            self.fast_timer.cancel()

        # SELL — always instant
        elif ideal == "SELL" or self.current == "SELL":
            self.slow_timer.cancel()
            self.fast_timer.cancel()
            transition_to = ideal

        # INSTANT override
        elif spread >= cfg.instant_spread:
            self.slow_timer.cancel()
            self.fast_timer.cancel()
            transition_to = ideal

        # Below hysteresis — cancel all
        elif spread < cfg.hysteresis:
            self.slow_timer.cancel()
            self.fast_timer.cancel()

        # Timer zone: hysteresis <= spread < instant
        else:
            # SLOW timer
            self.slow_timer.start(t, cfg.slow_duration)

            # FAST timer
            if spread >= cfg.fast_spread:
                self.fast_timer.start(t, cfg.fast_duration)
            elif self.fast_timer.is_active:
                self.fast_timer.cancel()

            # Check if any timer finished
            if self.slow_timer.is_finished(t):
                transition_to = ideal
            elif self.fast_timer.is_finished(t):
                transition_to = ideal

        # SOC fallback
        if self.current == "DUMP" and soc < cfg.dump_soc_fallback:
            transition_to = "GRID_USE"

        # Apply transition
        if transition_to and transition_to != self.current:
            old = self.current
            self.current = transition_to
            self.slow_timer.cancel()
            self.fast_timer.cancel()
            self.levers = CONTROL_LEVERS[transition_to].copy()
            self.log.append({
                "t": t, "from": old, "to": transition_to,
                "sell": sell, "buy": buy, "spread": spread,
                "ideal": ideal
            })
            return transition_to

        return None


# ── Test Scenarios ────────────────────────────────────────────────────────

def run_test(name: str, steps: list, config: EMSConfig = None,
             initial_state: str = "NORMAL") -> tuple[bool, list[str]]:
    """Run a test scenario. Steps: [(time, sell, buy, soc, gen_port, pv, sell_avg, expected_state)]"""
    ems = EMSState(current=initial_state, config=config or EMSConfig())
    ems.levers = CONTROL_LEVERS[initial_state].copy()
    errors = []

    for step in steps:
        t, sell, buy, soc, gen_port, pv, sell_avg, expected = step
        ems.evaluate(t, sell, buy, soc, gen_port, pv, sell_avg)

        if ems.current != expected:
            errors.append(
                f"  t={t:>4}s: expected {expected}, got {ems.current} "
                f"(sell={sell}, buy={buy}, soc={soc}, pv={pv})"
            )

    passed = len(errors) == 0
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}")
    for e in errors:
        print(e)
    return passed, ems.log


# ── Test Suite ────────────────────────────────────────────────────────────

def test_ideal_state_computation():
    """Test compute_ideal directly — independent of timers."""
    print("\n=== Ideal State Computation (no timers) ===")

    ems = EMSState()
    cases = [
        # (sell, buy, soc, gen_port, pv, sell_avg, expected_ideal)
        (50,   50,   80, "Microinverter", 5000, 50, "NORMAL"),
        (10,   10,   80, "Microinverter", 5000, 50, "SELF_CONSUME"),  # sell < 20
        (-50,  50,   80, "Microinverter", 5000, 50, "SELF_CONSUME"),  # sell < 20, buy > -20
        (-50,  -30,  80, "Microinverter", 5000, 50, "GRID_USE"),        # buy < -20
        (-100, -100, 80, "SmartLoad",     5000, 50, "DUMP"),          # buy < -90, SOC > 70, SmartLoad
        (-100, -100, 80, "Microinverter", 5000, 50, "GRID_USE"),        # no SmartLoad → GRID_USE
        (-100, -100, 60, "SmartLoad",     5000, 50, "GRID_USE"),        # SOC < 70 → GRID_USE
        (850,  850,  80, "Microinverter", 5000, 80, "SELL"),          # spike
        (850,  850,  80, "Microinverter", 2000, 80, "NORMAL"),        # PV < 3kW → not SELL
        (350,  350,  80, "Microinverter", 5000, 10, "NORMAL"),        # sell < floor → not SELL
        (850,  -100, 80, "SmartLoad",     5000, 80, "SELL"),          # SELL > DUMP priority
    ]

    all_pass = True
    for sell, buy, soc, gp, pv, avg, expected in cases:
        ideal = ems.compute_ideal(sell, buy, soc, gp, pv, avg)
        passed = ideal == expected
        if not passed:
            all_pass = False
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] sell={sell}, buy={buy}, soc={soc}, gp={gp}, pv={pv} → {ideal} (expected {expected})")

    return all_pass


def test_ideal_state_with_timers():
    """Test that transitions respect the timer system."""
    print("\n=== Ideal State Selection (with timers) ===")

    # Spread too small (< hysteresis) → stays in current state
    run_test("sell=10: spread 1ct < 2ct hysteresis → stays NORMAL", [
        (0, 10, 10, 80, "Microinverter", 5000, 50, "NORMAL"),
    ])

    # Spread sufficient + wait for SLOW timer
    run_test("SELF_CONSUME: sell=-10, spread 3ct, SLOW fires at 5min", [
        (0,   -10, 10, 80, "Microinverter", 5000, 50, "NORMAL"),
        (300, -10, 10, 80, "Microinverter", 5000, 50, "SELF_CONSUME"),
    ])

    # GRID_USE via SLOW timer
    run_test("GRID_USE: buy=-50, spread 3ct, SLOW fires at 5min", [
        (0,   -10, -50, 80, "Microinverter", 5000, 50, "NORMAL"),
        (300, -10, -50, 80, "Microinverter", 5000, 50, "GRID_USE"),
    ])

    # At buy=-200, ideal=DUMP directly (spread 11ct from -90 threshold), SLOW timer
    run_test("DUMP direct: buy=-200, spread 11ct, SLOW fires at 5min", [
        (0,   -100, -200, 80, "SmartLoad", 5000, 50, "NORMAL"),    # spread 11ct, SLOW starts
        (300, -100, -200, 80, "SmartLoad", 5000, 50, "DUMP"),      # SLOW fires → DUMP directly
    ])

    # INSTANT transition at extreme prices
    run_test("INSTANT GRID_USE at buy=-200 (spread 18ct)", [
        (0, -10, -200, 80, "Microinverter", 5000, 50, "GRID_USE"),   # spread=(-20-(-200))/10=18ct > 15ct
    ])

    # SELL is always instant regardless of spread
    run_test("SELL instant even at moderate spike (spread 12ct < 15ct instant)", [
        (0, 500, 50, 80, "Microinverter", 5000, 80, "SELL"),
    ])


def test_timer_behavior():
    """Test parallel timer logic."""
    print("\n=== Timer Behavior ===")

    # Spread 3ct → SLOW starts (5min), no transition yet
    run_test("SLOW timer: no transition before 5min", [
        (0,   -10, -50, 80, "Mi", 5000, 50, "NORMAL"),     # spread 3ct, SLOW starts
        (60,  -10, -50, 80, "Mi", 5000, 50, "NORMAL"),     # 1min, still waiting
        (240, -10, -50, 80, "Mi", 5000, 50, "NORMAL"),     # 4min, still waiting
    ])

    run_test("SLOW timer: transitions at 5min", [
        (0,   -10, -50, 80, "Mi", 5000, 50, "NORMAL"),     # spread 3ct, SLOW starts
        (300, -10, -50, 80, "Mi", 5000, 50, "GRID_USE"),     # 5min, SLOW fires
    ])

    # Spread 5ct → FAST also starts (1min)
    run_test("FAST timer: transitions at 1min when spread >= 4ct", [
        (0,  -10, -70, 80, "Mi", 5000, 50, "NORMAL"),      # spread 5ct, FAST starts
        (60, -10, -70, 80, "Mi", 5000, 50, "GRID_USE"),      # 1min, FAST fires
    ])

    # INSTANT: spread >= 15ct
    run_test("INSTANT: immediate transition at spread >= 15ct", [
        (0, -10, -200, 80, "Mi", 5000, 50, "GRID_USE"),      # spread 18ct, instant
    ])

    # Timer cancellation when spread drops below hysteresis
    run_test("Timer cancelled when spread drops below hysteresis", [
        (0,   -10, -50, 80, "Mi", 5000, 50, "NORMAL"),     # spread 3ct, SLOW starts
        (120, -10, -25, 80, "Mi", 5000, 50, "NORMAL"),     # spread 0.5ct < 2ct, cancelled
        (420, -10, -50, 80, "Mi", 5000, 50, "NORMAL"),     # SLOW restarts, not yet 5min
    ])

    # FAST cancels when spread drops below fast_spread but SLOW continues
    run_test("FAST cancelled at spread < 4ct, SLOW survives", [
        (0,   -10, -70, 80, "Mi", 5000, 50, "NORMAL"),     # 5ct, both start
        (30,  -10, -50, 80, "Mi", 5000, 50, "NORMAL"),     # 3ct, FAST cancelled, SLOW alive
        (300, -10, -50, 80, "Mi", 5000, 50, "GRID_USE"),     # 5min from t=0, SLOW fires
    ])


def test_sell_bypass():
    """Test that SELL always bypasses timers."""
    print("\n=== SELL Timer Bypass ===")

    run_test("SELL enters instantly regardless of spread", [
        (0, 500, 50, 80, "Mi", 5000, 80, "SELL"),          # spread 12ct (< instant 15ct) but SELL is always instant
    ])

    run_test("SELL exits instantly when conditions drop", [
        (0, 500, 50, 80, "Mi", 5000, 80, "SELL"),          # enter SELL
        (1, 100, 50, 80, "Mi", 5000, 80, "NORMAL"),        # sell drops, instant exit
    ], initial_state="NORMAL")

    run_test("SELL exits instantly when PV drops below 3kW", [
        (0, 500, 50, 80, "Mi", 5000, 80, "SELL"),
        (1, 500, 50, 80, "Mi", 2000, 80, "NORMAL"),        # PV < 3kW, SELL no longer ideal
    ])


def test_dump_prerequisites():
    """Test DUMP state prerequisites via timer system."""
    print("\n=== DUMP Prerequisites ===")

    # DUMP with sufficient spread (11ct) + SLOW timer
    run_test("DUMP requires SmartLoad + SLOW timer", [
        (0,   -100, -200, 80, "SmartLoad", 5000, 50, "NORMAL"),    # spread 11ct, SLOW starts
        (300, -100, -200, 80, "SmartLoad", 5000, 50, "DUMP"),      # SLOW fires
    ])

    # Without SmartLoad → ideal=GRID_USE, not DUMP. INSTANT at spread 18ct.
    run_test("DUMP blocked without SmartLoad → GRID_USE (instant at spread 18ct)", [
        (0, -100, -200, 80, "Microinverter", 5000, 50, "GRID_USE"),  # ideal=GRID_USE, spread=18ct > instant
    ])

    # Low SOC → ideal=GRID_USE, not DUMP
    run_test("DUMP blocked at low SOC → GRID_USE (instant)", [
        (0, -100, -200, 50, "SmartLoad", 5000, 50, "GRID_USE"),      # SOC < 70, ideal=GRID_USE, spread 18ct
    ])

    # buy=-85 > -90 → ideal=GRID_USE, not DUMP
    run_test("buy=-85: ideal is GRID_USE not DUMP (above -90 threshold)", [
        (0, -100, -85, 80, "SmartLoad", 5000, 50, "NORMAL"),       # ideal=GRID_USE, spread=(-20-(-85))/10=6.5ct
        (60, -100, -85, 80, "SmartLoad", 5000, 50, "GRID_USE"),      # FAST fires at 1min
    ])


def test_soc_fallback():
    """Test SOC-based DUMP exit."""
    print("\n=== SOC Fallback ===")

    # Start already in DUMP (simulating after a transition)
    run_test("SOC fallback: DUMP → GRID_USE when SOC < 60%", [
        (0, -100, -200, 80, "SmartLoad", 5000, 50, "DUMP"),    # already in DUMP, stays
        (1, -100, -200, 55, "SmartLoad", 5000, 50, "GRID_USE"),  # SOC drops, instant exit
    ], initial_state="DUMP")

    run_test("SOC fallback: no exit at SOC = 65% (above 60%)", [
        (0, -100, -200, 80, "SmartLoad", 5000, 50, "DUMP"),
        (1, -100, -200, 65, "SmartLoad", 5000, 50, "DUMP"),    # still above fallback
    ], initial_state="DUMP")


def test_control_levers():
    """Test that state entry sets correct control lever values."""
    print("\n=== Control Levers ===")

    ems = EMSState()
    scenarios = [
        ("NORMAL",       {"pv": 13000, "discharge": 240, "export": True,  "dumpload": False, "grid_charge": False}),
        ("SELL",         {"pv": 13000, "discharge": 240, "export": True,  "dumpload": False, "grid_charge": False, "charge_current": 0}),
        ("SELF_CONSUME", {"pv": 13000, "discharge": 240, "export": False, "dumpload": False, "grid_charge": False}),
        ("GRID_USE",     {"pv": 400,   "discharge": 0,   "export": False, "dumpload": False, "grid_charge": False}),
        ("DUMP",         {"pv": 400,   "discharge": 0,   "export": False, "dumpload": True,  "grid_charge": False}),
    ]

    all_pass = True
    for state, expected in scenarios:
        levers = CONTROL_LEVERS[state]
        errors = []
        for key, val in expected.items():
            if levers.get(key) != val:
                errors.append(f"{key}: expected {val}, got {levers.get(key)}")
        status = "PASS" if not errors else "FAIL"
        if errors:
            all_pass = False
        print(f"  [{status}] {state}: {', '.join(errors) if errors else 'all correct'}")

    return all_pass


def test_transition_spread():
    """Test spread calculation for various transitions."""
    print("\n=== Spread Calculation ===")

    ems = EMSState()
    cases = [
        # (current, ideal, sell, buy, sell_avg, expected_spread)
        ("NORMAL", "NORMAL",       50,   50,  50, 0.0),
        ("NORMAL", "SELF_CONSUME", 10,   10,  50, 1.0),     # (20-10)/10 = 1ct
        ("NORMAL", "GRID_USE",      -10,  -50,  50, 3.0),     # (-20-(-50))/10 = 3ct
        ("GRID_USE", "NORMAL",      -10,   10,  50, 3.0),     # (10-(-20))/10 = 3ct
        ("GRID_USE", "DUMP",        -10, -100,  50, 1.0),     # (-90-(-100))/10 = 1ct
        ("DUMP",   "GRID_USE",      -10,  -50,  50, 4.0),     # (-50-(-90))/10 = 4ct
        ("DUMP",   "NORMAL",       50,   50,  50, 14.0),    # (50-(-90))/10 = 14ct
        ("NORMAL", "SELL",        500,   50,  80, 12.0),    # (500-(80+300))/10 = 12ct
        ("SELL",   "NORMAL",      100,   50,  80, 28.0),    # (380-100)/10 = 28ct
    ]

    all_pass = True
    for current, ideal, sell, buy, sell_avg, expected in cases:
        ems.current = current
        spread = ems.compute_spread(ideal, sell, buy, sell_avg)
        passed = abs(spread - expected) < 0.01
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {current} → {ideal}: spread={spread}ct (expected {expected}ct)")

    return all_pass


def test_realistic_scenario():
    """Simulate a realistic day: morning normal, midday negative, spike, recovery."""
    print("\n=== Realistic Day Scenario ===")

    # Time in seconds, sell/buy in EUR/MWh, soc %, gen_port, pv W, sell_avg EUR/MWh
    steps = [
        # Morning: normal prices, PV ramping up
        (0,     50,  50,  70, "SmartLoad", 1000, 60, "NORMAL"),
        (3600,  40,  40,  75, "SmartLoad", 3000, 60, "NORMAL"),

        # Midday: prices drop, enter SELF_CONSUME
        (7200,  15,  15,  80, "SmartLoad", 8000, 60, "SELF_CONSUME"),  # sell < 20, instant (spread 13ct > instant)

        # Prices go negative: GRID_USE
        (10800, -30, -30, 85, "SmartLoad", 8000, 60, "GRID_USE"),  # buy=-30 < -20, spread=1ct... hmm

        # Actually with spread 1ct < 2ct hysteresis, won't trigger. Need more negative.
        # Let me fix: buy=-50, spread = (-20-(-50))/10 = 3ct, SLOW starts
        # At t=10800+300=11100, SLOW fires
    ]
    # Rewrite with correct spreads
    steps = [
        # Morning: normal prices
        (0,     50,  50,  70, "SmartLoad", 1000, 60, "NORMAL"),
        (3600,  40,  40,  75, "SmartLoad", 3000, 60, "NORMAL"),

        # Midday: sell drops to 10, spread from +20 threshold = 1ct → below hysteresis
        # Need sell to drop more: sell=-10, spread = (20-(-10))/10 = 3ct
        (7200,  -10, 15,  80, "SmartLoad", 8000, 60, "NORMAL"),    # spread 3ct, SLOW starts
        (7500,  -10, 15,  80, "SmartLoad", 8000, 60, "SELF_CONSUME"),  # 5min, SLOW fires

        # Prices deeply negative: buy=-50, spread=3ct from GRID_USE threshold
        (10800, -50, -50, 85, "SmartLoad", 8000, 60, "SELF_CONSUME"),  # SLOW starts for GRID_USE
        (11100, -50, -50, 85, "SmartLoad", 8000, 60, "GRID_USE"),        # 5min fires

        # Even more negative: buy=-100, spread from DUMP threshold = 1ct
        (14400, -80, -100, 85, "SmartLoad", 8000, 60, "GRID_USE"),  # spread 1ct < hysteresis for DUMP...
        # Need buy=-120: spread = (-90-(-120))/10 = 3ct
        (14400, -80, -120, 85, "SmartLoad", 8000, 60, "GRID_USE"),  # SLOW starts for DUMP
        (14700, -80, -120, 85, "SmartLoad", 8000, 60, "DUMP"),    # 5min fires

        # Price spike! sell=600, avg=60 → spike threshold = 60+300=360, sell=600 > 360 and > 400 floor
        (18000, 600, 600, 90, "SmartLoad", 6000, 60, "SELL"),     # SELL instant

        # Spike ends
        (18060, 50, 50, 90, "SmartLoad", 6000, 60, "NORMAL"),     # SELL exit instant

        # Evening: low PV, normal prices
        (21600, 50, 50, 85, "SmartLoad", 500, 60, "NORMAL"),
    ]

    passed, log = run_test("Realistic day with all states", steps)
    if log:
        print("\n  Transition log:")
        for entry in log:
            print(f"    t={entry['t']:>6}s: {entry['from']:>12} → {entry['to']:<12} "
                  f"(sell={entry['sell']}, buy={entry['buy']}, spread={entry['spread']}ct)")


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  EMS State Machine — Algorithm Verification")
    print("=" * 60)

    test_ideal_state_computation()
    test_ideal_state_with_timers()
    test_timer_behavior()
    test_sell_bypass()
    test_dump_prerequisites()
    test_soc_fallback()
    test_control_levers()
    test_transition_spread()
    test_realistic_scenario()

    print("\n" + "=" * 60)
    print("  Done.")
    print("=" * 60)
