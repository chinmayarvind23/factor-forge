# Grafana and Prometheus

From the repository root:

```powershell
# Supply an absolute path to your saved study report.
$env:FACTORFORGE_STUDY_REPORT = 'C:/path/to/historical-study-v1.json'
docker compose -f tools/observability/compose.yaml up -d
```

Open http://127.0.0.1:3007 for the provisioned FactorForge dashboard. Prometheus runs
at http://127.0.0.1:9097. These local services display retained historical study gauges,
including the report hash. They do not present saved spans as live request traffic.
The exporter rereads the bounded report on each scrape and returns 503 on invalid input.
Prometheus's `up` series shows exporter availability separately from research results.
Grafana allows anonymous Viewer access on its loopback-published port; this configuration
is for a trusted local machine, not public hosting. No credentials or private prompts
are placed in metric labels.

Stop with `docker compose -f tools/observability/compose.yaml down`.

Provisioning follows [Grafana's data source and dashboard configuration](https://grafana.com/docs/grafana/latest/administration/provisioning/).
The exporter uses [Prometheus text exposition](https://prometheus.io/docs/instrumenting/exposition_formats/).
