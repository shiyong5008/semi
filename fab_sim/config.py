from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolConfig:
    tool_id: str
    tool_cat: str
    vendor: str
    chambers_per_tool: int
    run_count_flag: bool
    pm_run_count: int
    time_count_flag: bool
    pm_mins_count: int
    pm_duration_mins: int


@dataclass(frozen=True)
class ToolOperationConfig:
    tool_id: str
    ops_id: int
    batch_size_min: int
    batch_size_max: int
    proc_time_per_load_mins: int


@dataclass(frozen=True)
class OperationConfig:
    ops_id: int
    ops_desc: str
    max_q_time_mins: int


@dataclass(frozen=True)
class FabConfig:
    tools: tuple[ToolConfig, ...]
    tool_operations: tuple[ToolOperationConfig, ...]
    operations: tuple[OperationConfig, ...]

    @classmethod
    def from_directory(cls, data_dir: Path) -> FabConfig:
        tools = tuple(
            ToolConfig(
                tool_id=row["tool_id"],
                tool_cat=row["tool_cat"],
                vendor=row["vendor"],
                chambers_per_tool=int(row["chambers_per_tool"]),
                run_count_flag=_parse_flag(row["run_count_flag"]),
                pm_run_count=int(row["pm_run_count"]),
                time_count_flag=_parse_flag(row["time_count_flag"]),
                pm_mins_count=int(row["pm_mins_count"]),
                pm_duration_mins=int(row["pm_duration_mins"]),
            )
            for row in _read_csv(data_dir / "poly_config_tool.csv")
        )
        tool_operations = tuple(
            ToolOperationConfig(
                tool_id=row["tool_id"],
                ops_id=int(row["ops_id"]),
                batch_size_min=int(row["batch_size_min"]),
                batch_size_max=int(row["batch_size_max"]),
                proc_time_per_load_mins=int(row["proc_time_per_load_mins"]),
            )
            for row in _read_csv(data_dir / "poly_config_tool-ops.csv")
        )
        operations = tuple(
            OperationConfig(
                ops_id=int(row["ops_id"]),
                ops_desc=row["ops_desc"],
                max_q_time_mins=int(row["max_q_time_mins"]),
            )
            for row in _read_csv(data_dir / "poly_config_ops.csv")
        )
        config = cls(tools, tool_operations, operations)
        config.validate()
        return config

    def validate(self) -> None:
        tool_ids = {tool.tool_id for tool in self.tools}
        operation_ids = {operation.ops_id for operation in self.operations}
        for mapping in self.tool_operations:
            if mapping.tool_id not in tool_ids:
                raise ValueError(f"Unknown tool in tool-operation mapping: {mapping.tool_id}")
            if mapping.ops_id not in operation_ids:
                raise ValueError(f"Unknown operation in tool-operation mapping: {mapping.ops_id}")
            if mapping.batch_size_min <= 0 or mapping.batch_size_max < mapping.batch_size_min:
                raise ValueError(f"Invalid batch range for tool {mapping.tool_id}")
            if mapping.proc_time_per_load_mins <= 0:
                raise ValueError(f"Processing time must be positive for tool {mapping.tool_id}")
        for tool in self.tools:
            if tool.chambers_per_tool <= 0:
                raise ValueError(f"Chamber count must be positive for tool {tool.tool_id}")
            if tool.pm_duration_mins < 0:
                raise ValueError(f"PM duration cannot be negative for tool {tool.tool_id}")
            if tool.run_count_flag and tool.pm_run_count <= 0:
                raise ValueError(f"PM run-count limit must be positive for tool {tool.tool_id}")
            if tool.time_count_flag and tool.pm_mins_count <= 0:
                raise ValueError(f"PM time limit must be positive for tool {tool.tool_id}")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def _parse_flag(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"y", "n"}:
        raise ValueError(f"Expected 'y' or 'n' flag, got {value!r}")
    return normalized == "y"
