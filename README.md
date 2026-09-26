# grafana-dashboards

Grafana-native dashboard JSON (plus an example file-provisioning provider) for
the homelab Grafana stack.

This repository holds **content**. Deployment stays in
[`dryvist/ansible-proxmox-apps`](https://github.com/dryvist/ansible-proxmox-apps)
(`roles/grafana_stack`), which fetches these files at a pinned git SHA.

Grafana's unit here is a **dashboard** (exported JSON with a stable `uid`), not
an App plugin and not a pack.

## Installation

Clone this repository, or reference a pinned commit SHA of it from a
consumer's automation (`roles/grafana_stack` in `ansible-proxmox-apps` does
this today).

## Usage

Load a file from `dashboards/` into Grafana's file-based dashboard
provisioner, or import it through Grafana's UI/HTTP API. The `provisioning/`
directory holds an example provider config for the file-based path.

## Dashboards

| File | `uid` (must equal the filename stem) |
| --- | --- |
| `dashboards/claude-code-metrics.json` | `claude-code-metrics` |
| `dashboards/claude-cache-economics.json` | `claude-cache-economics` |
| `dashboards/claude-context-bloat.json` | `claude-context-bloat` |
| `dashboards/claude-subagents-tools.json` | `claude-subagents-tools` |
| `dashboards/claude-subscription-burn.json` | `claude-subscription-burn` |
| `dashboards/hindsight-api-service.json` | `hindsight-api-service` |
| `dashboards/hindsight-llm.json` | `hindsight-llm` |
| `dashboards/hindsight-operations.json` | `hindsight-operations` |

Community dashboards (Node Exporter, Blackbox, Traefik) are still fetched from
grafana.com by ID and revision inside the Ansible role. They do not live here.

The three `hindsight-*` dashboards are vendored unmodified from
`vectorize-io/hindsight`'s own repository (`monitoring/grafana/dashboards/`,
pinned tag `v0.10.1`) — that project does not publish a grafana.com ID, so
they live here instead of in the Ansible role's by-ID fetch list.

## Validate

`scripts/validate_dashboards.sh` checks every file's JSON validity and its
`uid`-equals-filename convention; CI (`Validate Dashboards`) runs it on every
pull request. Run it locally with:

```bash
scripts/validate_dashboards.sh
```

## License

Apache License, Version 2.0 (see `LICENSE`). The vendored `hindsight-*`
dashboards keep their original MIT license — see `NOTICE`.
