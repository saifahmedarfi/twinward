"""FastAPI wrapper for the boundary-protection firewall.

Run locally:   uvicorn services.boundary_firewall.main:app --port 8002
All endpoints (healthz, state, control/mode, policy, tick, probe, reset, events,
metrics) come from services/common/app.py; the simulation logic is in core.py.
"""
from __future__ import annotations

from services.boundary_firewall.core import COMPONENT, ZONE, BoundaryFirewall
from services.common.app import create_app

app = create_app(BoundaryFirewall, COMPONENT, ZONE, section="boundary_firewall")
