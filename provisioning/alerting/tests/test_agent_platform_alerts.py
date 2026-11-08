"""Validate model-serving alert provisioning with yq and pytest."""

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
def rules():
    document = load_provisioning("accelerator-underutilized.yml")
    provisioned = [
        rule
        for group in document["groups"]
        for rule in group["rules"]
    ]
    indexed = {rule["uid"]: rule for rule in provisioned}
    assert len(indexed) == len(provisioned), "Alert rule UIDs must be unique"
    return indexed


def test_gpu_underuse_window_threshold_and_delivery(rules):
    rule = rules["accelerator-underutilized"]
    query, threshold = rule["data"]
    assert query["model"]["expr"] == (
        'avg_over_time(accelerator:busy_percent:avg5m'
        '{accelerator=~"gpu-primary|gpu-secondary|mac-primary"}[4h])'
    )
    assert threshold["model"]["conditions"][0]["evaluator"] == {
        "type": "lt", "params": [50],
    }
    assert rule["for"] == "0s"
    assert rule["labels"]["severity"] == "critical"
    assert rule["notification_settings"]["receiver"] == "critical-slack"
    assert rule["notification_settings"]["repeat_interval"] == "4h"
    assert "accelerator" in rule["notification_settings"]["group_by"]


def test_agent_completion_kpi_fires_below_50_percent_over_4_hours(rules):
    rule = rules["agent-completion-busy-kpi"]
    query, threshold = rule["data"]
    assert query["model"]["expr"] == (
        'avg_over_time(accelerator:busy_percent:avg5m'
        '{accelerator=~"gpu-primary|gpu-secondary|mac-primary"}[4h])'
    )
    assert query["datasourceUid"] == "victoriametrics"
    assert query["relativeTimeRange"]["from"] == 14400
    assert threshold["model"]["conditions"][0]["evaluator"] == {
        "type": "lt", "params": [50],
    }
    assert rule["for"] == "0s"


def test_agent_completion_kpi_links_a_panel_charting_every_machine(rules):
    annotations = rules["agent-completion-busy-kpi"]["annotations"]
    dashboard = load_dashboard(annotations["__dashboardUid__"])
    assert dashboard["uid"] == annotations["__dashboardUid__"]
    panel, = [
        panel for panel in dashboard["panels"]
        if panel["id"] == int(annotations["__panelId__"])
    ]
    assert [target["expr"] for target in panel["targets"]] == ["accelerator:busy_percent:avg5m"]


def test_agent_completion_kpi_stat_panels_match_the_alert_machines_and_floor(rules):
    query, threshold = rules["agent-completion-busy-kpi"]["data"]
    alerted = re.search(r'accelerator=~"([^"]+)"', query["model"]["expr"])[1].split("|")
    floor, = threshold["model"]["conditions"][0]["evaluator"]["params"]
    panels = {}
    for panel in load_dashboard("gpu-hardware")["panels"]:
        for target in panel.get("targets", []):
            match = re.fullmatch(
                r'avg_over_time\(accelerator:busy_percent:avg5m'
                r'\{accelerator="([^"]+)"\}\[4h\]\)',
                target["expr"],
            )
            if match:
                assert match[1] not in panels, f"{match[1]} has more than one KPI panel"
                panels[match[1]] = (panel, target)
    assert sorted(panels) == sorted(alerted)
    for panel, target in panels.values():
        assert panel["type"] == "stat"
        assert target["instant"] is True
        assert panel["fieldConfig"]["defaults"]["thresholds"]["steps"] == [
            {"color": "red", "value": None},
            {"color": "yellow", "value": floor},
            {"color": "green", "value": 75},
        ]


def test_agent_completion_router_requests_exclude_the_health_check_team():
    expression = (
        "sum by (api_key_alias) (increase(litellm_proxy_total_requests_metric_total"
        '{team!="litellm-internal-health-check"}[24h]))'
    )
    targets = [
        target
        for panel in load_dashboard("gpu-hardware")["panels"]
        for target in panel.get("targets", [])
        if target["expr"] == expression
    ]
    assert len(targets) == 1
    assert targets[0]["instant"] is True


