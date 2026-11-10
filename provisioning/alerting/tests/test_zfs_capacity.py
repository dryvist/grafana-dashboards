"""Validate the ZFS capacity alert provisioning with yq and pytest."""

import json
import os
from pathlib import Path
import subprocess

import pytest


ALERTING = Path(__file__).resolve().parents[1]
HEADROOM_BYTES = 53687091200


def load_provisioning(filename):
    return json.loads(subprocess.check_output(
        [os.environ.get("YQ", "yq"), ".", str(ALERTING / filename)],
        text=True,
    ))


def flattened(expression):
    return " ".join(expression.split())


POOL_USED_EXPRESSION = (
    "1 - pve_zfs_dataset_available_bytes{dataset!~\".*/.*\"} / "
    "(pve_zfs_dataset_available_bytes{dataset!~\".*/.*\"} + "
    "pve_zfs_dataset_used_bytes{dataset!~\".*/.*\"})"
)
POOL_FREE_EXPRESSION = 'pve_zfs_dataset_available_bytes{dataset!~".*/.*"}'
QUOTA_HEADROOM_EXPRESSION = (
    'pve_zfs_dataset_available_bytes{dataset=~".*/.*"} '
    '< on (instance, pool) group_left '
    'pve_zfs_dataset_available_bytes{dataset!~".*/.*"}'
)


@pytest.fixture(scope="module")
def groups():
    document = load_provisioning("zfs-capacity.yml")
    assert document["apiVersion"] == 1
    assert len(document["groups"]) == 2
    return document["groups"]


@pytest.fixture(scope="module")
def rules(groups):
    provisioned = [rule for group in groups for rule in group["rules"]]
    indexed = {rule["uid"]: rule for rule in provisioned}
    assert len(indexed) == len(provisioned), "Alert rule UIDs must be unique"
    return indexed


@pytest.mark.parametrize(
    "uid, threshold, severity",
    [
        ("zfs-pool-used-warning", 0.80, "warning"),
        ("zfs-pool-used-critical", 0.90, "critical"),
    ],
)
def test_pool_used_rules_keep_ratio_query_threshold_and_pending_window(
    rules, uid, threshold, severity
):
    rule = rules[uid]
    query, free, threshold_stage = rule["data"]
    assert query["refId"] == "A"
    assert flattened(query["model"]["expr"]) == POOL_USED_EXPRESSION, (
        "The used ratio reads 1 - available / (available + used) per pool"
    )
    assert query["datasourceUid"] == "victoriametrics"
    assert query["relativeTimeRange"] == {"from": 600, "to": 0}
    assert query["model"]["instant"] is True
    assert free["refId"] == "C"
    assert flattened(free["model"]["expr"]) == POOL_FREE_EXPRESSION, (
        "The free-bytes series feeds the free amount in the annotations"
    )
    assert threshold_stage["refId"] == "B"
    assert threshold_stage["model"]["type"] == "threshold"
    assert threshold_stage["model"]["expression"] == "A"
    assert threshold_stage["model"]["conditions"][0]["evaluator"] == {
        "type": "gt", "params": [threshold],
    }
    assert rule["condition"] == "B"
    assert rule["for"] == "15m"
    assert rule["noDataState"] == "OK"
    assert rule["execErrState"] == "Error"
    assert rule["labels"] == {"severity": severity, "ntfy": "true"}


@pytest.mark.parametrize(
    "uid", ["zfs-pool-used-warning", "zfs-pool-used-critical"]
)
def test_pool_used_summaries_name_the_instance_dataset_and_free_amount(
    rules, uid
):
    annotations = rules[uid]["annotations"]
    assert "$labels.instance" in annotations["summary"]
    assert "$labels.dataset" in annotations["summary"]
    assert "$values.C.Value" in annotations["summary"]
    assert "$labels.instance" in annotations["description"]
    assert "$labels.dataset" in annotations["description"]


@pytest.mark.parametrize(
    "uid, repeat_interval",
    [
        ("zfs-pool-used-warning", "12h"),
        ("zfs-pool-used-critical", "4h"),
        ("zfs-dataset-quota-headroom", "12h"),
    ],
)
def test_zfs_rules_deliver_through_the_provisioned_critical_slack_receiver(
    rules, uid, repeat_interval
):
    settings = rules[uid]["notification_settings"]
    assert settings["receiver"] == "critical-slack"
    contact_points = {
        point["name"]
        for point in load_provisioning(
            "critical-slack-contact-point.yml"
        )["contactPoints"]
    }
    assert settings["receiver"] in contact_points
    assert settings["repeat_interval"] == repeat_interval
    assert {"grafana_folder", "alertname", "instance", "dataset"} == set(
        settings["group_by"]
    )


def test_dataset_quota_rule_joins_child_datasets_to_their_pool_root(rules):
    rule = rules["zfs-dataset-quota-headroom"]
    query, threshold = rule["data"]
    expression = flattened(query["model"]["expr"])
    assert expression == QUOTA_HEADROOM_EXPRESSION, (
        "A dataset is quota-limited when its available bytes sit below its "
        "pool root's"
    )
    assert 'dataset=~".*/.*"' in expression, "Child datasets carry a slash"
    assert 'dataset!~".*/.*"' in expression, "Pool roots carry no slash"
    assert "on (instance, pool) group_left" in expression
    assert query["datasourceUid"] == "victoriametrics"
    assert query["relativeTimeRange"] == {"from": 600, "to": 0}
    assert query["model"]["instant"] is True
    assert threshold["model"]["conditions"][0]["evaluator"] == {
        "type": "lt", "params": [HEADROOM_BYTES],
    }
    assert rule["condition"] == "B"
    assert rule["for"] == "15m"
    assert rule["noDataState"] == "OK"
    assert rule["execErrState"] == "Error"
    assert rule["labels"] == {"severity": "warning", "ntfy": "true"}


def test_dataset_quota_summary_names_the_instance_dataset_and_free_amount(
    rules,
):
    annotations = rules["zfs-dataset-quota-headroom"]["annotations"]
    assert "$labels.instance" in annotations["summary"]
    assert "$labels.dataset" in annotations["summary"]
    assert "$values.A.Value" in annotations["summary"]
    assert "quota-limited" in annotations["summary"]
    assert "$labels.instance" in annotations["description"]
    assert "$labels.dataset" in annotations["description"]
    assert str(HEADROOM_BYTES) in annotations["description"]


def test_groups_follow_the_alerting_folder_and_interval_conventions(groups):
    assert {group["name"] for group in groups} == {
        "zfs-pool-used-ratio",
        "zfs-dataset-quota-headroom",
    }
    for group in groups:
        assert group["orgId"] == 1
        assert group["folder"] == "Alerting"
        assert group["interval"] == "1m"


def test_zfs_metrics_never_overlap_the_accelerator_underuse_family(rules):
    """The lt-based underuse family stays the accelerator slots alone."""
    for rule in rules.values():
        expression = " ".join(
            query["model"].get("expr", "") for query in rule["data"]
        )
        assert "accelerator:" not in expression
