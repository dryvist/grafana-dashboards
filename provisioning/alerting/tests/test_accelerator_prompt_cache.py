"""Validate the prompt cache hit rate panel and its low-cache warning rule."""

import json
from pathlib import Path

import pytest

from conftest import load_provisioning


LANE_MATCHER = 'accelerator=~"gpu-primary|gpu-secondary|mac-primary"'
PANEL_TITLE = "Prompt cache hit rate · 4h"
PANEL_ID = 19
DATASOURCE = {"type": "prometheus", "uid": "victoriametrics"}
DASHBOARD = (
    Path(__file__).resolve().parents[3] / "dashboards" / "local-llm-scoreboard.json"
)
ALERT_FILE = "accelerator-underutilized.yml"
GROUP_NAME = "accelerator-prompt-cache"
RULE_UID = "accelerator-prompt-cache-low"
PANEL_EXPR = (
    "100 * avg_over_time(accelerator:prompt_cache_hit:ratio"
    f"{{{LANE_MATCHER}}}[4h])"
)
RULE_EXPR = f"avg_over_time(accelerator:prompt_cache_hit:ratio{{{LANE_MATCHER}}}[4h])"


@pytest.fixture(scope="module")
def panels():
    return json.loads(DASHBOARD.read_text())["panels"]


def titled(panels, title):
    matches = [panel for panel in panels if panel["title"] == title]
    assert len(matches) == 1, f"Provide one {title!r} panel"
    return matches[0]


@pytest.fixture(scope="module")
def group_and_rule():
    groups = [
        group
        for group in load_provisioning(ALERT_FILE).get("groups", [])
        if group.get("name") == GROUP_NAME
    ]
    assert len(groups) == 1, f"Provision one {GROUP_NAME!r} group"
    rules = groups[0].get("rules", [])
    assert len(rules) == 1, f"Provision one rule in the {GROUP_NAME} group"
    return groups[0], rules[0]


def test_prompt_cache_panel_reads_the_brief_query(panels):
    panel = titled(panels, PANEL_TITLE)
    assert panel["id"] == PANEL_ID
    assert panel["type"] == "stat"
    assert panel["datasource"] == DATASOURCE
    target, = panel["targets"]
    assert target["expr"] == PANEL_EXPR
    assert target["instant"] is True
    assert target["datasource"] == DATASOURCE


def test_prompt_cache_panel_colors_the_kpi_band(panels):
    panel = titled(panels, PANEL_TITLE)
    defaults = panel["fieldConfig"]["defaults"]
    assert defaults["unit"] == "percent"
    assert defaults["noValue"] == "0"
    assert defaults["thresholds"] == {
        "mode": "absolute",
        "steps": [
            {"color": "red", "value": None},
            {"color": "yellow", "value": 60},
            {"color": "green", "value": 80},
        ],
    }


def test_prompt_cache_panel_opens_a_new_row_below_the_traffic_row(panels):
    panel = titled(panels, PANEL_TITLE)
    pos = panel["gridPos"]
    content_bottom = max(
        other["gridPos"]["y"] + other["gridPos"]["h"]
        for other in panels
        if other is not panel
    )
    assert pos["y"] == content_bottom
    assert pos["x"] == 0
    assert pos["w"] == 6
    assert pos["h"] == 5
    for other in panels:
        if other is panel:
            continue
        other_pos = other["gridPos"]
        assert not (
            pos["x"] < other_pos["x"] + other_pos["w"]
            and other_pos["x"] < pos["x"] + pos["w"]
            and pos["y"] < other_pos["y"] + other_pos["h"]
            and other_pos["y"] < pos["y"] + pos["h"]
        ), f"Prompt cache panel overlaps panel {other['id']}"


def test_prompt_cache_group_matches_the_file_conventions(group_and_rule):
    group, _ = group_and_rule
    assert group["orgId"] == 1
    assert group["folder"] == "Alerting"
    assert group["interval"] == "1m"


def test_low_cache_rule_queries_the_four_hour_ratio(group_and_rule):
    _, rule = group_and_rule
    assert rule["uid"] == RULE_UID
    assert rule["condition"] == "B"
    assert rule["for"] == "30m"
    data = {step["refId"]: step for step in rule["data"]}
    assert data["A"]["datasourceUid"] == "victoriametrics"
    assert data["A"]["model"]["expr"] == RULE_EXPR
    assert data["A"]["model"]["instant"] is True
    assert data["B"]["datasourceUid"] == "__expr__"
    model = data["B"]["model"]
    assert model["type"] == "threshold"
    assert model["expression"] == "A"
    assert model["conditions"][0]["evaluator"] == {"type": "lt", "params": [0.8]}


def test_low_cache_rule_stays_in_the_warning_only_digest_tier(group_and_rule):
    _, rule = group_and_rule
    assert rule["labels"] == {"severity": "warning"}
    assert "notification_settings" not in rule
    assert rule["noDataState"] == "OK"
    assert rule["execErrState"] == "Error"


def test_low_cache_rule_links_to_the_prompt_cache_panel(group_and_rule):
    _, rule = group_and_rule
    annotations = rule["annotations"]
    assert annotations["__dashboardUid__"] == "local-llm-scoreboard"
    assert annotations["__panelId__"] == str(PANEL_ID)