def test_token_absence_is_independent_for_each_serving_lane(rules):
    rule = rules["accelerator-token-kpi-missing"]
    expression = rule["data"][0]["model"]["expr"]
    lanes = re.findall(
        r'absent_over_time\(accelerator:token_utilization:ratio'
        r'\{accelerator="([^"]+)"\}\[30m\]\)',
        expression,
    )
    assert set(lanes) == {"gpu-primary", "gpu-secondary", "mac-primary"}
    assert len(lanes) == 3
    assert " or " in expression
    assert rule["for"] == "0s"
    assert rule["noDataState"] == "OK"
    assert rule["data"][1]["model"]["conditions"][0]["evaluator"] == {
        "type": "gt", "params": [0],
    }


def test_shared_critical_delivery_and_condition_references(rules):
    for rule in rules.values():
        assert rule["labels"] == rules["accelerator-underutilized"]["labels"]
        assert rule["notification_settings"] == (
            rules["accelerator-underutilized"]["notification_settings"]
        )
        assert rule["execErrState"] == "Error"
        queries = {query["refId"]: query for query in rule["data"]}
        assert rule["condition"] in queries
        assert len(queries) == len(rule["data"])
        assert queries["A"]["model"]["instant"] is True
        assert queries["B"]["model"]["expression"] in ("A", "$A >= 120")


def test_router_uses_dashboard_status_label_and_native_threshold_input(rules):
    rule = rules["router-429-rate-high"]
    query, threshold = rule["data"]
    expression = query["model"]["expr"]
    assert expression == (
        'sum(rate(litellm_proxy_total_requests_metric_total{status_code="429"}[5m]))'
        ' or (0 * sum(rate(litellm_proxy_total_requests_metric_total[5m])))'
    )
    dashboard = (ALERTING.parents[1] / "dashboards" / "litellm-all-prometheus-metrics.json").read_text()
    assert "litellm_proxy_total_requests_metric_total" in dashboard
    assert "by (status_code)" in dashboard
    evaluator = threshold["model"]["conditions"][0]["evaluator"]
    assert evaluator["type"] == "gt"
    assert len(evaluator["params"]) == 1
    assert isinstance(evaluator["params"][0], (int, float))
    assert evaluator["params"][0] >= 0
    assert "${" not in expression
    assert rule["noDataState"] == "NoData"


def test_queue_sums_recorded_lane_waiters_and_includes_the_120_boundary(rules):
    rule = rules["serving-queue-waiting-high"]
    query, threshold = rule["data"]
    assert query["model"]["expr"] == "sum(llm:requests_waiting)"
    assert query["datasourceUid"] == "victoriametrics"
    assert threshold["model"]["type"] == "math"
    assert threshold["model"]["expression"] == "$A >= 120"
    assert rule["for"] == "0s"


def test_queue_growth_requires_positive_total_slope_held_for_15_minutes(rules):
    rule = rules["serving-queue-growing"]
    query, threshold = rule["data"]
    assert query["model"]["expr"] == (
        "deriv(sum(llm:requests_waiting)[5m:1m])"
    )
    assert query["datasourceUid"] == "victoriametrics"
    assert query["relativeTimeRange"]["from"] >= 300
    assert threshold["model"]["conditions"][0]["evaluator"] == {
        "type": "gt", "params": [0],
    }
    assert rule["for"] == "15m"


@pytest.mark.parametrize("uid", ["serving-queue-growing", "serving-queue-waiting-high"])
def test_empty_queue_results_stay_ok_for_flat_or_drained_queues(rules, uid):
    """Absent waiters take Grafana's OK path; query errors remain visible."""
    rule = rules[uid]
    assert rule["noDataState"] == "OK"
    assert rule["execErrState"] == "Error"


def test_notification_receivers_reference_existing_contact_points(rules):
    document = load_provisioning("critical-slack-contact-point.yml")
    contact_points = {point["name"] for point in document["contactPoints"]}
    assert all(
        rule["notification_settings"]["receiver"] in contact_points
        for rule in rules.values()
    )


@pytest.mark.parametrize("path", sorted(ALERTING.glob("*.yml")), ids=lambda path: path.name)
def test_dashboard_links_name_both_dashboard_and_panel(path):
    # Grafana refuses to provision every alert file when a rule sets one of these without the other.
    for group in load_provisioning(path.name).get("groups", []):
        for rule in group.get("rules", []):
            keys = {"__dashboardUid__", "__panelId__"} & set(rule.get("annotations", {}))
            assert len(keys) in (0, 2), f"{rule['uid']} sets only {keys}"
