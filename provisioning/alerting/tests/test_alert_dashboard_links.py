"""Every provisioned alert rule must link a dashboard that exists in this repo."""

import json
import os
from pathlib import Path
import subprocess


ALERTING = Path(__file__).resolve().parents[1]


def load_provisioning(filename):
    return json.loads(subprocess.check_output(
        [os.environ.get("YQ", "yq"), ".", str(ALERTING / filename)],
        text=True,
    ))


def dashboard_uids():
    return {
        json.loads(path.read_text())["uid"]
        for path in (ALERTING.parents[1] / "dashboards").glob("*.json")
    }


def test_every_rule_names_a_non_empty_provisioned_dashboard_uid():
    """Grafana renders the link annotation only when the dashboard uid exists."""
    uids = dashboard_uids()
    unlinked = []
    for path in sorted(ALERTING.glob("*.yml")):
        for group in load_provisioning(path.name).get("groups", []):
            for rule in group.get("rules", []):
                link = (rule.get("annotations") or {}).get("__dashboardUid__") or ""
                if link not in uids:
                    unlinked.append(f"{path.name}: {rule['uid']} -> {link!r}")
    assert not unlinked, (
        "Every alert rule needs a __dashboardUid__ naming a repo dashboard:\n"
        + "\n".join(unlinked)
    )
