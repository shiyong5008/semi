from __future__ import annotations

import logging
import math
import random
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import simpy

from fab_sim.config import FabConfig, OperationConfig, ToolOperationConfig
from fab_sim.event_log import EventLog
from fab_sim.models import Lot, Tool

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SimulationParameters:
    lots_per_shift: float = 6.0
    duration_hours: float = 168.0
    wafers_per_lot: int = 25
    wait_for_full_batch_mins: float = 30.0
    random_seed: int = 1

    @classmethod
    def from_csv(cls, path: Path) -> SimulationParameters:
        with path.open(newline="", encoding="utf-8") as csv_file:
            rows = csv.DictReader(csv_file)
            if rows.fieldnames != ["parameter", "value"]:
                raise ValueError(
                    f"{path} must have exactly these columns: parameter,value"
                )
            values: dict[str, str] = {}
            for row in rows:
                name = row["parameter"].strip()
                if not name:
                    raise ValueError(f"Blank parameter name in {path}")
                if name in values:
                    raise ValueError(f"Duplicate parameter {name!r} in {path}")
                values[name] = row["value"].strip()

        expected = {
            "lots_per_shift",
            "duration_hours",
            "wafers_per_lot",
            "op_908_wait_for_third_lot_mins",
            "random_seed",
        }
        missing = expected - values.keys()
        unknown = values.keys() - expected
        if missing or unknown:
            raise ValueError(
                f"Invalid parameters in {path}: missing={sorted(missing)}, "
                f"unknown={sorted(unknown)}"
            )

        parameters = cls(
            lots_per_shift=float(values["lots_per_shift"]),
            duration_hours=float(values["duration_hours"]),
            wafers_per_lot=int(values["wafers_per_lot"]),
            wait_for_full_batch_mins=float(
                values["op_908_wait_for_third_lot_mins"]
            ),
            random_seed=int(values["random_seed"]),
        )
        parameters.validate()
        return parameters

    def validate(self) -> None:
        if self.lots_per_shift <= 0:
            raise ValueError("Lots per 12-hour shift must be greater than zero")
        if self.duration_hours <= 0:
            raise ValueError("Simulation duration must be greater than zero")
        if self.wafers_per_lot <= 0:
            raise ValueError("Wafer count per lot must be greater than zero")
        if self.wait_for_full_batch_mins < 0:
            raise ValueError("Batch wait time cannot be negative")


