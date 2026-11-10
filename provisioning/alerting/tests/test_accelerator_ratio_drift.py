"""Validate the accelerator ratio drift alert provisioning with yq and pytest."""

import json
import os
from pathlib import Path
import re
import subprocess

import pytest


ALERTING = Path(__file__).resolve().parents[1]

# Every accelerator:*:ratio series the recording rules and dashboards carry:
# the slot duty cycle per accelerator, the fleet slot utilization, plus the
# token and VRAM utilization ratios.
RATIO_SERIES = (
    "accelerator:slot_duty_cycle:ratio",
    "accelerator:slot_utilization:ratio",
    "accelerator:token_utilization:ratio",
    "accelerator:vram_utilization:ratio",
)

# The kpi label must land on the raw series, before the range function:
# range functions drop __name__, so the summary cannot recover the series
# name from the evaluated result.
EXPECTED_EXPRESSION = (
    "max_over_time( ( "
    + " or ".join(
        f'label_replace({series}, "kpi", "{series}", "", "")'
        for series in RATIO_SERIES
    )
    + " )[10m:1m] )"
)


def load_provisioning(filename):
    return json.loads(subprocess.check_output(
        [os.environ.get("YQ", "yq"), ".", str(ALERTING / filename)],
        text=True,
    ))


def recorded_ratio_series():
    """Every accelerator:*:ratio series the dashboards read."""
    return {
        name
        for dashboard in sorted((ALERTING.parents[1] / "dashboards").glob("*.json"))
        for name in re.findall(r"accelerator:[a-z_]+:ratio", dashboard.read_text())
    }


@pytest.fixture(scope="module")
def rule():
    document = load_provisioning("accelerator-ratio-drift.yml")
    assert len(document["groups"]) == 1
    rules = document["groups"][0]["rules"]
    assert len(rules) == 1, "One rule covers every ratio series and the fleet"
    return rules[0]


def test_drift_rule_keeps_the_provisioning_file_convention():
    document = load_provisioning("accelerator-ratio-drift.yml")
    group = document["groups"][0]
    assert group["orgId"] == 1
    assert group["folder"] == "Alerting"
    assert group["interval"] == "1m"
    rule = group["rules"][0]
    assert rule["uid"] == "accelerator-ratio-drift"
    assert rule["condition"] == "B"
    assert "deleteRules" not in document, "A new uid needs no deletion entry"


def test_drift_targets_every_recorded_ratio_series_above_one(rule):
    """The rule reads the raw series through one 10-minute maximum each."""
    query, threshold = rule["data"]
    expression = query["model"]["expr"]
    assert expression == EXPECTED_EXPRESSION
    targeted = set(
        re.findall(r"label_replace\((accelerator:[a-z_]+:ratio),", expression)
    )
    assert targeted == set(RATIO_SERIES), "Stamp every ratio series with a kpi label"
    assert targeted == recorded_ratio_series(), (
        "Cover every recorded ratio series; extend RATIO_SERIES for a new one"
    )
    assert "__name__" not in expression, (
        "The range function drops __name__, so never read it after it"
    )
    assert "clamp" not in expression, "Never clamp the ratio"
    assert query["datasourceUid"] == "victoriametrics"
    assert query["relativeTimeRange"]["from"] == 600
    assert query["model"]["instant"] is True
    assert threshold["datasourceUid"] == "__expr__"
    assert threshold["model"]["type"] == "threshold"
    assert threshold["model"]["expression"] == "A"
    assert threshold["model"]["conditions"][0]["evaluator"] == {
        "type": "gt", "params": [1.0],
    }


def test_drift_stays_pending_for_ten_minutes_before_firing(rule):
    assert rule["for"] == "10m"
    assert rule["noDataState"] == "OK"
    assert rule["execErrState"] == "Error"


def test_drift_summary_names_the_series_the_accelerator_and_the_slot_check(rule):
    summary = " ".join(rule["annotations"]["summary"].split())
    assert summary.startswith("{{ $labels.kpi }} exceeded 1.0 on")
    assert "{{ $labels.accelerator }}" in summary, "Name the accelerator"
    assert "the fleet" in summary, "Name the fleet series too"
    assert (
        "check accelerator:serving_slots against the engine's max_num_seqs "
        "or parallel setting"
    ) in summary


def test_drift_delivery_follows_the_accelerator_alert_convention(rule):
    assert rule["labels"] == {"severity": "warning", "ntfy": "true"}
    settings = rule["notification_settings"]
    assert settings == {
        "receiver": "critical-slack",
        "group_by": ["grafana_folder", "alertname", "accelerator"],
        "repeat_interval": "4h",
    }
    contact_points = {
        point["name"]
        for point in load_provisioning("critical-slack-contact-point.yml")["contactPoints"]
    }
    assert settings["receiver"] in contact_points
