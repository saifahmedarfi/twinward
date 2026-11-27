"""OpenTelemetry instrumentation for the experiment loop.

One trace per experiment run:

    experiment.run                 (attrs: experiment_id, scenario, seed, policy)
      ├─ experiment.configure
      ├─ experiment.simulate       span events: scenario.action (sim t, target, mode)
      ├─ experiment.evaluate       span events: evaluation.result
      └─ experiment.persist

and one OTel log record per estate event, emitted inside the simulate span so
each record carries the run's trace_id/span_id (that is the "correlation" step
of the observability plane). Export targets:

  - OTLP/HTTP to the collector when OTEL_EXPORTER_OTLP_ENDPOINT is set
    (e.g. http://localhost:4318), and
  - always, local JSONL files (spans + logs) so evidence survives without a
    collector.

Without the OpenTelemetry SDK every method is a cheap no-op.
"""
from __future__ import annotations

import contextlib
import json
import os
import threading
from collections.abc import Iterator, Sequence
from typing import Any

try:
    from opentelemetry._logs import SeverityNumber
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import (
        BatchLogRecordProcessor,
        LogRecordExporter,
        LogRecordExportResult,
        SimpleLogRecordProcessor,
    )
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        SimpleSpanProcessor,
        SpanExporter,
        SpanExportResult,
    )
    from opentelemetry.trace import Status, StatusCode
    AVAILABLE = True
except ImportError:  # stdlib-only path
    AVAILABLE = False

_SEVERITY = {"low": 9, "medium": 13, "high": 17, "critical": 21}  # INFO/WARN/ERROR/FATAL


def _hex_trace(tid: int) -> str:
    return f"{tid:032x}"


def _hex_span(sid: int) -> str:
    return f"{sid:016x}"


if AVAILABLE:
    class JsonlSpanExporter(SpanExporter):
        """Write finished spans as JSON lines (offline evidence)."""

        def __init__(self, path: str) -> None:
            self.path = path
            self._lock = threading.Lock()
            os.makedirs(os.path.dirname(path), exist_ok=True)

        def export(self, spans: Sequence) -> SpanExportResult:
            with self._lock, open(self.path, "a") as fh:
                fh.writelines(json.dumps({
                        "trace_id": _hex_trace(s.context.trace_id),
                        "span_id": _hex_span(s.context.span_id),
                        "parent_span_id": _hex_span(s.parent.span_id) if s.parent else None,
                        "name": s.name,
                        "start_ns": s.start_time, "end_ns": s.end_time,
                        "duration_ms": round((s.end_time - s.start_time) / 1e6, 3),
                        "status": s.status.status_code.name,
                        "attributes": dict(s.attributes or {}),
                        "events": [{"name": e.name, "attributes": dict(e.attributes or {})}
                                   for e in s.events],
                    }, default=str) + "\n" for s in spans)
            return SpanExportResult.SUCCESS

        def shutdown(self) -> None:
            return None

    class JsonlLogExporter(LogRecordExporter):
        """Write OTel log records as JSON lines (offline evidence)."""

        def __init__(self, path: str) -> None:
            self.path = path
            self._lock = threading.Lock()
            os.makedirs(os.path.dirname(path), exist_ok=True)

        def export(self, batch: Sequence) -> LogRecordExportResult:
            with self._lock, open(self.path, "a") as fh:
                for item in batch:
                    lr = item.log_record
                    fh.write(json.dumps({
                        "trace_id": _hex_trace(lr.trace_id) if lr.trace_id else None,
                        "span_id": _hex_span(lr.span_id) if lr.span_id else None,
                        "severity": lr.severity_text,
                        "event_name": lr.event_name,
                        "body": lr.body,
                        "attributes": dict(lr.attributes or {}),
                    }, default=str) + "\n")
            return LogRecordExportResult.SUCCESS

        def force_flush(self, timeout_millis: int = 30_000) -> bool:
            return True

        def shutdown(self) -> None:
            return None


