"""Validate PostgreSQL service and pgBackRest unit alert provisioning."""

import json

import pytest

from conftest import ALERTING, dashboard_uids, load_provisioning


EXPECTED_RULES = {
    "postgres-service-not-running": (
        "PostgreSQL service failed or inactive",
        r'node_systemd_unit_state{name=~"postgresql@.*\\.service", state=~"failed|inactive"} == 1',
        "5m",
        "critical",
        "1",
    ),
    "pgbackrest-backup-unit-failed": (
        "pgBackRest backup unit failed",
        r'node_systemd_unit_state{name=~"pgbackrest-backup@.*\\.service", state="failed"} == 1',
        "10m",
        "warning",
        "2",
    ),
}


@pytest.fixture(scope="module")
def rules():
    document = load_provisioning("postgres-resilience.yml")
    group, = document["groups"]
    assert group["orgId"] == 1
    assert group["name"] == "postgres-resilience"
    assert group["folder"] == "Alerting"
    assert group["interval"] == "5m"
    assert len(group["rules"]) == len(EXPECTED_RULES)
    assert {rule["uid"] for rule in group["rules"]} == set(EXPECTED_RULES)
    return {rule["uid"]: rule for rule in group["rules"]}


@pytest.fixture(scope="module")
def dashboard():
    path = ALERTING.parents[1] / "dashboards" / "postgres-resilience.json"
    return json.loads(path.read_text())


def test_rule_uids_are_provisioned_exactly_once():
    uids = [
        rule["uid"]
        for path in sorted(ALERTING.glob("*.yml"))
        for group in load_provisioning(path.name).get("groups", [])
        for rule in group.get("rules", [])
    ]
    for uid in EXPECTED_RULES:
        assert uids.count(uid) == 1


@pytest.mark.parametrize("uid", EXPECTED_RULES)
def test_rules_detect_only_the_expected_unit_states(rules, uid):
    title, selector, hold, severity, panel_id = EXPECTED_RULES[uid]
    rule = rules[uid]
    query, threshold = rule["data"]
    assert rule["title"] == title
    assert rule["condition"] == "B"
    assert rule["for"] == hold
    assert rule["labels"]["severity"] == severity
    assert query["refId"] == "A"
    assert query["datasourceUid"] == "victoriametrics"
    assert query["relativeTimeRange"] == {"from": 900, "to": 0}
    assert query["model"]["expr"] == f"sum by (guest, name) ({selector})"
    assert query["model"]["instant"] is True
    assert query["model"]["range"] is False
    assert threshold["refId"] == "B"
    assert threshold["datasourceUid"] == "__expr__"
    assert threshold["model"]["type"] == "threshold"
    assert threshold["model"]["expression"] == "A"
    assert threshold["model"]["conditions"][0]["evaluator"] == {
        "type": "gt", "params": [0],
    }
    assert rule["noDataState"] == "OK"
    assert rule["execErrState"] == "Error"
    assert rule["annotations"]["__dashboardUid__"] == "postgres-resilience"
    assert rule["annotations"]["__panelId__"] == panel_id
    assert '{{ index $labels "guest" }}' in rule["annotations"]["summary"]
    assert '{{ index $labels "name" }}' in rule["annotations"]["summary"]


def test_backup_rule_never_alerts_on_normal_inactive_units(rules):
    expression = rules["pgbackrest-backup-unit-failed"]["data"][0]["model"]["expr"]
    assert 'state="failed"' in expression
    assert "inactive" not in expression


def test_delivery_follows_existing_critical_and_warning_conventions(rules):
    critical = rules["postgres-service-not-running"]
    assert critical["labels"] == {"severity": "critical", "ntfy": "true"}
    assert critical["notification_settings"] == {
        "receiver": "critical-slack",
        "group_by": ["grafana_folder", "alertname", "guest", "name"],
        "repeat_interval": "4h",
    }
    contact_points = {
        point["name"]
        for point in load_provisioning("critical-slack-contact-point.yml")["contactPoints"]
    }
    assert critical["notification_settings"]["receiver"] in contact_points
    warning = rules["pgbackrest-backup-unit-failed"]
    assert warning["labels"] == {"severity": "warning"}
    assert "notification_settings" not in warning


def test_dashboard_links_resolve_to_the_unit_state_panels(rules, dashboard):
    assert dashboard["uid"] == "postgres-resilience"
    assert "postgres-resilience" in dashboard_uids()
    assert 1 <= len(dashboard["panels"]) <= 4
    panels = {str(panel["id"]): panel for panel in dashboard["panels"]}
    assert len(panels) == len(dashboard["panels"])
    for rule in rules.values():
        annotations = rule["annotations"]
        assert annotations["__dashboardUid__"] == dashboard["uid"]
        assert annotations["__panelId__"] in panels
        assert panels[annotations["__panelId__"]]["type"] == "state-timeline"


@pytest.mark.parametrize(
    "panel_id, expression",
    [
        (1, r'node_systemd_unit_state{name=~"postgresql@.*\\.service"} == 1'),
        (2, r'node_systemd_unit_state{name=~"pgbackrest-backup@.*\\.service"} == 1'),
    ],
)
def test_timeline_panels_show_current_state_by_guest_and_unit(dashboard, panel_id, expression):
    panel = next(panel for panel in dashboard["panels"] if panel["id"] == panel_id)
    assert panel["type"] == "state-timeline"
    assert panel["datasource"] == {"type": "prometheus", "uid": "victoriametrics"}
    assert panel["fieldConfig"]["defaults"]["custom"]["spanNulls"] is False
    target, = panel["targets"]
    assert target["datasource"] == panel["datasource"]
    assert target["expr"] == expression
    assert target["legendFormat"] == "{{guest}} / {{name}} / {{state}}"
    assert target["instant"] is False
    assert target["range"] is True


def test_newest_backup_age_panel_preserves_the_existing_metric(dashboard):
    panel = next(panel for panel in dashboard["panels"] if panel["id"] == 3)
    assert panel["type"] == "stat"
    assert panel["datasource"] == {"type": "prometheus", "uid": "victoriametrics"}
    target, = panel["targets"]
    assert target["datasource"] == panel["datasource"]
    assert target["expr"] == "min by (stanza) (pgbackrest_backup_since_last_completion_seconds)"
    assert target["legendFormat"] == "{{stanza}}"
    assert target["instant"] is True
    assert target["range"] is False
