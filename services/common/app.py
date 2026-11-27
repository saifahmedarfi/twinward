"""Shared FastAPI wrapper for the five estate components (handbook Step 3.3).

`create_app(core_cls, component, zone)` returns an app exposing:

  GET  /healthz          liveness
  GET  /state            component state (mode, healthy) + tick counter
  POST /control/mode     set the simulated mode (scenario injection)
  POST /policy           apply allow-listed policy levers via core.apply_policy()
  POST /tick?n=1         advance the component n ticks (emits telemetry)
  GET  /probe            legitimate availability probe (if the core has one)
  POST /reset            restore mode + baseline policy + fresh seeded state
  GET  /events?limit=50  most recent emitted events (ring buffer)
  GET  /metrics          Prometheus exposition
  POST /request          (idmz-gateway only) broker an inter-zone request

Configuration comes from the environment: GLOBAL_SEED, ESTATE_CONFIG (path to
estate-config.yaml, mounted read-only), EXPERIMENT_ID / SCENARIO_ID /
POLICY_VERSION, TICK_INTERVAL_S (>0 starts a background ticker so the service
emits live telemetry), and OTEL_EXPORTER_OTLP_ENDPOINT (OTLP/HTTP collector).

Each event is printed as one JSON line on stdout (what the container runtime and
a log shipper collect), counted in Prometheus and exported as an OTel log record.
"""
from __future__ import annotations

import asyncio
import collections
import contextlib
import datetime as dt
import os
import sys
import time

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from research.common.props_log import EventSink

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )
    _PROM = True
except ImportError:
    _PROM = False


class Mode(BaseModel):
    mode: str


class Policy(BaseModel):
    alert_threshold: float | None = None
    idmz_access_profile: str | None = None
    boundary_rate_limit: int | None = None
    recovery_timeout: int | None = None
    protocol_whitelist: list[str] | None = None


class Request(BaseModel):
    protocol: str = "P1"
    role: str = "operator"
    channel: str = "local"


def _estate_section(section: str) -> dict:
    path = os.environ.get("ESTATE_CONFIG")
    if not path or not os.path.exists(path):
        return {}
    try:
        import yaml  # type: ignore
    except ImportError:
        return {}
    with open(path) as fh:
        return (yaml.safe_load(fh) or {}).get(section) or {}


