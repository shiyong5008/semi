from __future__ import annotations

import csv
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fab_sim.config import FabConfig
from fab_sim.simulation import FabSimulation, SimulationParameters


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FabSimulationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = FabConfig.from_directory(PROJECT_ROOT / "data")

    def test_simulation_parameters_load_from_csv(self) -> None:
        parameters = SimulationParameters.from_csv(
            PROJECT_ROOT / "data" / "simulation_parameters.csv"
        )

        self.assertEqual(parameters.lots_per_shift, 20)
        self.assertEqual(parameters.duration_hours, 168)
        self.assertEqual(parameters.wafers_per_lot, 25)
        self.assertEqual(parameters.wait_for_full_batch_mins, 30)
        self.assertEqual(parameters.random_seed, 1)

    def test_batching_statuses_and_history_exports(self) -> None:
        simulation = FabSimulation(
            self.config,
            SimulationParameters(lots_per_shift=720, duration_hours=30),
        )
        event_log = simulation.run()

        lot_events = [event for event in event_log.events if event.entity_type == "lot"]
        tool_events = [event for event in event_log.events if event.entity_type == "tool"]
        dispatched_batches = [
            event for event in tool_events if event.event == "batch dispatched"
        ]
        self.assertTrue(dispatched_batches)
        self.assertEqual(dispatched_batches[0].lot_ids.count(";"), 2)
        self.assertTrue(any(event.status == "hold" for event in lot_events))
        self.assertTrue(any(event.event == "in process" for event in tool_events))

        lot_101 = [
            event
            for event in lot_events
            if event.entity_id == "Lot101"
        ]
        stage_exit_index = next(
            index
            for index, event in enumerate(lot_101)
            if event.event == "moved out of operation" and event.operation_id == 907
        )
        furnace_entry_index = next(
            index
            for index, event in enumerate(lot_101)
            if event.event == "moved into operation" and event.operation_id == 908
        )
        self.assertLess(stage_exit_index, furnace_entry_index)

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            event_log.write_csvs(output_dir)
            for filename in ("events.csv", "lot_history.csv", "tool_history.csv"):
                with (output_dir / filename).open(encoding="utf-8", newline="") as csv_file:
                    self.assertTrue(next(csv.DictReader(csv_file)))

    def test_run_count_pm_is_triggered_after_a_load(self) -> None:
        tools = tuple(
            replace(tool, pm_run_count=1, pm_mins_count=100_000)
            if tool.tool_id.startswith("VFP")
            else tool
            for tool in self.config.tools
        )
        config = FabConfig(tools, self.config.tool_operations, self.config.operations)
        simulation = FabSimulation(
            config,
            SimulationParameters(lots_per_shift=720, duration_hours=16),
        )

        tool_events = [
            event for event in simulation.run().events if event.entity_type == "tool"
        ]
        self.assertTrue(
            any(
                event.event == "PM started" and event.details == "trigger: run count"
                for event in tool_events
            )
        )

    def test_time_pm_is_triggered_and_logged(self) -> None:
        tools = tuple(
            replace(tool, pm_mins_count=30)
            if tool.tool_id.startswith("VFP")
            else tool
            for tool in self.config.tools
        )
        config = FabConfig(tools, self.config.tool_operations, self.config.operations)
        simulation = FabSimulation(
            config,
            SimulationParameters(lots_per_shift=720, duration_hours=16),
        )

        tool_events = [
            event for event in simulation.run().events if event.entity_type == "tool"
        ]
        self.assertTrue(
            any(
                event.event == "PM started" and event.details == "trigger: time"
                for event in tool_events
            )
        )


if __name__ == "__main__":
    unittest.main()
