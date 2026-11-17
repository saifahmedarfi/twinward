"""FastAPI wrapper for the IDMZ gateway.

Run locally:   uvicorn services.idmz_gateway.main:app --port 8001
The HTTP surface is what the Scenario Controller and Policy Engine call in the
Kubernetes path. The simulation logic itself lives in core.py and is unit-tested
without a server.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from pydantic import BaseModel

from research.common.props_log import EventSink
from services.idmz_gateway.core import COMPONENT, IdmzGateway

app = FastAPI(title="idmz-gateway")
_gw = IdmzGateway(seed=int(os.environ.get("GLOBAL_SEED", "1001")))
_sink = EventSink(
    experiment_id=os.environ.get("EXPERIMENT_ID", "exp-local"),
    scenario_id=os.environ.get("SCENARIO_ID", "SC-01"),
    policy_version=os.environ.get("POLICY_VERSION", "baseline-v1"),
)


class Mode(BaseModel):
    mode: str


class Request(BaseModel):
    protocol: str = "P1"
    role: str = "operator"
    channel: str = "local"


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/state")
def state():
    return _gw.state()


@app.post("/control/mode")
def control_mode(m: Mode):
    _gw.set_mode(m.mode)
    return {"component": COMPONENT, "mode": _gw.mode}


@app.post("/request")
def handle_request(r: Request):
    result = _gw.handle_request(r.model_dump(), _sink)
    return {"result": result}


@app.post("/tick")
def tick():
    _gw.tick(0, _sink)
    return {"ok": True}
