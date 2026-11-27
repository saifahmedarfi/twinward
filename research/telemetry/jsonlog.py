"""Per-experiment structured JSON-lines log (results/logs/<experiment_id>.jsonl).

Each line is the estate event exactly as emitted, plus the OTel trace/span id of
the run (when tracing is on) so a log line can be joined to its trace. The raw
event schema (research/common/event_schema.json) is unchanged: the correlation
ids live only in the log file, never in the event stream the detector reads.
"""
from __future__ import annotations

import json
import os


class RunLog:
    def __init__(self, log_dir: str, experiment_id: str,
                 trace_id: str | None = None, span_id: str | None = None) -> None:
        os.makedirs(log_dir, exist_ok=True)
        self.path = os.path.join(log_dir, f"{experiment_id}.jsonl")
        self._fh = open(self.path, "w")  # noqa: SIM115 - closed in close()
        self.trace_id = trace_id
        self.span_id = span_id
        self.lines = 0

    def on_event(self, rec: dict) -> None:
        line = dict(rec)
        if self.trace_id:
            line["trace_id"] = self.trace_id
            line["span_id"] = self.span_id
        self._fh.write(json.dumps(line, separators=(",", ":")) + "\n")
        self.lines += 1

    def close(self) -> None:
        self._fh.close()
