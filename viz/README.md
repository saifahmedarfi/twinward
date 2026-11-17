# ProPS-Twin live visualization

A Moonfly-themed browser view of the estate simulation — the event stream that
normally scrolls past in an Ubuntu terminal, plus a live estate map, a timeline
with the ground-truth windows marked, and the reward dashboard (`R` and its
D/C/A/Q/F/L components).

Two ways to run it. Both show **real** simulation output, not a mock-up.

## 1. With the backend (realtime, interactive)  ← recommended

Runs a fresh simulation per click and streams it over Server-Sent Events, so the
policy levers (access profile, alert threshold) actually move the reward live.
Stdlib-only — no pip install.

```bash
python3 scripts/viz_server.py --open      # serves + opens http://localhost:8008
# or
make viz                                  # same thing  (PORT=8008 by default)
make viz PORT=9000
```

The server serves `index.html` itself, so just open the printed URL.

## 2. With VS Code Live Server (static, offline replay)

Right-click `viz/index.html` → **Open with Live Server**. With no backend
reachable the page loads `demo_data.json` (baked from a real run) and replays it
with the same animation. The policy levers are disabled in this mode (they need
the backend to re-simulate).

> If you run **both** — Live Server on `viz/` *and* the backend — the page finds
> the backend automatically (tries same-origin, then `localhost:8008`) and
> upgrades itself to realtime. The status badge, top-right, says which mode.

## Rebuild the offline dataset

Regenerate `demo_data.json` after changing the simulation or scenarios:

```bash
python3 scripts/make_viz_data.py    # or: make viz-data
```

## Backend API (stdlib `http.server`)

| Route | Returns |
|---|---|
| `GET /` | this page |
| `GET /api/scenarios` | scenario list with ground-truth windows |
| `GET /api/stream?scenario=SC-01&speed=20[&access_profile=&alert_threshold=&recovery_timeout=]` | SSE: `meta` → `tick`×N → `reward` → `done` |
| `GET /api/evaluate?scenario=SC-01[&…policy…]` | the reward document (no stream) |

Policy levers: `access_profile` ∈ {standard, strict, lockdown} drives containment
`C`; `alert_threshold` ∈ 1..5 drives detection/false-positives; `recovery_timeout`
drives recovery `Q` on SC-07. Try SC-04 at `standard` (R≈0.60) vs `strict`
(R≈0.85) to see C move.
