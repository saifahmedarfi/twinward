"""FastAPI wrapper for the engineering workstation.

Run locally:   uvicorn services.eng_station.main:app --port 8004
All endpoints (healthz, state, control/mode, policy, tick, probe, reset, events,
metrics) come from services/common/app.py; the simulation logic is in core.py.
"""
from __future__ import annotations

from services.common.app import create_app
from services.eng_station.core import COMPONENT, ZONE, EngStation

app = create_app(EngStation, COMPONENT, ZONE, section="eng_station")
