"""FastAPI wrapper for the field-network PLC edge.

Run locally:   uvicorn services.plc_edge.main:app --port 8003
All endpoints (healthz, state, control/mode, policy, tick, probe, reset, events,
metrics) come from services/common/app.py; the simulation logic is in core.py.
"""
from __future__ import annotations

from services.common.app import create_app
from services.plc_edge.core import COMPONENT, ZONE, PlcEdge

app = create_app(PlcEdge, COMPONENT, ZONE, section="plc_edge")
