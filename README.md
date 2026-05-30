# Home Assistant Energy Management System

A state-machine based energy management system for Home Assistant, optimized for Dutch energy suppliers that bill on **TenneT imbalance settlement prices** (not day-ahead). Built for hybrid inverters with battery storage and optional dumpload.

## What It Does

Monitors real-time TenneT imbalance prices and automatically adjusts your solar inverter to maximize profit and minimize losses:

| State | When | What happens |
|-------|------|-------------|
| **NORMAL** | Sell price > 2ct | Full PV production, export enabled, earn on export |
| **SELF_CONSUME** | Sell < 2ct, buy > -2ct | Full PV, zero-export mode, avoid selling at loss |
| **SELL** | Price spike (>30ct above 24h avg) | Stop battery charging, maximize export at spike price |
| **GRID_USE** | Buy < -2ct | Curtail PV, stop battery discharge, household consumes from grid |
| **DUMP** | Buy < -9ct, dumpload connected | Activate 15kW dumpload heater, maximize grid consumption |

### Safety Features

- **Parallel timer system** prevents state flipping: SLOW (10min), FAST (3min), INSTANT (>15ct spread)
- **Soft Fuse** monitors P1 per-phase current every 10s and adjusts the battery discharge ceiling to protect your fuses
- **Charge-current fail-safe**: every non-SELL state restores full charge current, so leaving a SELL spike can never strand the battery at 0 A charge
- **SOC fallback** exits DUMP when battery drops below 60%
- **Opt-in states** for anything that overrides battery registers (SELL, GRID_USE, DUMP default to OFF)

## Who Is This For

- Dutch households on any energy supplier billing on **TenneT imbalance settlement prices**
- Hybrid inverter with Modbus control (tested on Deye SUN-12K via Solarman)
- Optional: dumpload heater on SmartLoad/GEN port, P1 smart meter for fuse protection

## Quick Start

### Prerequisites

