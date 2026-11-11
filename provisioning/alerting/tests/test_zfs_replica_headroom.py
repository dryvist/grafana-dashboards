"""Validate the ZFS replica headroom alert provisioning with yq and pytest."""

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
    document = load_provisioning("zfs-replica-headroom.yml")
    assert len(document["groups"]) == 1
    group = document["groups"][0]
    assert group["name"] == "zfs-replica-headroom"
    rules = {rule["uid"]: rule for rule in group["rules"]}
    assert len(rules) == 2, "One warning and one critical projection rule"
    return rules


@pytest.mark.parametrize(
    "uid, horizon_hours, hold",
    [
        ("zfs-replica-headroom-warning", 24, "30m"),
        ("zfs-replica-headroom-critical", 6, "15m"),
    ],
)
def test_projection_predicts_zero_available_bytes(rules, uid, horizon_hours, hold):
    rule = rules[uid]
    query, threshold = rule["data"]
    assert query["model"]["expr"] == (
        "predict_linear(pve_zfs_dataset_available_bytes"
        f'{{dataset=~".*/replica"}}[6h], {horizon_hours * 3600})'
    )
    assert query["datasourceUid"] == "victoriametrics"
    assert query["relativeTimeRange"] == {"from": 21600, "to": 0}
    assert query["model"]["instant"] is True
    assert threshold["datasourceUid"] == "__expr__"
    assert threshold["model"]["type"] == "threshold"
    assert threshold["model"]["expression"] == "A"
    assert threshold["model"]["conditions"][0]["evaluator"] == {
        "type": "lt", "params": [0],
    }
    assert rule["condition"] == "B"
    assert rule["for"] == hold
    assert rule["execErrState"] == "Error"


def test_no_dataset_export_takes_the_ok_path(rules):
    """Nodes without the dataset textfile export must not page."""
    for rule in rules.values():
        assert rule["noDataState"] == "OK"


def test_selector_keeps_instance_and_dataset_labels(rules):
    """No aggregation may drop the per-node, per-dataset dimensions."""
    for rule in rules.values():
        expression = rule["data"][0]["model"]["expr"]
        assert "by (" not in expression
        assert "sum(" not in expression
        assert "predict_linear(" in expression


def test_severities_and_delivery_match_the_repo_pattern(rules):
    warning = rules["zfs-replica-headroom-warning"]
    critical = rules["zfs-replica-headroom-critical"]
    assert warning["labels"] == {"severity": "warning", "ntfy": "true"}
    assert critical["labels"] == {"severity": "critical", "ntfy": "true"}
    settings = critical["notification_settings"]
    assert settings["receiver"] == "critical-slack"
    assert settings["group_by"] == [
        "grafana_folder", "alertname", "instance", "dataset",
    ]
    assert settings["repeat_interval"] == "4h"
    contact_points = {
        point["name"]
        for point in load_provisioning("critical-slack-contact-point.yml")["contactPoints"]
    }
    assert settings["receiver"] in contact_points
    assert "notification_settings" not in warning


def test_annotations_name_the_entity_horizon_and_fallback(rules):
    horizons = {
        "zfs-replica-headroom-warning": "24 hours",
        "zfs-replica-headroom-critical": "6 hours",
    }
    for uid, horizon in horizons.items():
        annotations = rules[uid]["annotations"]
        assert "{{ $labels.instance }}" in annotations["summary"]
        assert "{{ $labels.dataset }}" in annotations["summary"]
        assert horizon in annotations["summary"]
        assert "no dataset quota series" in annotations["description"]
        assert "/d/storage-capacity" in annotations["description"]


def test_rules_link_the_replica_dataset_panel(rules):
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
    assert panel["title"] == "Replica dataset available bytes"
    target, = panel["targets"]
    assert target["instant"] is False
    assert target["range"] is True
    assert target["expr"] == (
        "pve_zfs_dataset_available_bytes"
        '{instance=~"$node(:.*)?",pool=~"$pool",dataset=~".*/replica"}'
    )


def test_group_matches_the_provisioning_pattern():
    document = load_provisioning("zfs-replica-headroom.yml")
    group = document["groups"][0]
    assert group["orgId"] == 1
    assert group["folder"] == "Alerting"
    assert group["interval"] == "5m"
