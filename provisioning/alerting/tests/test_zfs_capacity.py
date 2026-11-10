"""Validate ZFS capacity alert provisioning with yq and pytest."""

import json
import os
from pathlib import Path
import subprocess

import pytest


ALERTING = Path(__file__).resolve().parents[1]

POOL_RATIO_EXPRESSION = (
    '1 - pve_zfs_dataset_available_bytes{dataset!~".*/.*"} / '
    '(pve_zfs_dataset_available_bytes{dataset!~".*/.*"} '
    '+ pve_zfs_dataset_used_bytes{dataset!~".*/.*"})'
)
QUOTA_HEADROOM_EXPRESSION = (
    'pve_zfs_dataset_available_bytes{dataset=~".*/.*"} '
    "< on (instance, pool) "
    'pve_zfs_dataset_available_bytes{dataset!~".*/.*"}'
)


def load_provisioning(filename):
    return json.loads(subprocess.check_output(
        [os.environ.get("YQ", "yq"), ".", str(ALERTING / filename)],
        text=True,
    ))


@pytest.fixture(scope="module")
def document():
    return load_provisioning("zfs-capacity.yml")


@pytest.fixture(scope="module")
def rules(document):
    provisioned = [
        rule
        for group in document["groups"]
        for rule in group["rules"]
    ]
    indexed = {rule["uid"]: rule for rule in provisioned}
    assert len(indexed) == len(provisioned), "Alert rule UIDs must be unique"
    return indexed


@pytest.mark.parametrize(
    "uid, threshold, severity",
    [
        ("zfs-pool-used-ratio-warning", [0.8], "warning"),
        ("zfs-pool-used-ratio-critical", [0.9], "critical"),
    ],
)
def test_pool_ratio_rule_thresholds_and_delivery(rules, uid, threshold, severity):
    rule = rules[uid]
    query, expression = rule["data"]
    assert query["model"]["expr"] == POOL_RATIO_EXPRESSION
    assert query["datasourceUid"] == "victoriametrics"
    assert query["relativeTimeRange"] == {"from": 0, "to": 0}
    assert query["model"]["instant"] is True
    assert expression["datasourceUid"] == "__expr__"
    assert expression["model"]["type"] == "threshold"
    assert expression["model"]["expression"] == "A"
    assert expression["model"]["conditions"][0]["evaluator"] == {
        "type": "gt", "params": threshold,
    }
    assert rule["condition"] == "B"
    assert rule["for"] == "15m"
    assert rule["noDataState"] == "OK"
    assert rule["execErrState"] == "Error"
    assert rule["labels"] == {"severity": severity, "ntfy": "true"}


@pytest.mark.parametrize(
    "uid", ["zfs-pool-used-ratio-warning", "zfs-pool-used-ratio-critical"]
)
def test_pool_ratio_summaries_print_the_query_value_as_a_percent(rules, uid):
    """The summary names the instance and dataset and reports refId A, not the threshold."""
    summary = rules[uid]["annotations"]["summary"]
    assert "$labels.instance" in summary
    assert "$labels.dataset" in summary
    assert "$values.A.Value" in summary
    assert "humanizePercentage" in summary
    assert "$values.B" not in summary


def test_quota_headroom_rule_threshold_and_delivery(rules):
    rule = rules["zfs-dataset-quota-headroom-low"]
    query, expression = rule["data"]
    assert query["model"]["expr"] == QUOTA_HEADROOM_EXPRESSION
    assert query["datasourceUid"] == "victoriametrics"
    assert query["relativeTimeRange"] == {"from": 0, "to": 0}
    assert query["model"]["instant"] is True
    assert expression["model"]["conditions"][0]["evaluator"] == {
        "type": "lt", "params": [53687091200],
    }
    assert rule["condition"] == "B"
    assert rule["for"] == "15m"
    assert rule["noDataState"] == "OK"
    assert rule["execErrState"] == "Error"
    assert rule["labels"] == {"severity": "warning", "ntfy": "true"}
    summary = rule["annotations"]["summary"]
    assert "$labels.instance" in summary
    assert "$labels.dataset" in summary
    assert "$values.A.Value" in summary
    assert "humanizeBytes" in summary


def test_critical_ratio_rule_delivers_to_the_critical_slack_contact_point(rules):
    rule = rules["zfs-pool-used-ratio-critical"]
    settings = rule["notification_settings"]
    contact_points = {
        point["name"]
        for point in load_provisioning(
            "critical-slack-contact-point.yml"
        )["contactPoints"]
    }
    assert settings["receiver"] in contact_points
    assert settings["group_by"] == [
        "grafana_folder", "alertname", "instance", "dataset",
    ]
    assert settings["repeat_interval"] == "4h"


@pytest.mark.parametrize(
    "uid", ["zfs-pool-used-ratio-warning", "zfs-dataset-quota-headroom-low"]
)
def test_warning_rules_stay_on_the_default_delivery_path(rules, uid):
    assert "notification_settings" not in rules[uid]


def test_provisioned_groups_share_the_alerting_folder_and_one_minute_interval(
    document,
):
    for group in document["groups"]:
        assert group["orgId"] == 1
        assert group["folder"] == "Alerting"
        assert group["interval"] == "1m"
