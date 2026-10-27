from __future__ import annotations

import argparse
import logging
from pathlib import Path

from fab_sim.config import FabConfig
from fab_sim.simulation import FabSimulation, SimulationParameters


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate the poly fab operations")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument(
        "--data-dir", type=Path, default=Path("data"),
        help="Directory containing the simulation parameter and poly config CSV files",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = FabConfig.from_directory(args.data_dir)
    parameters = SimulationParameters.from_csv(
        args.data_dir / "simulation_parameters.csv"
    )
    event_log = FabSimulation(config, parameters).run()
    event_log.write_csvs(args.output_dir)
    print(f"Wrote simulation histories to {args.output_dir}")
    print(f"Recorded {len(event_log.events)} events")


if __name__ == "__main__":
    main()
