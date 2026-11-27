"""FastAPI wrapper for the telemetry forwarder / data diode.

Run locally:   uvicorn services.telemetry_forwarder.main:app --port 8005
All endpoints (healthz, state, control/mode, policy, tick, probe, reset, events,
metrics) come from services/common/app.py; the simulation logic is in core.py.
"""
from __future__ import annotations

from services.common.app import create_app
from services.telemetry_forwarder.core import COMPONENT, ZONE, TelemetryForwarder

app = create_app(TelemetryForwarder, COMPONENT, ZONE, section="telemetry_forwarder")