- Home Assistant with [packages](https://www.home-assistant.io/docs/configuration/packages/) enabled
- Inverter integration with Modbus control (Solarman, SolarAssistant, etc.)
- HACS frontend: [fold-entity-row](https://github.com/thomasloven/lovelace-fold-entity-row), [ApexCharts](https://github.com/RomRider/apexcharts-card) (optional, for dashboard)
- Optional: [Nord Pool](https://github.com/custom-components/nordpool) integration (only for day-ahead price display on dashboard, not used by the EMS)

### Installation

1. **Copy** `packages/energy/` to your HA config directory
2. **Customize** entity IDs for your inverter — see [CUSTOMIZE.md](CUSTOMIZE.md)
3. **Add to configuration.yaml** (if not already using packages):
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
4. **Restart HA** and verify entities appear
5. **Enable states** you want via the dashboard toggles (all OFF by default)

### File Overview

| File | Purpose |
|------|---------|
| `imbalance_pricing.yaml` | TenneT real-time price sensor (polls TenEnergy every 60s) |
| `epex_predictor.yaml` | EpexPredictor 5-day price forecast (LightGBM model) |
| `energy_helpers.yaml` | All configurable parameters, timers, state toggles |
| `energy_state_machine.yaml` | Core: ideal state sensor, transition logic, state entry script |
| `energy_soft_fuse.yaml` | Independent fuse protection (needs P1 meter) |
| `energy_gen_port.yaml` | GEN port mode selector (remove if not applicable) |
| `energy_forecast.yaml` | Look-ahead "connect the dumpload" notification |
| `power_monitoring.yaml` | Net house usage + total PV sensors (the dashboard uses `sensor.nett_energy_use_house`) |
| `afrr_pv_priority.yaml` | Proactive discharge-current cap so aFRR discharge doesn't curtail rooftop PV (see [CUSTOMIZE.md](CUSTOMIZE.md)) |
| `morning_export_priority.yaml` | **Experimental**, optional, master-OFF — Solcast-gated morning PV export (see below) |

### Dashboard

Copy card configurations from `dashboard/cards.yaml` into your Lovelace dashboard. Requires `fold-entity-row` for collapsible settings sections.

## How It Works

### State Selection

Every 60 seconds (when prices update), the system computes the "ideal state" from current sell/buy prices. Transitions between states are governed by parallel timers:

```
Price signal → Compute ideal state → Compare with current
                                          ↓
                   spread < 2ct (hysteresis) → ignore
                   spread 2-15ct → SLOW timer (10min) + FAST timer (3min)
                   spread > 15ct → INSTANT transition
```

SELL state bypasses timers entirely (price spikes are fleeting).

### Supplier Fee

The supplier fee (default 2ct/kWh) on both import and export creates a natural 4ct dead zone. Combined with TenneT's buy/sell spread during regulation events, the total anti-oscillation margin is often 10-20ct.

### Opt-In States

Three states override battery registers that your energy supplier's EMS might also control:

- **SELL**: Sets battery charging current to 0 (stops PV→battery)
- **GRID_USE**: Sets battery discharge current to 0 (stops battery→household)
- **DUMP**: Same as GRID_USE + activates dumpload

All three default to OFF. Enable them via dashboard toggles when you're comfortable with the trade-off.

### Coexisting with an external supplier EMS

If your energy supplier also runs its own EMS that writes the inverter (for example to grid-charge the battery on cheap imbalance buy prices), this package is built to share the inverter rather than fight it:

- **Grid-charge ownership yield**: only the **SELL** state forces the grid-charge switch (`switch.inverter_battery_grid_charging`) OFF — you never want to pull from the grid while exporting into a price spike. In **NORMAL** and **SELF_CONSUME** the package no longer touches that switch, leaving grid-charging to the external supplier EMS.
- **Charge-current fail-safe default**: before applying any state, `script.ems_apply_state` writes the full charge-current limit (240 A); only the SELL branch overrides it to 0 A. This means leaving a SELL spike always restores charging, so a SELL→NORMAL transition can never strand the battery at 0 A charge.
- **Manual state override**: picking a state from the `EMS State` dropdown re-runs the apply script (loop-safe, gated on a UI user context), so a manual selection actually actuates the inverter levers instead of just updating the status tracker. The EMS keeps evaluating prices and transitions away normally afterward.
- **PV-cap refresh**: in `DUMP`/`GRID_USE` the PV limit is re-asserted every 30 s, because an external writer (the supplier EMS or a firmware watchdog) periodically clears the PV-limit register.

### Soft Fuse (battery-discharge ceiling)

The Soft Fuse is an independent safety layer (gated on the global `ems_enabled`) that watches P1 per-phase current every 10 s and protects your fuses by adjusting the **battery discharge ceiling** (`number.inverter_battery_max_discharging_current`). It steps the ceiling **up** on overload and ladders it **down** when phases are comfortably safe, using a `5 A of discharge ceiling per 1 A of phase overshoot` formula with a 30 s cooldown between up-steps. (Earlier versions lifted PV instead; the inverter firmware only honors the PV limit in some work modes, whereas the discharge-ceiling register is honored everywhere and written instantly.) See [CUSTOMIZE.md](CUSTOMIZE.md) for fuse-rating and single-phase tuning.

### aFRR PV Priority

`afrr_pv_priority.yaml` proactively caps battery discharge current during aFRR/imbalance discharge so battery + PV together stay just under the inverter's AC output ceiling, keeping rooftop PV (MPPT) from being curtailed to 0 W. It has its own master toggle (`input_boolean.afrr_pv_priority_enabled`, default OFF) and nine `afrr_*` tunables — see [CUSTOMIZE.md](CUSTOMIZE.md).

### Experimental: Morning Export Priority (Solcast)

`morning_export_priority.yaml` is **optional, experimental, and ships master-OFF** (`input_boolean.mep_enabled`). During a morning window, and only while the EMS is in NORMAL, it soft-floors the battery **charge** current so morning PV exports at positive prices — but only when a Solcast forecast says the midday cheap-price PV will refill the pack. It depends on extra entities not in the core EMS (Solcast forecast, a price sensor with `prices_today`, a daily consumption `utility_meter`, and `sensor.inverter_battery_capacity`). It is not production-validated; leave it disabled until you have dry-run it on your own data. See [CUSTOMIZE.md](CUSTOMIZE.md) for the full dependency list.

## Algorithm Verification

Run the simulation to verify the state machine logic:

```bash
python3 simulation/ems_simulation.py
```

This tests ideal state selection, timer behavior, spread calculations, control levers, and a realistic day scenario with all 5 states.

## Configuration

All parameters are tunable via the HA dashboard (Advanced Settings folds). See [CUSTOMIZE.md](CUSTOMIZE.md) for entity mapping and detailed parameter descriptions.

## Limitations

- **Grid charging does not work** in Deye "Zero Export To CT" mode. The GRID_USE state can only reduce consumption, not actively charge the battery from grid.
- **Battery arbitrage** (charge cheap, sell expensive) is not implemented — this tool focuses on overproduction and negative price scenarios.
- **Single supplier**: Designed for TenneT imbalance settlement pricing (NL). Other countries or day-ahead billing models may not benefit.

## Credits


- **Imbalance price sensor** based on work by [MertijnW](https://gathering.tweakers.net/forum/list_message/84349072#84349072) using the TenEnergy API (https://services.tenergy.nl)
- **EpexPredictor** by [b3nn0](https://github.com/b3nn0/EpexPredictor) — LightGBM price forecast model

## License

This work is licensed under [Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-nc-sa/4.0/).

You are free to use, modify, and share this for **personal and non-commercial use**. Commercial use (including by energy companies, SaaS products, or paid services) requires explicit permission from the author.

[![CC BY-NC-SA 4.0](https://licensebuttons.net/l/by-nc-sa/4.0/88x31.png)](https://creativecommons.org/licenses/by-nc-sa/4.0/)
