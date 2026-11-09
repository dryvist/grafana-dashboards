"""Validate the local LLM scoreboard dashboard."""

import json
from pathlib import Path

import pytest


LANES = ("gpu-primary", "gpu-secondary", "mac-primary")
LANE_MATCHER = 'accelerator=~"gpu-primary|gpu-secondary|mac-primary"'
DATASOURCE = {"type": "prometheus", "uid": "victoriametrics"}
DASHBOARD = (
    Path(__file__).resolve().parents[3] / "dashboards" / "local-llm-scoreboard.json"
)


@pytest.fixture(scope="module")
def panels():
    return json.loads(DASHBOARD.read_text())["panels"]


def titled(panels, title):
    matches = [panel for panel in panels if panel["title"] == title]
    assert len(matches) == 1, f"Provide one {title!r} panel"
    return matches[0]


@pytest.mark.parametrize("lane", LANES)
def test_headline_token_utilization_reads_zero_for_a_missing_lane(panels, lane):
    # The lane series keeps its accelerator label, so only on() stops vector(0)
    # from adding a second, zero-valued series when the lane is present.
    expression = (
        "100 * avg_over_time(accelerator:token_utilization:ratio"
        f'{{accelerator="{lane}"}}[4h]) or on() vector(0)'
    )
    matches = [
        (panel, target)
        for panel in panels
        for target in panel["targets"]
        if target["expr"] == expression
    ]
    assert len(matches) == 1, f"{lane} needs exactly one headline stat"
    panel, target = matches[0]
    assert panel["type"] == "stat"
    assert panel["gridPos"]["y"] == 0
    assert target["instant"] is True
    defaults = panel["fieldConfig"]["defaults"]
    assert defaults["unit"] == "percent"
    assert defaults["noValue"] == "0"
    assert defaults["thresholds"]["steps"] == [
        {"color": "red", "value": None},
        {"color": "yellow", "value": 50},
        {"color": "green", "value": 75},
    ]


def test_generation_rate_draws_each_lane_maximum_as_a_dashed_ceiling(panels):
    panel = titled(panels, "Generation tokens/s · 1h mean vs ceiling")
    assert panel["type"] == "timeseries"
    targets = {target["refId"]: target for target in panel["targets"]}
    assert targets["A"]["expr"] == (
        f"accelerator:generation_tokens_per_second:rate1h{{{LANE_MATCHER}}}"
    )
    assert targets["B"]["expr"] == (
        f"accelerator:max_generation_tokens_per_second{{{LANE_MATCHER}}}"
    )
    ceiling, = [
        override
        for override in panel["fieldConfig"]["overrides"]
        if override["matcher"] == {"id": "byFrameRefID", "options": "B"}
    ]
    assert {
        "id": "custom.lineStyle", "value": {"dash": [10, 10], "fill": "dash"},
    } in ceiling["properties"]


def test_duty_cycle_is_the_secondary_busy_panel(panels):
    panel = titled(panels, "GPU duty cycle (secondary)")
    assert panel["type"] == "timeseries"
    target, = panel["targets"]
    assert target["expr"] == f"accelerator:busy_percent:avg5m{{{LANE_MATCHER}}}"


@pytest.mark.parametrize(
    "noun, metric",
    [
        ("requests", "litellm_proxy_total_requests_metric_total"),
        ("output tokens", "litellm_output_tokens_metric_total"),
    ],
)
def test_router_traffic_keeps_local_and_cloud_providers_side_by_side(panels, noun, metric):
    local = titled(panels, f"Local {noun} per hour")
    cloud = titled(panels, f"Cloud {noun} per hour")
    for panel, operator in ((local, "="), (cloud, "!=")):
        target, = panel["targets"]
        assert target["expr"] == (
            f"sum by (api_provider) (increase({metric}{{api_provider{operator}"
            '"hosted_vllm",team!="litellm-internal-health-check"}[1h]))'
        )
    assert cloud["gridPos"]["y"] == local["gridPos"]["y"]
    assert cloud["gridPos"]["x"] == local["gridPos"]["x"] + local["gridPos"]["w"]


def test_every_query_reads_the_prometheus_datasource(panels):
    for panel in panels:
        assert panel["datasource"] == DATASOURCE
        for target in panel["targets"]:
            assert target["datasource"] == DATASOURCE
