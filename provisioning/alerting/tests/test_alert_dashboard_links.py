"""Every provisioned alert rule must link a dashboard that exists in this repo."""

from conftest import ALERTING, dashboard_uids, load_provisioning


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
