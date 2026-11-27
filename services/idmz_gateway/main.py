"""FastAPI wrapper for the IDMZ boundary gateway.

Run locally:   uvicorn services.idmz_gateway.main:app --port 8001
All endpoints (healthz, state, control/mode, policy, tick, probe, reset, events,
metrics) come from services/common/app.py; the simulation logic is in core.py.
"""
from __future__ import annotations

from services.common.app import create_app
from services.idmz_gateway.core import COMPONENT, ZONE, IdmzGateway

app = create_app(IdmzGateway, COMPONENT, ZONE, section="idmz_gateway")