class Telemetry:
    def __init__(self, service_name: str = "props-twin-runner", *,
                 endpoint: str | None = None, evidence_dir: str | None = None,
                 export_logs: bool = True) -> None:
        self.enabled = AVAILABLE
        self.endpoint = endpoint if endpoint is not None else os.environ.get(
            "OTEL_EXPORTER_OTLP_ENDPOINT")
        self.evidence_dir = evidence_dir
        self.export_logs = export_logs
        self._current_run: Any = None
        self._simulate_span: Any = None
        if not self.enabled:
            return
        resource = Resource.create({
            "service.name": service_name,
            "service.namespace": "props-twin",
            "deployment.environment": "isolated-simulation",
        })
        self.tracer_provider = TracerProvider(resource=resource)
        self.logger_provider = LoggerProvider(resource=resource)
        if evidence_dir:
            self.tracer_provider.add_span_processor(
                SimpleSpanProcessor(JsonlSpanExporter(os.path.join(evidence_dir, "spans.jsonl"))))
            if export_logs:
                self.logger_provider.add_log_record_processor(SimpleLogRecordProcessor(
                    JsonlLogExporter(os.path.join(evidence_dir, "logs.jsonl"))))
        if self.endpoint:
            from opentelemetry.exporter.otlp.proto.http._log_exporter import (
                OTLPLogExporter,
            )
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            base = self.endpoint.rstrip("/")
            self.tracer_provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{base}/v1/traces", timeout=5)))
            if export_logs:
                self.logger_provider.add_log_record_processor(BatchLogRecordProcessor(
                    OTLPLogExporter(endpoint=f"{base}/v1/logs", timeout=5)))
        self.tracer = self.tracer_provider.get_tracer("props_twin.experiment")
        self.logger = self.logger_provider.get_logger("props_twin.events")

    # --- spans ------------------------------------------------------------
    @contextlib.contextmanager
    def run_span(self, attrs: dict[str, Any]) -> Iterator[dict]:
        """Root span of one experiment. Yields {trace_id, span_id} (hex)."""
        ids: dict[str, str | None] = {"trace_id": None, "span_id": None}
        if not self.enabled:
            yield ids
            return
        with self.tracer.start_as_current_span("experiment.run",
                                               attributes=_clean(attrs)) as span:
            ctx = span.get_span_context()
            ids["trace_id"] = _hex_trace(ctx.trace_id)
            ids["span_id"] = _hex_span(ctx.span_id)
            self._current_run = span
            try:
                yield ids
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise
            finally:
                self._current_run = None

    @contextlib.contextmanager
    def phase(self, name: str, attrs: dict[str, Any] | None = None) -> Iterator[Any]:
        if not self.enabled:
            yield None
            return
        with self.tracer.start_as_current_span(f"experiment.{name}",
                                               attributes=_clean(attrs or {})) as span:
            if name == "simulate":
                self._simulate_span = span
            try:
                yield span
            finally:
                if name == "simulate":
                    self._simulate_span = None

    def set_run_attrs(self, attrs: dict[str, Any]) -> None:
        if self.enabled and self._current_run is not None:
            self._current_run.set_attributes(_clean(attrs))

    # --- hooks ------------------------------------------------------------
    def on_action(self, t: int, target: str, value: str) -> None:
        """Controller callback: a scenario mode change at simulated tick t."""
        if self.enabled and self._simulate_span is not None:
            self._simulate_span.add_event("scenario.action", {
                "sim.t": t, "target": target, "mode": value,
                "kind": "restore" if value == "normal" else "inject"})

    def on_event(self, rec: dict) -> None:
        """EventSink hook: one OTel log record per estate event."""
        if not (self.enabled and self.export_logs):
            return
        self.logger.emit(
            severity_number=SeverityNumber(_SEVERITY[rec["severity"]]),
            severity_text=rec["severity"].upper(),
            body=rec["event_type"],
            event_name=f"props.{rec['event_type']}",
            attributes={
                "event_id": rec["event_id"], "experiment_id": rec["experiment_id"],
                "scenario_id": rec["scenario_id"], "component": rec["component"],
                "zone": rec["zone"], "simulated_state": rec["simulated_state"],
                "policy_version": rec["policy_version"], "sim.timestamp": rec["timestamp"],
                "details": json.dumps(rec.get("details") or {}, sort_keys=True),
            },
        )

    def current_ids(self) -> dict[str, str | None]:
        if not self.enabled:
            return {"trace_id": None, "span_id": None}
        from opentelemetry import trace
        ctx = trace.get_current_span().get_span_context()
        if not ctx.is_valid:
            return {"trace_id": None, "span_id": None}
        return {"trace_id": _hex_trace(ctx.trace_id), "span_id": _hex_span(ctx.span_id)}

    def shutdown(self) -> None:
        if not self.enabled:
            return
        self.tracer_provider.force_flush(10_000)
        self.logger_provider.force_flush(10_000)
        self.tracer_provider.shutdown()
        self.logger_provider.shutdown()


def _clean(attrs: dict[str, Any]) -> dict[str, Any]:
    """OTel attributes must be primitives; serialize anything else."""
    out = {}
    for k, v in attrs.items():
        if v is None:
            continue
        out[k] = v if isinstance(v, (str, bool, int, float)) else json.dumps(v, sort_keys=True,
                                                                              default=str)
    return out