def create_app(core_cls, component: str, zone: str, section: str) -> FastAPI:
    seed = int(os.environ.get("GLOBAL_SEED", "1001"))
    cfg = _estate_section(section)
    tick_interval = float(os.environ.get("TICK_INTERVAL_S", "0") or 0)
    stream = sys.stdout if os.environ.get("EVENT_STDOUT", "1") == "1" else False

    state = {"core": core_cls(seed, cfg), "t": 0}
    recent: collections.deque = collections.deque(maxlen=500)

    # --- Prometheus ---------------------------------------------------------
    registry = CollectorRegistry() if _PROM else None
    if _PROM:
        m_events = Counter("props_service_events_total", "Events emitted",
                           ["component", "event_type", "severity", "state"], registry=registry)
        m_ticks = Counter("props_service_ticks_total", "Telemetry ticks", ["component"],
                          registry=registry)
        m_mode = Gauge("props_service_mode_info", "Current simulated mode (1 = active)",
                       ["component", "mode"], registry=registry)
        m_healthy = Gauge("props_service_healthy", "1 if the component reports healthy",
                          ["component"], registry=registry)
        m_probe = Histogram("props_service_probe_latency_ms", "Availability probe latency",
                            ["component", "ok"], buckets=(2, 5, 10, 20, 50, 100),
                            registry=registry)
        m_policy = Counter("props_service_policy_applied_total", "Applied policy updates",
                           ["component"], registry=registry)

    def _refresh_gauges() -> None:
        if not _PROM:
            return
        st = state["core"].state()
        m_mode.clear()
        m_mode.labels(component, st["mode"]).set(1)
        m_healthy.labels(component).set(1 if st["healthy"] else 0)

    # --- OpenTelemetry -------------------------------------------------------
    from research.telemetry.otel import Telemetry
    otel = Telemetry(service_name=component, evidence_dir=None)

    def _on_event(rec: dict) -> None:
        recent.append(rec)
        if _PROM:
            m_events.labels(component, rec["event_type"], rec["severity"],
                            rec["simulated_state"]).inc()
        otel.on_event(rec)

    sink = EventSink(os.environ.get("EXPERIMENT_ID", "exp-live"),
                     os.environ.get("SCENARIO_ID", "live"),
                     os.environ.get("POLICY_VERSION", "baseline-v1"),
                     stream=stream, clock=lambda: dt.datetime.now(dt.UTC), hooks=[_on_event])

    def _tick() -> None:
        state["core"].tick(state["t"], sink)
        state["t"] += 1
        if _PROM:
            m_ticks.labels(component).inc()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = None
        _refresh_gauges()
        if tick_interval > 0:
            async def ticker() -> None:
                while True:
                    _tick()
                    _refresh_gauges()
                    await asyncio.sleep(tick_interval)
            task = asyncio.create_task(ticker())
        yield
        if task:
            task.cancel()
        otel.shutdown()

    app = FastAPI(title=component, lifespan=lifespan)

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "component": component}

    @app.get("/state")
    def get_state():
        return {**state["core"].state(), "t": state["t"], "zone": zone, "seed": seed}

    @app.post("/control/mode")
    def control_mode(m: Mode):
        with otel_span(otel, "control.mode", {"component": component, "mode": m.mode}):
            state["core"].set_mode(m.mode)
        _refresh_gauges()
        return {"component": component, "mode": state["core"].mode}

    @app.post("/policy")
    def apply_policy(p: Policy):
        levers = {k: v for k, v in p.model_dump().items() if v is not None}
        if not levers:
            raise HTTPException(422, "no policy levers given")
        with otel_span(otel, "policy.apply", {"component": component, "levers": str(levers)}):
            state["core"].apply_policy(levers)
        if _PROM:
            m_policy.labels(component).inc()
        return {"component": component, "applied": levers}

    @app.post("/tick")
    def tick(n: int = 1):
        if not 1 <= n <= 10_000:
            raise HTTPException(422, "n must be in [1, 10000]")
        for _ in range(n):
            _tick()
        _refresh_gauges()
        return {"ok": True, "t": state["t"]}

    @app.get("/probe")
    def probe():
        core = state["core"]
        if not hasattr(core, "probe"):
            raise HTTPException(404, f"{component} has no availability probe")
        t0 = time.perf_counter()
        res = core.probe(state["t"])
        if _PROM:
            m_probe.labels(component, str(bool(res["ok"])).lower()).observe(res["latency_ms"])
        return {**res, "handled_ms": round((time.perf_counter() - t0) * 1000, 3)}

    @app.post("/reset")
    def reset():
        with otel_span(otel, "service.reset", {"component": component}):
            state["core"] = core_cls(seed, cfg)
            state["t"] = 0
            sink.reset()
            recent.clear()
        _refresh_gauges()
        return {"component": component, "reset": True, **state["core"].state()}

    @app.get("/events")
    def events(limit: int = 50):
        return list(recent)[-max(1, min(limit, 500)):]

    @app.get("/metrics")
    def metrics():
        if not _PROM:
            raise HTTPException(501, "prometheus_client not installed")
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    if hasattr(state["core"], "handle_request"):
        @app.post("/request")
        def handle_request(r: Request):
            return {"result": state["core"].handle_request(r.model_dump(), sink)}

    return app


@contextlib.contextmanager
def otel_span(otel, name: str, attrs: dict):
    if not otel.enabled:
        yield
        return
    with otel.tracer.start_as_current_span(name, attributes=attrs):
        yield
