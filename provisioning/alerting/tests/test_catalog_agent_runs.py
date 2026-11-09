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


def test_silence_counts_the_shared_dify_path_over_six_hours(rule):
    query, threshold = rule["data"]
    expression = query["model"]["expr"]
    match = re.fullmatch(
        r"sum\(increase\("
        r"litellm_proxy_total_requests_metric_total\{"
        r'api_key_alias="([^"]+)", team!="([^"]+)"'
        r"\}\[6h\]\)\) or vector\(0\)",
        expression,
    )
    assert match, "Sum the shared catalog agents' path over the 6h window"
    assert match[1] == "dify"
    assert match[2] == "litellm-internal-health-check"
    assert " or vector(0)" in expression, (
        "A silent path must return 0 instead of no data, which never fires"
    )
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


def test_silence_names_the_shared_dify_path_and_its_scope(rule):
    annotations = rule["annotations"]
    assert "Dify router path" in annotations["summary"]
    assert "six hours" in annotations["summary"]
    assert "Dify router path" in annotations["description"]
    assert "six hours" in annotations["description"]
    monitored = annotations["monitored_agents"]
    assert "All catalog agents" in monitored
    assert "api_key_alias" in monitored
    assert "no per-agent run series" in monitored


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


def test_silence_keeps_critical_delivery_without_per_alias_grouping(rule):
    assert rule["labels"] == {"severity": "critical", "ntfy": "true"}
    settings = rule["notification_settings"]
    assert settings["receiver"] == "critical-slack"
    assert settings["repeat_interval"] == "24h"
    assert settings["group_by"] == ["grafana_folder", "alertname"]
    assert "api_key_alias" not in settings["group_by"]
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
