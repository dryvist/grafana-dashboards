"""Validate the accelerator ratio drift alert provisioning with yq and pytest."""

import json
import os
from pathlib import Path
import re
import subprocess

import pytest


ALERTING = Path(__file__).resolve().parents[1]


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
    assert len(rules) == 1, "One rule covers every accelerator and the fleet"
    return rules[0]


def test_drift_alerts_every_recorded_ratio_series_above_one_for_ten_minutes(rule):
    """A ratio above 1.0 means the slot-count constant drifted from the engine."""
    query, threshold = rule["data"]
    expression = query["model"]["expr"]
    match = re.search(r'__name__=~"accelerator:\(([^)]+)\):ratio"', expression)
    assert match, "Select the ratio series by name inside one max_over_time"
    targeted = {f"accelerator:{name}:ratio" for name in match[1].split("|")}
    recorded = recorded_ratio_series()
    assert recorded, "The dashboards must read at least one ratio series"
    assert targeted == recorded, (
        "The rule must target exactly the recorded accelerator:*:ratio series"
    )
    assert "max_over_time(" in expression
    assert re.search(r"\[10m\]\s*\)", expression)
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
    assert rule["condition"] == "B"
    assert rule["for"] == "10m"
    assert rule["noDataState"] == "OK"
    assert rule["execErrState"] == "Error"


def test_drift_summary_names_the_series_the_accelerator_and_the_slot_check(rule):
    summary = rule["annotations"]["summary"]
    assert "{{ $labels.kpi }}" in summary, "Name the fired series"
    assert "{{ $labels.accelerator }}" in summary, "Name the accelerator"
    assert (
        "check accelerator:serving_slots against the engine's max_num_seqs "
        "or parallel setting"
    ) in summary
    expression = rule["data"][0]["model"]["expr"]
    assert 'label_replace(' in expression
    assert '"kpi", "$1", "__name__"' in expression, (
        "The summary's series name must come from __name__"
    )


def test_drift_delivery_follows_the_accelerator_convention(rule):
    document = load_provisioning("accelerator-ratio-drift.yml")
    group = document["groups"][0]
    assert rule["uid"] == group["name"] == "accelerator-ratio-drift"
    assert group["orgId"] == 1
    assert group["folder"] == "Alerting"
    assert group["interval"] == "1m"
    assert rule["labels"] == {"severity": "warning", "ntfy": "true"}
    settings = rule["notification_settings"]
    assert settings["receiver"] == "critical-slack"
    assert "accelerator" in settings["group_by"]
    contact_points = {
        point["name"]
        for point in load_provisioning("critical-slack-contact-point.yml")["contactPoints"]
    }
    assert settings["receiver"] in contact_points
