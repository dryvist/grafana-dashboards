"""Every provisioned alert rule must link to a dashboard panel in this repo.

Grafana links a rule to a dashboard panel through the reserved __dashboardUid__
and __panelId__ annotations; both must be set together and the panel ID must
parse as an integer (Grafana rejects the rule otherwise). The notification then
carries DashboardURL and PanelURL links. This test enforces that every rule
under provisioning/alerting/ carries that pair and that the referenced
dashboard and panel exist in dashboards/.
"""

import json
import os
from pathlib import Path
import subprocess

import pytest


ALERTING = Path(__file__).resolve().parents[1]
REPO = ALERTING.parents[1]
DASHBOARDS = REPO / "dashboards"

DASHBOARD_UID_ANNOTATION = "__dashboardUid__"
PANEL_ID_ANNOTATION = "__panelId__"


def load_provisioning(filename):
    return json.loads(subprocess.check_output(
        [os.environ.get("YQ", "yq"), ".", str(ALERTING / filename)],
        text=True,
    ))


def load_dashboard(uid):
    return json.loads((DASHBOARDS / f"{uid}.json").read_text())


def provisioned_rules():
    """Every alert rule in every provisioning file, keyed by rule uid."""
    rules = {}
    for filename in sorted(ALERTING.glob("*.yml")):
        document = load_provisioning(filename)
        for group in document.get("groups", []):
            for rule in group.get("rules", []):
                assert rule["uid"] not in rules, (
                    f"Alert rule uid {rule['uid']} provisioned twice"
                )
                rules[rule["uid"]] = rule
    return rules


ALL_RULES = sorted(provisioned_rules().items())
RULE_IDS = [uid for uid, _ in ALL_RULES]

rule_params = pytest.mark.parametrize("uid, rule", ALL_RULES, ids=RULE_IDS)


@rule_params
def test_every_rule_links_to_a_dashboard_panel(uid, rule):
    annotations = rule.get("annotations") or {}
    dashboard_uid = annotations.get(DASHBOARD_UID_ANNOTATION)
    panel_id = annotations.get(PANEL_ID_ANNOTATION)
    assert dashboard_uid, f"Rule {uid} lacks the {DASHBOARD_UID_ANNOTATION} annotation"
    assert panel_id, f"Rule {uid} lacks the {PANEL_ID_ANNOTATION} annotation"


@rule_params
def test_linked_dashboard_exists(uid, rule):
    dashboard_uid = rule["annotations"][DASHBOARD_UID_ANNOTATION]
    known_uids = {path.stem for path in DASHBOARDS.glob("*.json")}
    assert dashboard_uid in known_uids, (
        f"Rule {uid} links to dashboard {dashboard_uid}, "
        f"which has no dashboards/{dashboard_uid}.json in this repo"
    )


@rule_params
def test_linked_panel_exists_and_id_is_an_integer(uid, rule):
    """Grafana parses the panel annotation with an integer parser, so the
    annotation must be an integer, and the panel must exist in the dashboard
    for the notification's panel link to resolve."""
    annotations = rule["annotations"]
    dashboard_uid = annotations[DASHBOARD_UID_ANNOTATION]
    panel_id = annotations[PANEL_ID_ANNOTATION]
    assert str(panel_id).strip().lstrip("-").isdigit(), (
        f"Rule {uid} panel annotation {panel_id!r} is not an integer; "
        "Grafana rejects the rule"
    )
    panels = load_dashboard(dashboard_uid)["panels"]
    panel_ids = {panel["id"] for panel in panels}
    # Children of a row panel live under the row's own panels list.
    for panel in panels:
        panel_ids.update(child["id"] for child in panel.get("panels", []))
    assert int(panel_id) in panel_ids, (
        f"Rule {uid} links to panel {panel_id} of dashboard {dashboard_uid}, "
        f"which has no such panel: {sorted(panel_ids)}"
    )
