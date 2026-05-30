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
| `switch.inverter_battery_grid_charging` | Grid-charge enable (only forced OFF in SELL) | _your grid-charge enable switch_ |
| `select.inverter_io_mode` | GEN port function selector — set to `Generator`/`SmartLoad` to actuate the dumpload | _your GEN/AUX port mode selector (remove if you don't have one)_ |
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
- Update `energy_soft_fuse.yaml`: it reads three phase-current sensors (`l1`, `l2`, `l3`) and acts on the worst (`max_phase`). For single-phase, point all three at your one current sensor (or trim to just `l1`).
- The correction is now a battery-discharge-ceiling formula (`5 A of discharge ceiling per 1 A of phase overshoot`), not the old PV-lift `× 230 × 3` term — there is no per-phase multiplier to change. Adjust the zone thresholds (`23`/`26 A`) and the `fuse_limit`/SAFE target (`25`/`24 A`) to your fuse rating instead.
- Or skip the Soft Fuse entirely if your fuse rating has enough headroom.

## Supplier Fee

The default `provider_fee` is 20 EUR/MWh (2ct/kWh) — this is the supplier's per-kWh markup. If your energy supplier charges a different fee, adjust this helper. If your supplier bills on day-ahead instead of imbalance prices, this entire package may not be useful for you.

## Tuning Parameters

All parameters are adjustable via the dashboard (Advanced Settings folds). Start with defaults and tune based on your observations:

| Parameter | Default | What to watch |
|---|---|---|
| Hysteresis | 2ct | Lower = more responsive, higher = more stable |
| Slow Timer | 10min | How long a moderate price signal must sustain |
| Fast Timer | 3min | How long a strong price signal must sustain |
| Instant Spread | 15ct | Price swing that triggers immediate transition |
| Spike Spread | 30ct | How far above 24h average triggers SELL |
| Spike Floor | 40ct | Absolute minimum sell price for SELL |
| Dump Profit | 7ct | Minimum per-kWh profit to activate dumpload |

## aFRR PV Priority (`afrr_pv_priority.yaml`)

When the inverter discharges hard into an aFRR/imbalance event, battery at full
240 A can saturate the ~12 kW AC output, forcing rooftop PV (MPPT) to curtail to
0 W and wasting free solar. This layer proactively caps battery discharge current
so that `battery + PV` together target a combined AC ceiling that sits just under
the inverter limit, keeping MPPT active. It only modulates discharge current in
`NORMAL`/`SELL`/`SELF_CONSUME`; in `GRID_USE`/`DUMP` the state machine owns the
discharge lever.

It needs these extra inverter entities (remap to your hardware):

| This package uses | What it does |
|---|---|
| `sensor.inverter_battery_voltage` | Battery pack voltage (V), used to convert target W → A |
| `select.inverter_work_mode` | Inverter work mode; prestage only runs in `Zero Export To CT` |

### Master toggle

`input_boolean.afrr_pv_priority_enabled` gates the whole layer (in addition to the
global `input_boolean.ems_enabled`). Leave it OFF until you have verified the
discharge clamp behaves on your inverter.

### Tunables (`afrr_*` in `energy_helpers.yaml`)

| Helper | Default | What it does |
|---|---|---|
| `afrr_ac_ceiling` | 11800 W | Combined battery + PV target; sit a margin under your inverter's AC ceiling |
| `afrr_pv_threshold` | 500 W | Below this PV, prefer full 240 A discharge (savings negligible) |
| `afrr_target_floor_w` | 2000 W | Minimum power the battery must keep contributing (keep > 0 for BMS stability) |
| `afrr_min_amps` | 40 A | Lower clamp on computed discharge current |
| `afrr_max_amps` | 240 A | Upper clamp / restore value (your discharge hardware ceiling) |
| `afrr_pv_padding_pct` | 5 % | PV over-estimate at high PV, to absorb upward fluctuations |
| `afrr_pv_padding_flat` | 200 W | PV over-estimate at low PV (the smaller of the two pads wins) |
| `afrr_step_deadband` | 5 A | Minimum register change before writing (prevents Modbus/EEPROM thrash) |
| `afrr_restore_delay` | 2 min | How long PV must stay below threshold before restoring full discharge |

## EXPERIMENTAL: Morning Export Priority / Solcast PV-charge-block (`morning_export_priority.yaml`)

**Not production-validated. Ships master-OFF (`input_boolean.mep_enabled`). Optional file — leave it out if you don't have the dependencies below.**

During a morning window and only while the EMS is in `NORMAL`, this soft-floors
the battery **charge** current (default ~20 A ≈ 1 kW) so morning PV is exported at
positive prices instead of charging the pack — but only when a Solcast forecast
says the midday cheap-price PV will still refill the battery (with a consumption
buffer). It is the charge-side mirror of the aFRR discharge layer.

This feature pulls in entities that are NOT part of the core EMS and are not in
the mapping tables above. You must provide all of them:

| Dependency | What it must expose |
|---|---|
| `sensor.solcast_pv_forecast_forecast_today` | Solcast integration; needs a `detailedForecast` attribute with `period_start`, `pv_estimate10`, `pv_estimate`, `pv_estimate90` (P10/P50/P90) |
| `sensor.average_electricity_price` | A price sensor with a `prices_today` attribute (list of `{time, price}` entries, price in EUR/kWh) |
| `sensor.daily_energy_usage_house` | A `utility_meter` (daily reset, in Wh) whose `last_period` attribute holds yesterday's total |
| `sensor.inverter_battery_capacity` | Usable pack capacity in kWh |

### MEP helpers (`mep_*`, defined in `morning_export_priority.yaml`)

| Helper | Default | What it does |
|---|---|---|
| `input_boolean.mep_enabled` | OFF | Master gate for the feature |
| `input_number.mep_charge_floor_amps` | 20 A | Soft floor written to the charge register while deferring |
| `input_number.mep_charge_restore_amps` | 240 A | Value restored when not deferring (the one deliberate `initial:` exception, boot-safe) |
| `input_number.mep_soc_floor` | 30 % | Never defer below this SOC (charge from morning sun instead) |
| `input_number.mep_pv_weight_p10` / `_p50` / `_p90` | 50 / 50 / 0 | Solcast P10/P50/P90 blend weights |
| `input_number.mep_step_deadband` | 5 A | Minimum register change before writing |
| `input_datetime.mep_window_start` / `mep_window_end` | 06:00 / 12:00 | Morning deferral window (time-only) |

Treat the whole feature as untested: dry-run with `mep_enabled` OFF, watch
`sensor.mep_margin` and `binary_sensor.mep_defer_charging`, and only enable it once
you trust the forecast on your own data.
