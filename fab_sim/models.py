from __future__ import annotations

from dataclasses import dataclass, field

import simpy

from fab_sim.config import ToolConfig, ToolOperationConfig


@dataclass
class Lot:
    lot_id: str
    wafer_count: int
    status: str = "active"
    operation_entry_times: dict[int, float] = field(default_factory=dict)


@dataclass
class Tool:
    config: ToolConfig
    operation_config: ToolOperationConfig
    resource: simpy.PriorityResource
    batch_queue: simpy.Store
    run_count_since_pm: int = 0
    last_pm_completion: float = 0.0
    estimated_available_at: float = 0.0
