"""The runner guest wedge alert: blocked processes on the CI runner guests for 15 minutes."""

from conftest import load_provisioning


def _rule():
    groups = load_provisioning("runner-guest-blocked.yml")["groups"]
    assert len(groups) == 1 and len(groups[0]["rules"]) == 1
    return groups[0]["rules"][0]


def test_it_reads_blocked_processes_on_the_runner_guests_only():
    expr = _rule()["data"][0]["model"]["expr"]
    assert expr.startswith("min_over_time(node_procs_blocked{")
    assert expr.endswith("[15m])")
    assert 'job="guest_node_exporter"' in expr
    assert 'guest=~"docker-host.*"' in expr


def test_it_fires_above_20_for_15_minutes_and_pages():
    rule = _rule()
    evaluator = rule["data"][1]["model"]["conditions"][0]["evaluator"]
    assert evaluator == {"type": "gt", "params": [20]}
    assert rule["for"] == "15m"
    assert rule["labels"] == {"severity": "critical", "ntfy": "true"}
