"""Validate model-serving alert provisioning with yq and pytest."""

import json
import os
from pathlib import Path
import re
import subprocess

import pytest


ALERTING = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def rules():
    document = json.loads(subprocess.check_output(
        [os.environ.get("YQ", "yq"), ".", str(ALERTING / "accelerator-underutilized.yml")],
        text=True,
    ))
    return {
        rule["uid"]: rule
        for group in document["groups"]
        for rule in group["rules"]
    }


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


def test_queue_sums_engine_waiters_and_includes_the_120_boundary(rules):
    rule = rules["serving-queue-waiting-high"]
    query, threshold = rule["data"]
    assert query["model"]["expr"] == (
        'sum(llamacpp:requests_deferred{job="llm_gpu_engine"})'
    )
    dashboard = (ALERTING.parents[1] / "dashboards" / "llm-serving-4080.json").read_text()
    assert "llamacpp:requests_deferred" in dashboard
    assert threshold["model"]["type"] == "math"
    assert threshold["model"]["expression"] == "$A >= 120"
    assert rule["for"] == "0s"
    assert rule["noDataState"] == "NoData"
