"""Experiment ledger (proposal §5.1 and §6.1).

Every experiment records: a unique ID, timestamps, the scenario seed, the initial
configuration snapshot (scenario + estate + reward weights), the policy
parameters, the generated event identifiers, metrics, reward and final status.
Events, ground-truth rows and reset procedures are stored alongside so candidate
policies can be compared on matched runs and the evidence re-scored later.

Backends (same schema, same API):
  - PostgreSQL  when PROPS_DB_URL / `url` is postgresql://...  (psycopg 3)
  - SQLite      otherwise (default results/ledger.sqlite), stdlib only
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from typing import Any

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS experiments(
        experiment_id   TEXT PRIMARY KEY,
        scenario_id     TEXT NOT NULL,
        seed            INTEGER NOT NULL,
        run_counter     INTEGER NOT NULL,
        status          TEXT NOT NULL,
        created_at      TEXT NOT NULL,
        finished_at     TEXT,
        duration_s      DOUBLE PRECISION,
        policy_version  TEXT,
        policy_json     TEXT,
        config_json     TEXT,
        reward          DOUBLE PRECISION,
        components_json TEXT,
        metrics_json    TEXT,
        counts_json     TEXT,
        n_events        INTEGER,
        n_persisted     INTEGER,
        event_ids_sha256 TEXT,
        trace_id        TEXT,
        code_version    TEXT,
        error           TEXT)""",
    """CREATE TABLE IF NOT EXISTS events(
        experiment_id   TEXT NOT NULL,
        event_id        TEXT NOT NULL,
        timestamp       TEXT NOT NULL,
        component       TEXT NOT NULL,
        event_type      TEXT NOT NULL,
        severity        TEXT NOT NULL,
        simulated_state TEXT NOT NULL,
        zone            TEXT NOT NULL,
        policy_version  TEXT,
        details_json    TEXT,
        PRIMARY KEY (experiment_id, event_id))""",
    """CREATE TABLE IF NOT EXISTS ground_truth(
        experiment_id   TEXT NOT NULL,
        scenario_id     TEXT NOT NULL,
        label           TEXT NOT NULL,
        t_start         INTEGER NOT NULL,
        t_end           INTEGER NOT NULL,
        expected_detection INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS resets(
        scenario_id     TEXT NOT NULL,
        from_experiment TEXT,
        to_experiment   TEXT,
        steps_json      TEXT,
        all_normal      INTEGER,
        at              TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_exp_scenario ON experiments(scenario_id, seed)",
    "CREATE INDEX IF NOT EXISTS idx_events_type ON events(experiment_id, event_type)",
]


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")


def _j(v: Any) -> str:
    return json.dumps(v, sort_keys=True, default=str)


class Ledger:
    con: Any  # sqlite3.Connection or psycopg.Connection (DB-API compatible)

    def __init__(self, url: str | None = None) -> None:
        url = url or os.environ.get("PROPS_DB_URL") or ""
        if url.startswith(("postgresql://", "postgres://")):
            import psycopg  # type: ignore
            self.backend = "postgresql"
            self.url = url
            self.con = psycopg.connect(url, autocommit=False)
            self.ph = "%s"
        else:
            path = url.removeprefix("sqlite:///") if url else os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "results", "ledger.sqlite")
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self.backend = "sqlite"
            self.url = f"sqlite:///{path}"
            self.con = sqlite3.connect(path)
            self.ph = "?"
        cur = self.con.cursor()
        for stmt in SCHEMA:
            cur.execute(stmt)
        self.con.commit()

    # --- helpers ----------------------------------------------------------
    def _q(self, sql: str) -> str:
        return sql.replace("?", self.ph)

    def _exec(self, sql: str, params: tuple = ()) -> Any:
        cur = self.con.cursor()
        cur.execute(self._q(sql), params)
        return cur

    def close(self) -> None:
        self.con.close()

    # --- experiment lifecycle --------------------------------------------
    def next_counter(self, scenario_id: str, seed: int) -> int:
        row = self._exec("SELECT MAX(run_counter) FROM experiments WHERE scenario_id=? AND seed=?",
                         (scenario_id, seed)).fetchone()
        return int(row[0] or 0) + 1

    def start(self, *, experiment_id: str, scenario_id: str, seed: int, run_counter: int,
              policy_version: str, policy: dict, config: dict, code_version: str | None) -> None:
        self._exec(
            "INSERT INTO experiments(experiment_id, scenario_id, seed, run_counter, status, "
            "created_at, policy_version, policy_json, config_json, code_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (experiment_id, scenario_id, seed, run_counter, "running", _now(), policy_version,
             _j(policy), _j(config), code_version))
        self.con.commit()

    def persist_evidence(self, experiment_id: str, events: list[dict],
                         ground_truth: list[dict]) -> int:
        """Store events + ground truth; returns the number of events now retained."""
        cur = self.con.cursor()
        cur.executemany(self._q(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)"),
            [(e["experiment_id"], e["event_id"], e["timestamp"], e["component"],
              e["event_type"], e["severity"], e["simulated_state"], e["zone"],
              e["policy_version"], _j(e.get("details") or {})) for e in events])
        cur.executemany(self._q("INSERT INTO ground_truth VALUES (?,?,?,?,?,?)"),
                        [(g["experiment_id"], g["scenario_id"], g["label"], g["t_start"],
                          g["t_end"], int(g["expected_detection"])) for g in ground_truth])
        self.con.commit()
        return self.count_events(experiment_id)

    def count_events(self, experiment_id: str) -> int:
        return int(self._exec("SELECT COUNT(*) FROM events WHERE experiment_id=?",
                              (experiment_id,)).fetchone()[0])

    def finish(self, experiment_id: str, *, status: str, duration_s: float,
               reward: float | None = None, components: dict | None = None,
               metrics: dict | None = None, counts: dict | None = None,
               n_events: int = 0, n_persisted: int = 0, event_ids_sha256: str | None = None,
               trace_id: str | None = None, error: str | None = None) -> None:
        self._exec(
            "UPDATE experiments SET status=?, finished_at=?, duration_s=?, reward=?, "
            "components_json=?, metrics_json=?, counts_json=?, n_events=?, n_persisted=?, "
            "event_ids_sha256=?, trace_id=?, error=? WHERE experiment_id=?",
            (status, _now(), duration_s, reward, _j(components), _j(metrics), _j(counts),
             n_events, n_persisted, event_ids_sha256, trace_id, error, experiment_id))
        self.con.commit()

    def record_reset(self, report: dict, from_experiment: str | None) -> None:
        self._exec("INSERT INTO resets VALUES (?,?,?,?,?,?)",
                   (report["scenario_id"], from_experiment, report["experiment_id"],
                    _j(report["steps"]), int(report["all_normal"]), _now()))
        self.con.commit()

    # --- queries ----------------------------------------------------------
    def experiments(self, limit: int = 50) -> list[dict]:
        cur = self._exec(
            "SELECT experiment_id, scenario_id, seed, status, policy_version, reward, "
            "n_events, n_persisted, duration_s, trace_id, created_at FROM experiments "
            "ORDER BY created_at DESC LIMIT ?", (limit,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def get(self, experiment_id: str) -> dict | None:
        cur = self._exec("SELECT * FROM experiments WHERE experiment_id=?", (experiment_id,))
        row = cur.fetchone()
        if row is None:
            return None
        rec = dict(zip([d[0] for d in cur.description], row, strict=True))
        for k in list(rec):
            if k.endswith("_json") and rec[k] is not None:
                rec[k] = json.loads(rec[k])
        return rec

    def events_for(self, experiment_id: str) -> list[dict]:
        cur = self._exec("SELECT * FROM events WHERE experiment_id=? ORDER BY timestamp, component",
                         (experiment_id,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def stats(self) -> dict:
        def one(sql: str) -> int:
            return int(self._exec(sql).fetchone()[0])
        return {"backend": self.backend, "url": self.url,
                "experiments": one("SELECT COUNT(*) FROM experiments"),
                "events": one("SELECT COUNT(*) FROM events"),
                "ground_truth": one("SELECT COUNT(*) FROM ground_truth"),
                "resets": one("SELECT COUNT(*) FROM resets")}


def open_ledger(url: str | None = None) -> Ledger:
    return Ledger(url)
