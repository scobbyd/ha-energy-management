# Home Assistant Energy Management System (archived)

This repository is archived. The state-machine EMS it published, which steered a
Deye hybrid inverter on real-time TenneT imbalance prices, has been retired on the
site it was built for and is no longer maintained.

## Where to go instead

**[deye-dayahead-ems](https://github.com/scobbyd/deye-dayahead-ems)** is its
successor: a day-ahead battery planner (EMHASS, 15-minute solves) with a writer
that drives the Deye directly, plus the backtest that shows whether a battery pays
off on your own data. It runs live on the same plant.

## Why it was retired

The state machine reacted to the imbalance price minute by minute: NORMAL,
SELF_CONSUME, SELL, GRID_USE and DUMP states, with timers against flapping and a
soft fuse on the P1 phase currents. It worked, but a reactive controller cannot
plan a battery across a day. When the site changed supplier and moved to a
day-ahead tariff, a planner that optimises the whole horizon (charge when cheap or
sunny, discharge into the expensive hours, keep a reserve) came out clearly ahead
in backtests, and the state machine, soft fuse, helpers, forecast, generator-port,
aFRR PV-priority and morning-export packages were removed.

## What is still here

Three standalone packages that do not depend on the retired EMS, frozen as last
synced (2026-05-30):

| Package | What it does |
|---|---|
| `packages/energy/imbalance_pricing.yaml` | TenneT imbalance prices from the free TenEnergy endpoint, for suppliers that bill on settlement prices |
| `packages/energy/epex_predictor.yaml` | EPEX day-ahead price predictions (120 h, 15-minute) from the public [EpexPredictor](https://github.com/b3nn0/EpexPredictor) API |
| `packages/energy/power_monitoring.yaml` | Net house usage, consumption and production template sensors |

## The full previous system

The complete state-machine EMS (packages, dashboard cards, simulation and the
customisation guide) is preserved at the tag
[`v1-imbalance-state-machine`](https://github.com/scobbyd/ha-energy-management/tree/v1-imbalance-state-machine).

## License

MIT, see [LICENSE](LICENSE).
