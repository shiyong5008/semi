# Poly-operation fab simulation

This repository contains a small SimPy discrete-event simulation driven by the
three configuration files in `data/`:

- `poly_config_ops.csv` defines operations 907 (`d-poly-stage`) and 908
  (`d-poly`), including each operation's maximum queue time.
- `poly_config_tool.csv` defines the tools. STG907 is configured as a virtual
  tool; VFP701 and VFP702 are furnace tools with preventive-maintenance limits.
- `poly_config_tool-ops.csv` maps tools to operations and defines wafer batch
  limits and processing time per load.

The configured flow modeled by the simulator is operation 907 followed by
operation 908. There is no WetEtch step in these configuration files, and this
project does not use a `job_routes.csv` route table.

## Simulation parameters

Edit `data/simulation_parameters.csv` to set the run inputs:

| Parameter | Meaning |
| --- | --- |
| `lots_per_shift` | Average number of arriving lots per 12-hour shift. Arrivals are stochastic, not evenly spaced. |
| `duration_hours` | Total simulated time. The simulation stops at this time; it does not drain unfinished work. |
| `wafers_per_lot` | Wafer count assigned to each created lot. |
| `op_908_wait_for_third_lot_mins` | How long the dispatcher waits for a third lot after two are waiting for operation 908. |
| `random_seed` | Seed for reproducible random lot-arrival times. |

The checked-in parameter file currently specifies 20 lots per shift, 168
simulation hours, 25 wafers per lot, a 30-minute wait for a third lot, and seed
1.

## Current simulation behavior

Install the dependency and run the simulator from the repository root:

```sh
python -m pip install -r requirements.txt
python -m fab_sim
```

Lot arrivals follow a Poisson process. Operation 907 is processed one lot at a
time on STG907. For operation 908, the configured batch limits are 37–75
wafers: with 25 wafers per lot, two lots meet the minimum and three lots fill a
75-wafer load. If only two lots are waiting, the dispatcher waits for the
configured time for a third; if it does not arrive, the two-lot batch is
released.

VFP701 and VFP702 are parallel tools for operation 908. Each load counts as one
run for PM, whether it contains two or three lots. PM is triggered by whichever
configured enabled limit is reached first: run count or elapsed time. A
time-triggered PM waits for an active load to finish before taking the tool
offline. Queue-time limits are checked against each lot's elapsed time in the
operation, including waiting and processing. A lot that exceeds the limit is
still processed and changes to `hold` when it exits the operation.

## Output

By default, the simulation writes these files to `output/`:

- `events.csv`: combined chronological event log.
- `lot_history.csv`: events for each lot, including status and operation
  transitions.
- `tool_history.csv`: tool processing and PM events, with associated lot IDs.

Times in the logs are simulated minutes. Change the output path with
`--output-dir`, or the configuration directory with `--data-dir`.
