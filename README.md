# grafana-dashboards

Grafana-native dashboard JSON (plus an example file-provisioning provider) for
the homelab Grafana stack.

This repository holds **content**. Deployment stays in
[`dryvist/ansible-proxmox-apps`](https://github.com/dryvist/ansible-proxmox-apps)
(`roles/grafana_stack`), which fetches these files at a pinned git SHA.

Grafana's unit here is a **dashboard** (exported JSON with a stable `uid`), not
an App plugin and not a pack.

## Dashboards

| File | `uid` (must equal the filename stem) |
| --- | --- |
| `dashboards/claude-code-metrics.json` | `claude-code-metrics` |
| `dashboards/claude-cache-economics.json` | `claude-cache-economics` |
| `dashboards/claude-context-bloat.json` | `claude-context-bloat` |
| `dashboards/claude-subagents-tools.json` | `claude-subagents-tools` |
| `dashboards/claude-subscription-burn.json` | `claude-subscription-burn` |

Community dashboards (Node Exporter, Blackbox, Traefik) are still fetched from
grafana.com by ID and revision inside the Ansible role. They do not live here.

## Validate

From the Nix dev shell (`direnv` / `nix develop`):

```bash
jq empty dashboards/*.json
for f in dashboards/*.json; do
  stem="${f##*/}"; stem="${stem%.json}"
  uid="$(jq -r .uid "$f")"
  test "$uid" = "$stem"
done
```
