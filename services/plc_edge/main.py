"""FastAPI wrapper for the boundary-protection firewall."""
from __future__ import annotations

import os

from fastapi import FastAPI
from pydantic import BaseModel

from research.common.props_log import EventSink
from services.plc_edge.core import COMPONENT, PlcEdge

app = FastAPI(title="plc-edge")
_svc = PlcEdge(seed=int(os.environ.get("GLOBAL_SEED", "1001")))
_sink = EventSink(os.environ.get("EXPERIMENT_ID", "exp-local"),
                  os.environ.get("SCENARIO_ID", "SC-01"),
                  os.environ.get("POLICY_VERSION", "baseline-v1"))


class Mode(BaseModel):
    mode: str


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/state")
def state():
    return _svc.state()


@app.post("/control/mode")
def control_mode(m: Mode):
    _svc.set_mode(m.mode)
    return {"component": COMPONENT, "mode": _svc.mode}


@app.post("/tick")
def tick():
    _svc.tick(0, _sink)
    return {"ok": True}
