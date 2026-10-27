from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path


EVENT_FIELDS = (
    "time_minutes",
    "entity_type",
    "entity_id",
    "event",
    "operation_id",
    "tool_id",
    "lot_ids",
    "status",
    "details",
)


@dataclass(frozen=True)
class SimulationEvent:
    time_minutes: float
    entity_type: str
    entity_id: str
    event: str
    operation_id: int | None = None
    tool_id: str | None = None
    lot_ids: str = ""
    status: str = ""
    details: str = ""


class EventLog:
    def __init__(self) -> None:
        self.events: list[SimulationEvent] = []

    def record(
        self,
        time_minutes: float,
        entity_type: str,
        entity_id: str,
        event: str,
        *,
        operation_id: int | None = None,
        tool_id: str | None = None,
        lot_ids: tuple[str, ...] = (),
        status: str = "",
        details: str = "",
    ) -> None:
        self.events.append(
            SimulationEvent(
                time_minutes=round(time_minutes, 3),
                entity_type=entity_type,
                entity_id=entity_id,
                event=event,
                operation_id=operation_id,
                tool_id=tool_id,
                lot_ids=";".join(lot_ids),
                status=status,
                details=details,
            )
        )

    def write_csvs(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        self._write(output_dir / "events.csv", self.events)
        self._write(
            output_dir / "lot_history.csv",
            [event for event in self.events if event.entity_type == "lot"],
        )
        self._write(
            output_dir / "tool_history.csv",
            [event for event in self.events if event.entity_type == "tool"],
        )

    @staticmethod
    def _write(path: Path, events: list[SimulationEvent]) -> None:
        with path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=EVENT_FIELDS)
            writer.writeheader()
            writer.writerows(asdict(event) for event in events)
