from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
import csv
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Fab simulation report</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, sans-serif; color: #172033; background: #f3f6fb; }
    body { max-width: 1400px; margin: 0 auto; padding: 24px; }
    h1 { margin-bottom: 4px; }
    .muted { color: #64748b; }
    .panel { background: white; border: 1px solid #dce3ed; border-radius: 12px; padding: 20px; margin: 18px 0; }
    .time-row { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
    #time-label { font-size: 1.35rem; font-weight: 700; font-variant-numeric: tabular-nums; }
    input[type=range] { width: 100%; margin: 18px 0 8px; accent-color: #2563eb; }
    .range-labels { display: flex; justify-content: space-between; color: #64748b; font-size: .85rem; }
    .playback-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
    button, .speed-control select { padding: 7px 12px; border: 1px solid #cbd5e1; border-radius: 7px; background: white; color: inherit; font: inherit; }
    button { cursor: pointer; }
    button:disabled { cursor: not-allowed; opacity: .5; }
    .speed-control { display: flex; align-items: center; gap: 8px; margin-left: auto; }
    .table-wrap { overflow-x: auto; }
    .table-wrap table { width: 100%; min-width: 1300px; border-collapse: collapse; }
    th, td { padding: 11px 12px; border-bottom: 1px solid #e6ebf2; text-align: left; }
    th { color: #475569; font-size: .85rem; }
    td.number { font-variant-numeric: tabular-nums; }
    .tool-list { display: flex; flex-wrap: wrap; gap: 6px; }
    .tool-status { display: inline-block; padding: 4px 8px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: .82rem; white-space: nowrap; }
    .tool-idle { background: #fff; }
    .tool-run { background: #bbf7d0; border-color: #86efac; }
    .tool-pm { background: #fef08a; border-color: #fde047; }
    #chart { width: 100%; height: 320px; display: block; }
    .legend { display: flex; flex-wrap: wrap; gap: 16px; margin: 10px 0 0; color: #475569; font-size: .9rem; }
    .legend span::before { content: ""; display: inline-block; width: 12px; height: 3px; margin: 0 7px 3px 0; background: var(--color); }
    select { padding: 7px 10px; border: 1px solid #cbd5e1; border-radius: 7px; background: white; }
    @media (max-width: 600px) { body { padding: 12px; } .panel { padding: 14px; } th, td { padding: 8px 5px; font-size: .85rem; } }
  </style>
</head>
<body>
  <h1>Fab simulation report</h1>
  <div class="muted">Interactive summary generated from the simulation event CSV.</div>
  <section class="panel">
    <div class="time-row"><strong>Simulation time</strong><span id="time-label"></span></div>
    <input id="time-slider" type="range" min="0" max="0" value="0" step="1" aria-label="Simulation time">
    <div class="range-labels"><span>0 min</span><span id="end-label"></span></div>
    <div class="playback-controls" aria-label="Playback controls">
      <button id="start-button" type="button">Start</button>
      <button id="pause-button" type="button" disabled>Pause</button>
      <button id="stop-button" type="button" disabled>Stop</button>
      <label class="speed-control" for="speed-select">Speed
        <select id="speed-select" aria-label="Playback speed">
          <option value="1">1x - 1min</option>
          <option value="10">10x - 10mins</option>
          <option value="60">60x - 1hr</option>
          <option value="180">180x - 3hrs</option>
          <option value="720">720x - 12hrs</option>
          <option value="1440">1440x - 24hrs</option>
          <option value="4320">4320x - 3days</option>
          <option value="10080">10080x - 7days</option>
        </select>
      </label>
    </div>
  </section>
  <section class="panel">
    <h2>Operation status</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>ops_id</th><th>Description</th><th>WIP (wafer)</th><th>In process (wafer)</th><th>Hold (wafer)</th><th>Tool status</th><th>Current shift outs (wafer)</th><th>Last shift outs (wafer)</th><th>Last 7 days outs (wafer)</th></tr></thead>
        <tbody id="status-table"></tbody>
      </table>
    </div>
  </section>
  <section class="panel">
    <div class="time-row"><h2>WIP trend (wafer)</h2><label>Operation <select id="operation-select"></select></label></div>
    <canvas id="chart"></canvas>
    <div class="legend">
      <span style="--color:#2563eb">WIP (wafer)</span>
      <span style="--color:#16a34a">In process (wafer)</span>
      <span style="--color:#dc2626">Hold (wafer)</span>
    </div>
  </section>
  <script id="report-data" type="application/json">__REPORT_DATA__</script>
  <script>
    const data = JSON.parse(document.getElementById("report-data").textContent);
    const slider = document.getElementById("time-slider");
    const startButton = document.getElementById("start-button");
    const pauseButton = document.getElementById("pause-button");
    const stopButton = document.getElementById("stop-button");
    const speedSelect = document.getElementById("speed-select");
    const timeLabel = document.getElementById("time-label");
    const endLabel = document.getElementById("end-label");
    const table = document.getElementById("status-table");
    const selector = document.getElementById("operation-select");
    const canvas = document.getElementById("chart");
    const context = canvas.getContext("2d");
    const colors = {wip: "#2563eb", in_process: "#16a34a", hold: "#dc2626"};
    let isPlaying = false;
    let animationFrameId = null;
    let lastFrameTime = null;
    let playbackTime = 0;

    data.operations.forEach(operation => {
      const option = document.createElement("option");
      option.value = operation.ops_id;
      option.textContent = `${operation.ops_id} - ${operation.description}`;
      selector.appendChild(option);
    });
    slider.max = Math.max(0, data.snapshots.length - 1);
    endLabel.textContent = `${data.end_time.toLocaleString()} min`;

    function currentSnapshot() {
      return data.snapshots[Number(slider.value)];
    }

    function renderTable(snapshot) {
      table.replaceChildren();
      snapshot.rows.forEach(row => {
        const tr = document.createElement("tr");
        [row.ops_id, row.description, row.wip, row.in_process, row.hold].forEach((value, index) => {
          const td = document.createElement("td");
          td.textContent = value;
          if (index >= 2 && index <= 4) td.className = "number";
          tr.appendChild(td);
        });
        const toolsCell = document.createElement("td");
        const toolList = document.createElement("div");
        toolList.className = "tool-list";
        row.tools.forEach(tool => {
          const badge = document.createElement("span");
          badge.className = `tool-status tool-${tool.status.toLowerCase()}`;
          badge.textContent = `${tool.tool_id} (${tool.status})`;
          toolList.appendChild(badge);
        });
        toolsCell.appendChild(toolList);
        tr.appendChild(toolsCell);
        [
          row.current_shift_outs,
          row.last_shift_outs,
          row.last_7_days_outs
        ].forEach(value => {
          const td = document.createElement("td");
          td.className = "number";
          td.textContent = value;
          tr.appendChild(td);
        });
        table.appendChild(tr);
      });
    }

    function drawChart(operationId, selectedTime) {
      const bounds = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(bounds.width * ratio));
      canvas.height = Math.max(1, Math.floor(bounds.height * ratio));
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      const width = bounds.width, height = bounds.height;
      const pad = {left: 42, right: 12, top: 16, bottom: 30};
      const points = data.snapshots.map(snapshot => ({
        time: snapshot.time,
        ...(snapshot.rows.find(row => String(row.ops_id) === String(operationId)) || {})
      }));
      const maxValue = Math.max(1, ...points.flatMap(point => [point.wip || 0, point.in_process || 0, point.hold || 0]));
      const plotWidth = width - pad.left - pad.right;
      const plotHeight = height - pad.top - pad.bottom;
      context.clearRect(0, 0, width, height);
      context.font = "12px system-ui, sans-serif";
      context.textAlign = "right";
      context.textBaseline = "middle";
      context.strokeStyle = "#e2e8f0";
      context.fillStyle = "#64748b";
      for (let tick = 0; tick <= 4; tick++) {
        const value = maxValue * tick / 4;
        const y = pad.top + plotHeight * (1 - tick / 4);
        context.beginPath();
        context.moveTo(pad.left, y);
        context.lineTo(width - pad.right, y);
        context.stroke();
        context.fillText(String(Math.round(value)), pad.left - 8, y);
      }
      const end = Math.max(1, data.end_time);
      context.textAlign = "left";
      context.fillText("0", pad.left, height - 8);
      context.textAlign = "right";
      context.fillText(`${Math.round(end)} min`, width - pad.right, height - 8);
      for (const key of ["wip", "in_process", "hold"]) {
        context.beginPath();
        context.strokeStyle = colors[key];
        context.lineWidth = 2;
        points.forEach((point, index) => {
          const x = pad.left + (point.time / end) * plotWidth;
          const y = pad.top + (1 - (point[key] || 0) / maxValue) * plotHeight;
          if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
        });
        context.stroke();
      }
      const markerX = pad.left + (selectedTime / end) * plotWidth;
      context.beginPath();
      context.strokeStyle = "#0f172a";
      context.setLineDash([4, 4]);
      context.moveTo(markerX, pad.top);
      context.lineTo(markerX, pad.top + plotHeight);
      context.stroke();
      context.setLineDash([]);
    }

    function render() {
      const snapshot = currentSnapshot();
      if (!snapshot) return;
      timeLabel.textContent = `${snapshot.time.toLocaleString()} min`;
      renderTable(snapshot);
      drawChart(selector.value || data.operations[0]?.ops_id, snapshot.time);
    }

    function updatePlaybackControls() {
      startButton.disabled = isPlaying || data.snapshots.length === 0;
      pauseButton.disabled = !isPlaying;
      stopButton.disabled = !isPlaying && Number(slider.value) === 0;
    }

    function pausePlayback() {
      isPlaying = false;
      if (animationFrameId !== null) cancelAnimationFrame(animationFrameId);
      animationFrameId = null;
      lastFrameTime = null;
      updatePlaybackControls();
    }

    function findSnapshotIndex(time) {
      let low = 0;
      let high = data.snapshots.length - 1;
      while (low < high) {
        const middle = Math.ceil((low + high) / 2);
        if (data.snapshots[middle].time <= time) low = middle;
        else high = middle - 1;
      }
      return low;
    }

    function advancePlayback(timestamp) {
      if (!isPlaying) return;
      if (lastFrameTime !== null) {
        playbackTime += (timestamp - lastFrameTime) * Number(speedSelect.value) / 60000;
      }
      lastFrameTime = timestamp;

      const endTime = data.snapshots[data.snapshots.length - 1].time;
      const nextIndex = findSnapshotIndex(Math.min(playbackTime, endTime));
      if (Number(slider.value) !== nextIndex) {
        slider.value = String(nextIndex);
        render();
      }
      if (playbackTime >= endTime) {
        pausePlayback();
        return;
      }
      animationFrameId = requestAnimationFrame(advancePlayback);
    }

    startButton.addEventListener("click", () => {
      if (Number(slider.value) >= data.snapshots.length - 1) {
        slider.value = "0";
        playbackTime = data.snapshots[0]?.time || 0;
      }
      isPlaying = true;
      lastFrameTime = null;
      updatePlaybackControls();
      animationFrameId = requestAnimationFrame(advancePlayback);
    });
    pauseButton.addEventListener("click", pausePlayback);
    stopButton.addEventListener("click", () => {
      pausePlayback();
      slider.value = "0";
      playbackTime = data.snapshots[0]?.time || 0;
      render();
      updatePlaybackControls();
    });
    slider.addEventListener("input", () => {
      playbackTime = currentSnapshot()?.time || 0;
      lastFrameTime = null;
      render();
      updatePlaybackControls();
    });
    selector.addEventListener("change", render);
    window.addEventListener("resize", render);
    render();
    updatePlaybackControls();
  </script>
</body>
</html>
"""


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def load_simulation_end(parameters_path: Path, events: list[dict[str, str]]) -> float:
    if parameters_path.exists():
        parameters = {
            row["parameter"].strip(): row["value"].strip()
            for row in read_csv(parameters_path)
        }
        duration_hours = parameters.get("duration_hours")
        if duration_hours is not None:
            return float(duration_hours) * 60
    return max((float(row["time_minutes"]) for row in events), default=0.0)


def load_wafers_per_lot(parameters_path: Path) -> int:
    if not parameters_path.exists():
        raise FileNotFoundError(
            f"Simulation parameters file not found: {parameters_path}"
        )
    parameters = {
        row["parameter"].strip(): row["value"].strip()
        for row in read_csv(parameters_path)
    }
    try:
        wafers_per_lot = int(parameters["wafers_per_lot"])
    except (KeyError, ValueError) as error:
        raise ValueError(
            f"Invalid or missing wafers_per_lot in {parameters_path}"
        ) from error
    if wafers_per_lot <= 0:
        raise ValueError("wafers_per_lot must be greater than zero")
    return wafers_per_lot


def build_report_data(
    events: list[dict[str, str]],
    operations: list[dict[str, str]],
    tool_operations: list[dict[str, str]],
    end_time: float,
    step_minutes: float,
    wafers_per_lot: int,
) -> dict[str, Any]:
    shift_minutes = 12 * 60
    seven_days_minutes = 7 * 24 * 60
    if step_minutes <= 0:
        raise ValueError("Report interval must be greater than zero")
    if wafers_per_lot <= 0:
        raise ValueError("Wafers per lot must be greater than zero")

    tool_ids_by_operation: dict[int, list[str]] = {}
    tool_statuses = {}
    for mapping in tool_operations:
        operation_id = int(mapping["ops_id"])
        tool_id = mapping["tool_id"]
        tool_ids_by_operation.setdefault(operation_id, []).append(tool_id)
        tool_statuses[tool_id] = "Idle"

    operation_rows = []
    for row in operations:
        operation_id = int(row["ops_id"])
        tool_ids = sorted(set(tool_ids_by_operation.get(operation_id, [])))
        operation_rows.append({
            "ops_id": operation_id,
            "description": row["ops_desc"],
            "tool_ids": tool_ids,
        })
    ordered_events = sorted(events, key=lambda row: float(row["time_minutes"]))
    successful_out_times: dict[int, list[float]] = {}
    for event in ordered_events:
        if (
            event["entity_type"] == "lot"
            and event["event"] == "moved out of operation"
            and (event["status"] or "active") != "hold"
        ):
            operation_id = int(event["operation_id"])
            successful_out_times.setdefault(operation_id, []).append(
                float(event["time_minutes"])
            )
    sample_times = [0.0]
    sample_time = step_minutes
    while sample_time < end_time:
        sample_times.append(round(sample_time, 3))
        sample_time += step_minutes
    if end_time > 0:
        sample_times.append(round(end_time, 3))

    lot_states: dict[str, dict[str, Any]] = {}
    event_index = 0
    snapshots = []
    for target_time in sample_times:
        while (
            event_index < len(ordered_events)
            and float(ordered_events[event_index]["time_minutes"]) <= target_time
        ):
            event = ordered_events[event_index]
            event_index += 1
            if event["entity_type"] == "tool":
                tool_id = event["entity_id"]
                if event["event"] == "in process":
                    tool_statuses[tool_id] = "Run"
                elif event["event"] == "process completed":
                    tool_statuses[tool_id] = "Idle"
                elif event["event"] == "PM started":
                    tool_statuses[tool_id] = "PM"
                elif event["event"] == "PM completed":
                    tool_statuses[tool_id] = "Idle"
                continue
            if event["entity_type"] != "lot":
                continue
            lot_id = event["entity_id"]
            state = lot_states.setdefault(
                lot_id, {"ops_id": None, "status": "active", "in_process": False}
            )
            event_name = event["event"]
            if event_name == "moved into operation":
                state.update(
                    ops_id=int(event["operation_id"]),
                    status=event["status"] or "active",
                    in_process=False,
                )
            elif event_name == "processing started":
                state.update(
                    ops_id=int(event["operation_id"]),
                    status=event["status"] or "active",
                    in_process=True,
                )
            elif event_name == "processing completed":
                state["in_process"] = False
                if event["status"]:
                    state["status"] = event["status"]
            elif event_name == "moved out of operation":
                state["status"] = event["status"] or "active"
                if state["status"] == "hold":
                    state.update(ops_id=int(event["operation_id"]), in_process=False)
                else:
                    state.update(ops_id=None, in_process=False)

        counts = {
            operation["ops_id"]: {"wip": 0, "in_process": 0, "hold": 0}
            for operation in operation_rows
        }
        for state in lot_states.values():
            ops_id = state["ops_id"]
            if ops_id is None:
                continue
            operation_count = counts.setdefault(
                ops_id, {"wip": 0, "in_process": 0, "hold": 0}
            )
            operation_count["wip"] += wafers_per_lot
            operation_count["in_process"] += wafers_per_lot * int(state["in_process"])
            operation_count["hold"] += wafers_per_lot * int(state["status"] == "hold")

        shift_start = (target_time // shift_minutes) * shift_minutes
        last_shift_start = max(0.0, shift_start - shift_minutes)
        seven_days_start = max(0.0, target_time - seven_days_minutes)
        for operation_id, operation_count in counts.items():
            out_times = successful_out_times.get(operation_id, [])
            out_end = bisect_right(out_times, target_time)
            current_shift_start_index = bisect_left(
                out_times, shift_start, 0, out_end
            )
            last_shift_start_index = bisect_left(
                out_times, last_shift_start, 0, out_end
            )
            seven_days_start_index = bisect_left(
                out_times, seven_days_start, 0, out_end
            )
            last_shift_end_index = bisect_left(
                out_times, shift_start, last_shift_start_index, out_end
            )
            operation_count.update(
                current_shift_outs=(
                    out_end - current_shift_start_index
                ) * wafers_per_lot,
                last_shift_outs=(
                    last_shift_end_index - last_shift_start_index
                ) * wafers_per_lot,
                last_7_days_outs=(
                    out_end - seven_days_start_index
                ) * wafers_per_lot,
            )

        snapshots.append(
            {
                "time": target_time,
                "rows": [
                    {
                        **operation,
                        **counts[operation["ops_id"]],
                        "tools": [
                            {
                                "tool_id": tool_id,
                                "status": tool_statuses.get(tool_id, "Idle"),
                            }
                            for tool_id in operation["tool_ids"]
                        ],
                    }
                    for operation in operation_rows
                ],
            }
        )

    return {
        "end_time": round(end_time, 3),
        "operations": operation_rows,
        "snapshots": snapshots,
    }


def generate_report(
    events_path: Path,
    operations_path: Path,
    tool_operations_path: Path,
    parameters_path: Path,
    output_path: Path,
    step_minutes: float,
) -> None:
    events = read_csv(events_path)
    operations = read_csv(operations_path)
    tool_operations = read_csv(tool_operations_path)
    end_time = load_simulation_end(parameters_path, events)
    wafers_per_lot = load_wafers_per_lot(parameters_path)
    report_data = build_report_data(
        events,
        operations,
        tool_operations,
        end_time,
        step_minutes,
        wafers_per_lot,
    )
    serialized_data = json.dumps(report_data, ensure_ascii=False)
    serialized_data = (
        serialized_data.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        HTML_TEMPLATE.replace("__REPORT_DATA__", serialized_data),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a standalone interactive report from simulation CSVs"
    )
    parser.add_argument("--events", type=Path, default=PROJECT_ROOT / "output/events.csv")
    parser.add_argument("--operations", type=Path, default=PROJECT_ROOT / "data/poly_config_ops.csv")
    parser.add_argument(
        "--tool-operations",
        type=Path,
        default=PROJECT_ROOT / "data/poly_config_tool-ops.csv",
    )
    parser.add_argument(
        "--parameters",
        type=Path,
        default=PROJECT_ROOT / "data/simulation_parameters.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "output/analysis_report.html",
    )
    parser.add_argument(
        "--step-minutes",
        type=float,
        default=5.0,
        help="Interval between report samples (default: 5 simulation minutes)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generate_report(
        args.events,
        args.operations,
        args.tool_operations,
        args.parameters,
        args.output,
        args.step_minutes,
    )
    print(f"Generated interactive report: {args.output}")


if __name__ == "__main__":
    main()
