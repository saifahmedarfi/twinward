#!/usr/bin/env python3
"""Realtime visualization backend for ProPS-Twin (stdlib-only).

Wraps the existing simulation core (research/scenario_controller) and the
log-only evaluator (research/evaluation) behind a tiny HTTP + Server-Sent-Events
API, so the browser visualization in viz/index.html can stream a scenario as it
runs in simulated time and watch the reward move when policy levers change.

Like scripts/demo_local.py and scripts/evaluate_local.py this uses nothing but
the Python standard library -- no FastAPI, no extra pip install.

    python3 scripts/viz_server.py                 # serve on http://localhost:8008
    python3 scripts/viz_server.py --port 9000
    python3 scripts/viz_server.py --open          # also open the page in a browser

Then open http://localhost:8008/  (the server serves viz/index.html itself), or
run VS Code Live Server on viz/ and point it at this backend -- the page talks to
it cross-origin (CORS is open) and falls back to viz/demo_data.json when the
backend is not running.

Endpoints
    GET /                         -> viz/index.html
    GET /demo_data.json           -> the pre-generated offline dataset
    GET /api/scenarios            -> [{id, description, seed, window, ...}]
    GET /api/stream?scenario=SC-01&speed=20[&access_profile=&alert_threshold=&recovery_timeout=]
                                  -> SSE: one `event:tick` per simulated second,
                                     then `event:reward`, then `event:done`
    GET /api/evaluate?scenario=SC-01[&...policy...]   -> reward document (no stream)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
VIZ_DIR = os.path.join(ROOT, "viz")

from research.evaluation.engine import _t_of, evaluate  # noqa: E402
from research.scenario_controller.catalog import SCENARIO_IDS, load  # noqa: E402
from research.scenario_controller.controller import COMPONENT_ZONE, run_scenario  # noqa: E402


# --------------------------------------------------------------------------- #
# simulation helpers
# --------------------------------------------------------------------------- #
def _estate_cfg(access_profile: str | None) -> dict:
    """Turn the access-profile lever into per-component estate config.

    `idmz_access_profile` is read by the idmz-gateway and eng-station cores and
    decides whether a malicious crossing is contained -- the reward's C lever.
    """
    if not access_profile:
        return {}
    return {
        "idmz_gateway": {"idmz_access_profile": access_profile},
        "eng_station": {"idmz_access_profile": access_profile},
    }


def _policy_from_query(q: dict) -> dict:
    def _one(key):
        v = q.get(key)
        return v[0] if v else None

    policy = {}
    ap = _one("access_profile")
    if ap:
        policy["access_profile"] = ap
    at = _one("alert_threshold")
    if at:
        policy["alert_threshold"] = float(at)
    rt = _one("recovery_timeout")
    if rt:
        policy["recovery_timeout"] = float(rt)
    return policy


def run_and_score(scenario_id: str, policy: dict) -> tuple[dict, dict, dict]:
    """Run one scenario under a policy and score it. Returns (scenario, run, doc)."""
    scenario = load(scenario_id)
    estate = _estate_cfg(policy.get("access_profile"))
    run = run_scenario(scenario, estate_cfg=estate, stream=False)
    doc = evaluate(
        run,
        scenario,
        alert_threshold=policy.get("alert_threshold"),
        recovery_budget=policy.get("recovery_timeout"),
    )
    return scenario, run, doc


def pack_event(e: dict) -> dict:
    """Trim a raw event to the fields the visualization needs."""
    return {
        "t": _t_of(e),
        "ts": e["timestamp"],
        "id": e["event_id"][:12],
        "component": e["component"],
        "event_type": e["event_type"],
        "severity": e["severity"],
        "state": e["simulated_state"],
        "zone": e["zone"],
        "details": e.get("details") or {},
    }


def scenario_summary(sid: str) -> dict:
    sc = load(sid)
    return {
        "id": sid,
        "description": sc.get("description", ""),
        "seed": sc["seed"],
        "window": sc["evaluation_window"],
        "ground_truth": [
            {"label": g["label"], "window": g["window"],
             "detection_type": g.get("detection_type", "presence"),
             "component": g.get("component"), "event_type": g.get("event_type")}
            for g in sc["ground_truth"]
        ],
        "has_probes": bool(sc.get("probes")),
    }


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "ProPSTwinViz/1.0"

    def log_message(self, fmt, *args):  # quieter console
        sys.stderr.write("  [viz] %s\n" % (fmt % args))

    # -- small response helpers -------------------------------------------- #
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as fh:
                body = fh.read()
        except OSError:
            self._json({"error": f"not found: {os.path.basename(path)}"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        route = u.path
        q = parse_qs(u.query)

        if route in ("/", "/index.html"):
            return self._file(os.path.join(VIZ_DIR, "index.html"), "text/html; charset=utf-8")
        if route == "/demo_data.json":
            return self._file(os.path.join(VIZ_DIR, "demo_data.json"), "application/json")
        if route == "/api/scenarios":
            return self._json([scenario_summary(s) for s in SCENARIO_IDS])
        if route == "/api/evaluate":
            return self._api_evaluate(q)
        if route == "/api/stream":
            return self._api_stream(q)
        return self._json({"error": f"no route {route}"}, 404)

    # -- API: evaluate ----------------------------------------------------- #
    def _api_evaluate(self, q):
        sid = (q.get("scenario") or ["SC-01"])[0]
        if sid not in SCENARIO_IDS:
            return self._json({"error": f"unknown scenario {sid}"}, 400)
        policy = _policy_from_query(q)
        _sc, _run, doc = run_and_score(sid, policy)
        return self._json(doc)

    # -- API: SSE stream --------------------------------------------------- #
    def _api_stream(self, q):
        sid = (q.get("scenario") or ["SC-01"])[0]
        if sid not in SCENARIO_IDS:
            return self._json({"error": f"unknown scenario {sid}"}, 400)
        try:
            speed = max(1.0, min(200.0, float((q.get("speed") or ["20"])[0])))
        except ValueError:
            speed = 20.0
        policy = _policy_from_query(q)

        scenario, run, doc = run_and_score(sid, policy)
        events = sorted(run["events"], key=lambda e: _t_of(e))
        end = int(scenario["evaluation_window"]["end"])

        # open the SSE stream
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._cors()
        self.end_headers()

        def send(ev, data):
            try:
                self.wfile.write(f"event: {ev}\n".encode())
                self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError):
                return False

        meta = scenario_summary(sid)
        meta["experiment_id"] = run["experiment_id"]
        meta["policy"] = doc["policy"]
        meta["n_events"] = len(events)
        if not send("meta", meta):
            return

        # group events by simulated tick and replay them paced by `speed`x realtime
        by_tick: dict[int, list] = {}
        for e in events:
            by_tick.setdefault(_t_of(e), []).append(e)

        dt = 1.0 / speed  # wall-seconds per simulated second
        for t in range(0, end + 1):
            batch = [pack_event(e) for e in by_tick.get(t, [])]
            if not send("tick", {"t": t, "end": end, "events": batch}):
                return
            time.sleep(dt)

        send("reward", doc)
        send("done", {"experiment_id": run["experiment_id"]})


def main():
    ap = argparse.ArgumentParser(description="ProPS-Twin visualization backend")
    ap.add_argument("--port", type=int, default=8008)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--open", action="store_true", help="open the page in a browser")
    args = ap.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"ProPS-Twin viz backend -> {url}")
    print(f"  scenarios : {', '.join(SCENARIO_IDS)}")
    print(f"  serving   : {VIZ_DIR}")
    print("  Ctrl-C to stop.")
    if args.open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye.")
        httpd.shutdown()


if __name__ == "__main__":
    main()
