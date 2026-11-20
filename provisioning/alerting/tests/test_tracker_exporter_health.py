"""Validate the tracker SQL exporter alert provisioning."""

import json

from conftest import ALERTING, dashboard_uids, load_provisioning


EXPECTED_RULES = {
    "tracker-sql-exporter-down": (
        'up{job="tracker_sql_exporter"} == 0',
        "15m",
        "1",
        "lt",
        [1.0],
    ),
    "tracker-vikunja-open-tasks-missing": (
        "absent(vikunja_open_tasks)",
        "30m",
        "1",
        "gt",
        [0.0],
    ),
    "tracker-zammad-open-tickets-missing": (
        "absent(zammad_open_tickets)",
        "30m",
        "1",
        "gt",
        [0.0],
    ),
}


def test_tracker_exporter_rules_use_the_provisioning_convention():
    document = load_provisioning("tracker-exporter-health.yml")
    assert len(document["groups"]) == 1
    group = document["groups"][0]
    assert group["orgId"] == 1
    assert group["name"] == "tracker-exporter-health"
    assert group["folder"] == "Alerting"
    assert group["interval"] == "1m"
    assert {rule["uid"] for rule in group["rules"]} == set(EXPECTED_RULES)
    assert "deleteRules" not in document


def test_tracker_exporter_rules_detect_only_the_expected_conditions():
    document = load_provisioning("tracker-exporter-health.yml")
    rules = {rule["uid"]: rule for rule in document["groups"][0]["rules"]}

    for uid, (expression, hold, panel_id, evaluator, params) in EXPECTED_RULES.items():
        rule = rules[uid]
        query, threshold = rule["data"]
        assert rule["condition"] == "B"
        assert rule["for"] == hold
        assert query["datasourceUid"] == "prometheus"
        assert query["model"]["expr"] == expression
        assert query["model"]["instant"] is True
        assert threshold["datasourceUid"] == "__expr__"
        assert threshold["model"]["type"] == "threshold"
        assert threshold["model"]["expression"] == "A"
        assert threshold["model"]["conditions"][0]["evaluator"] == {
            "type": evaluator,
            "params": params,
        }
        assert rule["labels"] == {"severity": "warning"}
        assert "notification_settings" not in rule
        assert rule["noDataState"] == "OK"
        assert rule["execErrState"] == "Error"
        assert rule["annotations"]["__dashboardUid__"] == "telemetry-health"
        assert rule["annotations"]["__panelId__"] == panel_id


def test_tracker_exporter_dashboard_links_resolve_to_overview_panels():
    document = load_provisioning("tracker-exporter-health.yml")
    assert "telemetry-health" in dashboard_uids()
    dashboard_path = ALERTING.parents[1] / "dashboards" / "telemetry-health.json"
    dashboard = json.loads(dashboard_path.read_text())
    panels = {str(panel["id"]): panel["title"] for panel in dashboard["panels"]}
    assert panels["1"] == "Target up ratio by job"

    for rule in document["groups"][0]["rules"]:
        assert rule["annotations"]["__panelId__"] in panels
