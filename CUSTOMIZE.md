# Customization Guide

This package was built for a Deye SUN-12K-SG04LP3-EU hybrid inverter with the Solarman integration. If you use different hardware, you'll need to remap entity IDs.

## Entity Mapping

### Inverter Control (Solarman → your integration)

| This package uses | What it does | Your entity |
|---|---|---|
| `number.inverter_pv_power` | PV production limit (0-13000W) | _your inverter's PV limit register_ |
| `number.inverter_battery_max_discharging_current` | Battery discharge limit (0-240A) | _your battery discharge register_ |
| `number.inverter_battery_max_charging_current` | Battery charge limit (0-240A) | _your battery charge register_ |
| `switch.inverter_export_surplus` | Solar Sell / grid export toggle | _your export enable switch_ |
| `switch.inverter_generator` | SmartLoad / dumpload toggle | _your dumpload relay or smart switch_ |
| `select.inverter_io_mode` | GEN port function selector | _remove if you don't have a GEN port_ |
| `sensor.inverter_pv_power` | Current PV production (W) | _your PV power sensor_ |
| `sensor.inverter_battery` | Battery SOC (%) | _your battery SOC sensor_ |

### P1 Smart Meter (ESPHome → your meter)

| This package uses | What it does | Your entity |
|---|---|---|
| `sensor.p1reader2_p1_reader_2_current_l1` | Phase 1 current (A) | _your P1/CT meter L1 current_ |
| `sensor.p1reader2_p1_reader_2_current_l2` | Phase 2 current (A) | _your P1/CT meter L2 current_ |
| `sensor.p1reader2_p1_reader_2_current_l3` | Phase 3 current (A) | _your P1/CT meter L3 current_ |

**No P1 meter?** You can skip `energy_soft_fuse.yaml` entirely. The state machine works without it — you just won't have fuse protection.

### Price Sensors

| This package uses | What it does | Notes |
|---|---|---|
| `sensor.tennet_imbalance_sell_price` | TenneT sell price (EUR/MWh) | Created by `imbalance_pricing.yaml` — works for all NL users |
| `sensor.tennet_imbalance_buy_price` | TenneT buy price (EUR/MWh) | Same |
| `sensor.tennet_imbalance_regelstand` | Grid regulation state | Same |
| `sensor.epex_predictor_nl` | 5-day price forecast | Created by `epex_predictor.yaml` — works for NL |
| `sensor.nord_pool_nl_current_price` | Day-ahead spot price (optional) | Only for dashboard display — not used by EMS logic |

### Notifications

`energy_forecast.yaml` uses `notify.notify` as a placeholder. Change it to your mobile app notify service (e.g., `notify.mobile_app_your_phone`) or remove the file if you don't need the "plug in dumpload" lookahead warning.

## What to Remove If You Don't Have...

### No dumpload heater
- Remove `energy_gen_port.yaml`
- Remove DUMP-related helpers (`dump_soc_entry`, `dump_soc_fallback`, `dumpload_profit_threshold`) from `energy_helpers.yaml`
- The state machine will never enter DUMP (requires `gen_port_mode = SmartLoad`)

### No GEN port / single-purpose inverter
- Remove `energy_gen_port.yaml`
- Remove `input_select.gen_port_mode` from `energy_helpers.yaml`
- Remove the `gen_port` check from the DUMP condition in `energy_state_machine.yaml`

### Single-phase system
- Update `energy_soft_fuse.yaml`: remove L2/L3 references, change `× 3` to `× 1` in correction formulas
- Or skip the Soft Fuse entirely if your fuse rating has enough headroom

## Supplier Fee

The default `provider_fee` is 20 EUR/MWh (2ct/kWh) — this is the supplier's per-kWh markup. If your energy supplier charges a different fee, adjust this helper. If your supplier bills on day-ahead instead of imbalance prices, this entire package may not be useful for you.

## Tuning Parameters

All parameters are adjustable via the dashboard (Advanced Settings folds). Start with defaults and tune based on your observations:

| Parameter | Default | What to watch |
|---|---|---|
| Hysteresis | 5ct | Lower = more responsive, higher = more stable |
| Slow Timer | 10min | How long a moderate price signal must sustain |
| Fast Timer | 3min | How long a strong price signal must sustain |
| Instant Spread | 15ct | Price swing that triggers immediate transition |
| Spike Spread | 30ct | How far above 24h average triggers SELL |
| Spike Floor | 40ct | Absolute minimum sell price for SELL |
| Dump Profit | 7ct | Minimum per-kWh profit to activate dumpload |
