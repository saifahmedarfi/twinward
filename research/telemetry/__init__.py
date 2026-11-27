"""Observability plane (proposal §5, Figure 1).

Three independent exporters, each attached to the run as an EventSink hook so
the simulation cores stay unaware of them:

  prom.RunMetrics   Prometheus-style metrics (event/alert counters, reward and
                    reward components, run duration, log retention). Written to
                    a textfile, pushed to a Pushgateway, and served by every
                    estate service at /metrics.
  otel.Telemetry    OpenTelemetry traces (one trace per experiment, one span per
                    loop phase: configure / simulate / evaluate / persist) and
                    OTel log records (the normalized event stream, correlated to
                    the run's trace). Exported over OTLP/HTTP to the collector
                    and, always, to local JSONL so evidence exists offline.
  jsonlog.RunLog    Structured JSON-lines log per experiment under results/logs/.

Every exporter degrades to a no-op when its library is missing, so the
stdlib-only simulation path keeps working.
"""
