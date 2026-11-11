"""Validate the ZFS pool capacity alert provisioning with yq and pytest."""

import json
import os
from pathlib import Path
import subprocess

import pytest


ALERTING = Path(__file__).resolve().parents[1]


def load_provisioning(filename):
    return json.loads(subprocess.check_output(
        [os.environ.get("YQ", "yq"), ".", str(ALERTING / filename)],
        text=True,
    ))


def load_dashboard(uid):
    return json.loads((ALERTING.parents[1] / "dashboards" / f"{uid}.json").read_text())


@pytest.fixture(scope="module")
def rules():
    document = load_provisioning("zfs-pool-capacity.yml")
    assert len(document["groups"]) == 1
    group = document["groups"][0]
    assert group["name"] == "zfs-pool-capacity"
    rules = {rule["uid"]: rule for rule in group["rules"]}
    assert len(rules) == 2, "One warning and one critical threshold rule"
    return rules


@pytest.mark.parametrize(
    "uid, threshold",
    [
        ("zfs-pool-capacity-warning", 80),
        ("zfs-pool-capacity-critical", 90),
    ],
)
def test_threshold_fires_above_the_pool_fill_percent(rules, uid, threshold):
    rule = rules[uid]
    query, evaluation = rule["data"]
    assert query["model"]["expr"] == "pve_zpool_cap_percent"
    assert query["datasourceUid"] == "victoriametrics"
    assert query["relativeTimeRange"] == {"from": 900, "to": 0}
    assert query["model"]["instant"] is True
    assert evaluation["datasourceUid"] == "__expr__"
    assert evaluation["model"]["type"] == "threshold"
    assert evaluation["model"]["expression"] == "A"
    assert evaluation["model"]["conditions"][0]["evaluator"] == {
        "type": "gt", "params": [threshold],
    }
    assert rule["condition"] == "B"
    assert rule["for"] == "15m"
    assert rule["noDataState"] == "OK"
    assert rule["execErrState"] == "Error"


def test_selector_is_per_pool_and_keeps_instance_and_pool_labels(rules):
    """No aggregation may merge pools or drop the per-node dimension."""
    for rule in rules.values():
        expression = rule["data"][0]["model"]["expr"]
        assert expression == "pve_zpool_cap_percent"
        assert "by (" not in expression
        assert "sum(" not in expression


def test_severities_and_delivery_match_the_repo_pattern(rules):
    warning = rules["zfs-pool-capacity-warning"]
    critical = rules["zfs-pool-capacity-critical"]
    assert warning["labels"] == {"severity": "warning", "ntfy": "true"}
    assert critical["labels"] == {"severity": "critical", "ntfy": "true"}
    settings = critical["notification_settings"]
    assert settings["receiver"] == "critical-slack"
    assert settings["group_by"] == [
        "grafana_folder", "alertname", "instance", "pool",
    ]
    assert settings["repeat_interval"] == "4h"
    contact_points = {
        point["name"]
        for point in load_provisioning("critical-slack-contact-point.yml")["contactPoints"]
    }
    assert settings["receiver"] in contact_points
    assert "notification_settings" not in warning


def test_summaries_print_the_queried_fill_percent_not_the_threshold(rules):
    """The summary shows refId A's value, never the threshold result."""
    for rule in rules.values():
        summary = rule["annotations"]["summary"]
        assert "{{ $labels.pool }}" in summary
        assert "{{ $labels.instance }}" in summary
        assert '$values.A.Value' in summary
        assert "$values.B" not in summary


def test_rules_link_the_pool_fill_time_series_panel(rules):
    panel_ids = set()
    for rule in rules.values():
        annotations = rule["annotations"]
        assert annotations["__dashboardUid__"] == "storage-capacity"
        panel_ids.add(annotations["__panelId__"])
    assert len(panel_ids) == 1, "Both rules link the same panel"
    panel_id = int(panel_ids.pop())
    panel = next(
        panel
        for panel in load_dashboard("storage-capacity")["panels"]
        if panel["id"] == panel_id
    )
    assert panel["type"] == "timeseries"
    assert panel["title"] == "Pool fill % over time"
    target, = panel["targets"]
    assert target["expr"] == (
        "pve_zpool_cap_percent{instance=~\"$node(:.*)?\",pool=~\"$pool\"}"
    )
    steps = panel["fieldConfig"]["defaults"]["thresholds"]["steps"]
    assert [step["value"] for step in steps[1:]] == [70, 80, 90]


def test_group_matches_the_provisioning_pattern():
    document = load_provisioning("zfs-pool-capacity.yml")
    group = document["groups"][0]
    assert group["orgId"] == 1
    assert group["folder"] == "Alerting"
    assert group["interval"] == "5m"
