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
- **Soft Fuse** monitors P1 per-phase current every 10s, adjusts PV to protect your fuses
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

### Dashboard

Copy card configurations from `dashboard/cards.yaml` into your Lovelace dashboard. Requires `fold-entity-row` for collapsible settings sections.

## How It Works

### State Selection

Every 60 seconds (when prices update), the system computes the "ideal state" from current sell/buy prices. Transitions between states are governed by parallel timers:

```
Price signal → Compute ideal state → Compare with current
                                          ↓
                   spread < 5ct (hysteresis) → ignore
                   spread 5-15ct → SLOW timer (10min) + FAST timer (3min)
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
