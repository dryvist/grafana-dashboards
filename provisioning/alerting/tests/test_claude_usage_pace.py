"""Validate the Claude usage pace alert provisioning with yq and pytest."""

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
def rule():
    document = load_provisioning("claude-usage-pace.yml")
    assert len(document["groups"]) == 1
    group = document["groups"][0]
    assert group["name"] == "claude-usage-pace"
    assert len(group["rules"]) == 1
    rule = group["rules"][0]
    assert rule["uid"] == "claude-usage-pace-over-line"
    return rule


def test_one_group_with_one_rule():
    document = load_provisioning("claude-usage-pace.yml")
    assert len(document["groups"]) == 1
    group = document["groups"][0]
    assert group["name"] == "claude-usage-pace"
    assert group["orgId"] == 1
    assert group["folder"] == "Alerting"
    assert group["interval"] == "5m"
    assert [rule["uid"] for rule in group["rules"]] == [
        "claude-usage-pace-over-line",
    ]


def test_query_a_costs_claude_usage_over_the_last_24_hours(rule):
    query = rule["data"][0]
    assert query["refId"] == "A"
    assert query["datasourceUid"] == "victoriametrics"
    assert query["relativeTimeRange"] == {"from": 86400, "to": 0}
    expression = query["model"]["expr"]
    assert "claude_code_cost_usage_total" in expression
    assert 'model=~"claude-.*"' in expression
    assert "[24h]" in expression
    assert query["model"]["instant"] is True


def test_condition_compares_the_cost_against_the_daily_line(rule):
    assert rule["condition"] == "B"
    by_ref = {item["refId"]: item for item in rule["data"]}
    assert by_ref["B"]["datasourceUid"] == "__expr__"
    assert by_ref["B"]["model"]["type"] == "math"
    assert by_ref["B"]["model"]["expression"] == "$A > 550"
    assert by_ref["C"]["datasourceUid"] == "__expr__"
    assert by_ref["C"]["model"]["type"] == "math"
    assert by_ref["C"]["model"]["expression"] == "$A / 550 * 100"


def test_wait_and_delivery_match_the_repo_pattern(rule):
    assert rule["for"] == "15m"
    assert rule["noDataState"] == "OK"
    assert rule["execErrState"] == "Error"
    assert rule["labels"] == {"severity": "warning", "ntfy": "true"}


def test_rule_links_the_burn_rate_panel(rule):
    annotations = rule["annotations"]
    assert annotations["__dashboardUid__"] == "claude-subscription-burn"
    assert annotations["__panelId__"] == "2"
    panels = load_dashboard("claude-subscription-burn")["panels"]
    assert any(panel["id"] == 2 for panel in panels)