class FabSimulation:
    def __init__(
        self,
        config: FabConfig,
        parameters: SimulationParameters,
    ) -> None:
        parameters.validate()
        self.config = config
        self.parameters = parameters
        self.env = simpy.Environment()
        self.events = EventLog()
        self.random = random.Random(parameters.random_seed)
        self.lots: dict[str, Lot] = {}
        self.waiting_lots: simpy.Store = simpy.Store(self.env)
        self.tools = self._create_tools()
        self.tool_by_id = {tool.config.tool_id: tool for tool in self.tools}
        self.operation_by_id = {
            operation.ops_id: operation for operation in config.operations
        }
        self.mappings_by_operation = self._mappings_by_operation()
        self._next_lot_number = 101

    def run(self) -> EventLog:
        self.env.process(self._create_lots())
        self.env.process(self._batch_dispatcher())
        for tool in self.tools:
            self.env.process(self._tool_worker(tool))
            if tool.config.time_count_flag:
                self.env.process(self._time_based_pm(tool))
        self.env.run(until=self.parameters.duration_hours * 60)
        LOGGER.info("Simulation stopped at %.1f minutes", self.env.now)
        return self.events

    def _create_tools(self) -> list[Tool]:
        tools_by_id = {tool.tool_id: tool for tool in self.config.tools}
        tools: list[Tool] = []
        for mapping in self.config.tool_operations:
            tool_config = tools_by_id[mapping.tool_id]
            tools.append(
                Tool(
                    config=tool_config,
                    operation_config=mapping,
                    resource=simpy.PriorityResource(
                        self.env, capacity=tool_config.chambers_per_tool
                    ),
                    batch_queue=simpy.Store(self.env),
                )
            )
        return tools

    def _mappings_by_operation(self) -> dict[int, list[ToolOperationConfig]]:
        mappings: dict[int, list[ToolOperationConfig]] = {}
        for mapping in self.config.tool_operations:
            mappings.setdefault(mapping.ops_id, []).append(mapping)
        for operation_mappings in mappings.values():
            operation_mappings.sort(key=lambda mapping: mapping.tool_id)
        return mappings

    def _create_lots(self) -> Iterator[simpy.Event]:
        while True:
            interarrival = self.random.expovariate(
                self.parameters.lots_per_shift / (12 * 60)
            )
            yield self.env.timeout(interarrival)
            lot_id = f"Lot{self._next_lot_number}"
            self._next_lot_number += 1
            lot = Lot(lot_id, self.parameters.wafers_per_lot)
            self.lots[lot_id] = lot
            self.events.record(
                self.env.now,
                "lot",
                lot_id,
                "created",
                status=lot.status,
                details=f"{lot.wafer_count} wafers",
            )
            self.env.process(self._lot_flow(lot))

    def _lot_flow(self, lot: Lot) -> Iterator[simpy.Event]:
        for operation in sorted(self.config.operations, key=lambda item: item.ops_id):
            mappings = self.mappings_by_operation.get(operation.ops_id, [])
            if not mappings:
                raise ValueError(f"No tools are configured for operation {operation.ops_id}")

            if self._is_batch_operation(mappings):
                self._enter_operation(lot, operation)
                yield self.waiting_lots.put(lot)
                continue

            mapping = mappings[0]
            tool = self.tool_by_id[mapping.tool_id]
            self._enter_operation(lot, operation)
            with tool.resource.request(priority=1) as request:
                yield request
                self._record_lot(
                    lot, "processing started", operation, tool=tool, lot_ids=(lot.lot_id,)
                )
                self.events.record(
                    self.env.now,
                    "tool",
                    tool.config.tool_id,
                    "in process",
                    operation_id=operation.ops_id,
                    tool_id=tool.config.tool_id,
                    lot_ids=(lot.lot_id,),
                    details="1 lot",
                )
                yield self.env.timeout(mapping.proc_time_per_load_mins)
                self._record_lot(
                    lot, "processing completed", operation, tool=tool, lot_ids=(lot.lot_id,)
                )
                self._record_tool(
                    tool, "process completed", (lot.lot_id,), operation.ops_id
                )
            self._leave_operation(lot, operation)

    def _is_batch_operation(
        self, mappings: list[ToolOperationConfig]
    ) -> bool:
        return len(mappings) > 1 or any(
            mapping.batch_size_min > self.parameters.wafers_per_lot
            for mapping in mappings
        )

    def _enter_operation(self, lot: Lot, operation: OperationConfig) -> None:
        lot.operation_entry_times[operation.ops_id] = self.env.now
        self._record_lot(lot, "moved into operation", operation)

    def _leave_operation(self, lot: Lot, operation: OperationConfig) -> None:
        entered_at = lot.operation_entry_times.pop(operation.ops_id)
        elapsed = self.env.now - entered_at
        breached = elapsed > operation.max_q_time_mins
        if breached:
            lot.status = "hold"
        self._record_lot(
            lot,
            "moved out of operation",
            operation,
            status=lot.status,
            details=(
                f"operation elapsed {elapsed:.1f} min; "
                f"limit {operation.max_q_time_mins} min"
            ),
        )

    def _batch_dispatcher(self) -> Iterator[simpy.Event]:
        mappings = self.mappings_by_operation.get(908, [])
        if not mappings:
            return
        min_batch_lots = max(
            math.ceil(mapping.batch_size_min / self.parameters.wafers_per_lot)
            for mapping in mappings
        )
        max_batch_lots = min(
            mapping.batch_size_max // self.parameters.wafers_per_lot
            for mapping in mappings
        )
        if min_batch_lots > max_batch_lots:
            raise ValueError(
                "Operation 908 batch limits cannot be met with the configured "
                "wafer count per lot"
            )
        operation = self.operation_by_id[908]
        pending: list[Lot] = []
        while True:
            while len(pending) < min_batch_lots:
                pending.append((yield self.waiting_lots.get()))

            if len(pending) < max_batch_lots:
                deadline = self.env.timeout(
                    self.parameters.wait_for_full_batch_mins
                )
                while len(pending) < max_batch_lots:
                    next_lot = self.waiting_lots.get()
                    result = yield next_lot | deadline
                    if next_lot in result:
                        pending.append(result[next_lot])
                    else:
                        next_lot.cancel()
                        break

            batch = pending[:max_batch_lots]
            del pending[:len(batch)]
            tool = self._select_tool(mappings)
            self.events.record(
                self.env.now,
                "tool",
                tool.config.tool_id,
                "batch dispatched",
                operation_id=operation.ops_id,
                tool_id=tool.config.tool_id,
                lot_ids=tuple(lot.lot_id for lot in batch),
                details=f"{len(batch)} lots",
            )
            yield tool.batch_queue.put((batch, operation))

    def _select_tool(self, mappings: list[ToolOperationConfig]) -> Tool:
        eligible_tools = [self.tool_by_id[mapping.tool_id] for mapping in mappings]
        tool = min(
            eligible_tools,
            key=lambda item: (item.estimated_available_at, item.config.tool_id),
        )
        mapping = tool.operation_config
        tool.estimated_available_at = max(
            self.env.now, tool.estimated_available_at
        ) + mapping.proc_time_per_load_mins
        return tool

    def _tool_worker(self, tool: Tool) -> Iterator[simpy.Event]:
        while True:
            batch, operation = yield tool.batch_queue.get()
            lot_ids = tuple(lot.lot_id for lot in batch)
            with tool.resource.request(priority=1) as request:
                yield request
                for lot in batch:
                    self._record_lot(
                        lot,
                        "processing started",
                        operation,
                        tool=tool,
                        lot_ids=lot_ids,
                    )
                self._record_tool(tool, "in process", lot_ids, operation.ops_id)
                yield self.env.timeout(tool.operation_config.proc_time_per_load_mins)
                for lot in batch:
                    self._record_lot(
                        lot,
                        "processing completed",
                        operation,
                        tool=tool,
                        lot_ids=lot_ids,
                    )
                    self._leave_operation(lot, operation)
                self._record_tool(tool, "process completed", lot_ids, operation.ops_id)
                tool.run_count_since_pm += 1
                if (
                    tool.config.run_count_flag
                    and tool.run_count_since_pm >= tool.config.pm_run_count
                ):
                    yield self.env.process(self._perform_pm(tool, "run count"))

    def _time_based_pm(self, tool: Tool) -> Iterator[simpy.Event]:
        while True:
            remaining = tool.config.pm_mins_count - (
                self.env.now - tool.last_pm_completion
            )
            yield self.env.timeout(max(0.0, remaining))
            with tool.resource.request(priority=0) as request:
                yield request
                time_limit_reached = (
                    self.env.now - tool.last_pm_completion
                    >= tool.config.pm_mins_count
                )
                if time_limit_reached:
                    yield self.env.process(self._perform_pm(tool, "time"))

    def _perform_pm(self, tool: Tool, trigger: str) -> Iterator[simpy.Event]:
        self._record_tool(tool, "PM started", (), details=f"trigger: {trigger}")
        yield self.env.timeout(tool.config.pm_duration_mins)
        tool.run_count_since_pm = 0
        tool.last_pm_completion = self.env.now
        self._record_tool(tool, "PM completed", (), details=f"trigger: {trigger}")

    def _record_lot(
        self,
        lot: Lot,
        event: str,
        operation: OperationConfig,
        *,
        tool: Tool | None = None,
        lot_ids: tuple[str, ...] = (),
        status: str | None = None,
        details: str = "",
    ) -> None:
        self.events.record(
            self.env.now,
            "lot",
            lot.lot_id,
            event,
            operation_id=operation.ops_id,
            tool_id=tool.config.tool_id if tool else None,
            lot_ids=lot_ids,
            status=status or lot.status,
            details=details,
        )

    def _record_tool(
        self,
        tool: Tool,
        event: str,
        lot_ids: tuple[str, ...],
        operation_id: int | None = None,
        *,
        details: str = "",
    ) -> None:
        self.events.record(
            self.env.now,
            "tool",
            tool.config.tool_id,
            event,
            operation_id=operation_id,
            tool_id=tool.config.tool_id,
            lot_ids=lot_ids,
            details=details,
        )


def load_default_config(project_root: Path) -> FabConfig:
    return FabConfig.from_directory(project_root / "data")
