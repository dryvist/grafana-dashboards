"""Validate the catalog agent run-silence alert provisioning with yq and pytest."""

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


def load_dashboard(uid):
    return json.loads((ALERTING.parents[1] / "dashboards" / f"{uid}.json").read_text())


@pytest.fixture(scope="module")
def rule():
    document = load_provisioning("catalog-agent-runs.yml")
    assert len(document["groups"]) == 1
    rules = document["groups"][0]["rules"]
    assert len(rules) == 1, "One rule per silence window keeps routing predictable"
    return rules[0]


def test_silence_counts_panel_runs_per_agent_over_six_hours(rule):
    query, threshold = rule["data"]
    expression = query["model"]["expr"]
    match = re.fullmatch(
        r"sum by \(api_key_alias\) \(increase\("
        r"litellm_proxy_total_requests_metric_total\{team!=\"([^\"]+)\"\}\[6h\]\)\)",
        expression,
    )
    assert match, "Use the agent completion panel's run count over the 6h window"
    assert match[1] == "litellm-internal-health-check"
    assert query["datasourceUid"] == "victoriametrics"
    assert query["relativeTimeRange"]["from"] == 21600
    assert query["model"]["instant"] is True
    assert threshold["model"]["conditions"][0]["evaluator"] == {
        "type": "lt", "params": [1],
    }
    assert rule["condition"] == "B"
    assert rule["for"] == "0s"
    assert rule["noDataState"] == "OK"
    assert rule["execErrState"] == "Error"


def test_silence_query_and_panel_share_metric_grouping_and_exclusion(rule):
    query, _ = rule["data"]
    alert_expression = query["model"]["expr"]
    panel, target = next(
        (panel, target)
        for panel in load_dashboard("gpu-hardware")["panels"]
        for target in panel.get("targets", [])
        if panel["title"] == "Router requests by key alias · 24h"
    )
    window = r"\[(?:\d+[dhm])+\]"
    panel_shape = re.fullmatch(
        r"sum by \(api_key_alias\) \(increase\("
        r"litellm_proxy_total_requests_metric_total\{[^}]+\}" + window + r"\)\)",
        target["expr"],
    )
    alert_shape = re.fullmatch(
        r"sum by \(api_key_alias\) \(increase\("
        r"litellm_proxy_total_requests_metric_total\{[^}]+\}" + window + r"\)\)",
        alert_expression,
    )
    assert panel_shape and alert_shape, (
        "Alert and panel must keep the same metric, agent grouping and matcher shape"
    )
    assert panel["datasource"]["uid"] == query["datasourceUid"]
    assert panel["type"] == "bargauge"


def test_silence_links_to_the_agent_completion_panel(rule):
    annotations = rule["annotations"]
    assert annotations["__dashboardUid__"] == "gpu-hardware"
    assert annotations["__panelId__"] == "31"
    panel = next(
        panel
        for panel in load_dashboard("gpu-hardware")["panels"]
        if panel["id"] == 31
    )
    assert panel["title"] == "Router requests by key alias · 24h"
    assert panel["description"].startswith(
        "Router requests per API key alias over the last 24 hours"
    )


def test_silence_names_the_agent_and_the_six_hour_group(rule):
    annotations = rule["annotations"]
    assert "$labels.api_key_alias" in annotations["summary"]
    assert "$labels.api_key_alias" in annotations["description"]
    monitored = annotations["monitored_agents"]
    assert "api_key_alias" in monitored
    assert "litellm-internal-health-check" in monitored
    assert "six hours" in monitored


def test_silence_keeps_critical_delivery_per_agent(rule):
    assert rule["labels"] == {"severity": "critical", "ntfy": "true"}
    settings = rule["notification_settings"]
    assert settings["receiver"] == "critical-slack"
    assert settings["repeat_interval"] == "4h"
    assert "api_key_alias" in settings["group_by"]
    contact_points = {
        point["name"]
        for point in load_provisioning("critical-slack-contact-point.yml")["contactPoints"]
    }
    assert settings["receiver"] in contact_points


def test_silence_group_matches_the_ninety_two_pattern():
    document = load_provisioning("catalog-agent-runs.yml")
    group = document["groups"][0]
    assert group["orgId"] == 1
    assert group["folder"] == "Alerting"
    assert group["interval"] == "1m"
