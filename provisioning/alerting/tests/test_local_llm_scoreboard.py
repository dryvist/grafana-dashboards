"""Validate the local LLM scoreboard dashboard."""

import json
from pathlib import Path
import re

import pytest


LANES = ("gpu-primary", "gpu-secondary", "mac-primary")
LANE_MATCHER = 'accelerator=~"gpu-primary|gpu-secondary|mac-primary"'
TOKEN_RATE_WINDOWS = ("1h", "4h", "12h", "24h")
DATASOURCE = {"type": "prometheus", "uid": "victoriametrics"}
DASHBOARD = (
    Path(__file__).resolve().parents[3] / "dashboards" / "local-llm-scoreboard.json"
)
CENTS_METER = (
    Path(__file__).resolve().parents[3] / "dashboards" / "ai-cents-meter.json"
)


@pytest.fixture(scope="module")
def panels():
    return json.loads(DASHBOARD.read_text())["panels"]


def titled(panels, title):
    matches = [panel for panel in panels if panel["title"] == title]
    assert len(matches) == 1, f"Provide one {title!r} panel"
    return matches[0]


@pytest.fixture(scope="module")
def local_model_regex():
    saved_by_local = titled(
        json.loads(CENTS_METER.read_text())["panels"],
        "$ saved by local (market equivalent, cents MTD)",
    )
    regexes = {
        regex
        for target in saved_by_local["targets"]
        for regex in re.findall(
            r'api_provider="openai",model=~"([^"]+)"', target.get("expr") or ""
        )
    }
    assert len(regexes) == 1, "The cents meter needs one local model regex"
    return regexes.pop()


@pytest.mark.parametrize("lane", LANES)
def test_headline_slot_duty_cycle_reads_zero_for_a_missing_lane(panels, lane):
    # The lane series keeps its accelerator label, so only on() stops vector(0)
    # from adding a second, zero-valued series when the lane is present.
    expression = (
        "100 * avg_over_time(accelerator:slot_duty_cycle:ratio"
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


def test_headline_lane_stats_keep_their_panel_ids(panels):
    ids = {
        re.search(r'accelerator="([^"]+)"', target["expr"])[1]: panel["id"]
        for panel in panels
        for target in panel["targets"]
        if "accelerator:slot_duty_cycle:ratio" in target["expr"]
    }
    assert ids == {"gpu-primary": 1, "gpu-secondary": 2, "mac-primary": 3}


def test_headline_row_ends_with_the_context_weighted_aggregate(panels):
    panel = titled(panels, "All lanes · 4h slot duty cycle")
    target, = panel["targets"]
    assert target["expr"] == (
        "100 * avg_over_time(accelerator:slot_utilization:ratio[4h]) or on() vector(0)"
    )
    assert panel["type"] == "stat"
    assert target["instant"] is True
    headline = sorted(
        (other for other in panels if other["gridPos"]["y"] == 0),
        key=lambda other: other["gridPos"]["x"],
    )
    assert [other["id"] for other in headline] == [1, 2, 3, panel["id"]]
    assert sum(other["gridPos"]["w"] for other in headline) == 24
    defaults = panel["fieldConfig"]["defaults"]
    assert defaults["unit"] == "percent"
    assert defaults["noValue"] == "0"
    assert defaults["thresholds"] == headline[0]["fieldConfig"]["defaults"]["thresholds"]


def test_vram_row_sits_directly_below_the_headline_row(panels):
    panel = titled(panels, "VRAM utilization per accelerator")
    assert panel["type"] == "timeseries"
    target, = panel["targets"]
    assert target["expr"] == f"100 * accelerator:vram_utilization:ratio{{{LANE_MATCHER}}}"
    assert target["instant"] is False
    assert panel["fieldConfig"]["defaults"]["unit"] == "percent"
    headline_bottom = max(
        other["gridPos"]["h"] for other in panels if other["gridPos"]["y"] == 0
    )
    assert panel["gridPos"]["y"] == headline_bottom
    assert panel["gridPos"]["w"] == 24


@pytest.mark.parametrize("window", TOKEN_RATE_WINDOWS)
def test_total_tokens_per_second_row_shows_each_recorded_window(panels, window):
    panel = titled(panels, f"Total tokens/s · {window} mean")
    assert panel["type"] == "stat"
    target, = panel["targets"]
    assert target["expr"] == (
        f"accelerator:total_tokens_per_second:rate{window}{{{LANE_MATCHER}}}"
    )
    assert target["instant"] is True
    assert target["legendFormat"] == "{{accelerator}}"
    assert panel["fieldConfig"]["defaults"]["unit"] == "suffix:tok/s"


def test_total_tokens_per_second_row_follows_vram_in_window_order(panels):
    vram = titled(panels, "VRAM utilization per accelerator")
    row = [titled(panels, f"Total tokens/s · {window} mean") for window in TOKEN_RATE_WINDOWS]
    assert {panel["gridPos"]["y"] for panel in row} == {
        vram["gridPos"]["y"] + vram["gridPos"]["h"]
    }
    positions = [panel["gridPos"]["x"] for panel in row]
    assert positions == sorted(positions)
    assert sum(panel["gridPos"]["w"] for panel in row) == 24


@pytest.mark.parametrize("lane", LANES)
def test_token_utilization_stays_as_a_secondary_stat_below_the_reference_rows(
    panels, lane
):
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
    assert len(matches) == 1, f"{lane} needs exactly one secondary token stat"
    panel, target = matches[0]
    assert panel["type"] == "stat"
    assert panel["title"].endswith("token utilization (secondary)")
    assert target["instant"] is True
    reference_bottom = max(
        reference["gridPos"]["y"] + reference["gridPos"]["h"]
        for reference in (
            titled(panels, f"Total tokens/s · {window} mean")
            for window in TOKEN_RATE_WINDOWS
        )
    )
    assert panel["gridPos"]["y"] >= reference_bottom


def test_panel_ids_are_unique(panels):
    ids = [panel["id"] for panel in panels]
    assert len(ids) == len(set(ids))


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
def test_router_traffic_splits_local_and_cloud_like_the_cents_meter(
    panels, local_model_regex, noun, metric
):
    local = titled(panels, f"Local {noun} per hour")
    cloud = titled(panels, f"Cloud {noun} per hour")
    local_routes = (
        'api_provider="hosted_vllm"',
        f'api_provider="openai",model=~"{local_model_regex}"',
    )
    cloud_routes = (
        'api_provider!~"hosted_vllm|openai"',
        f'api_provider="openai",model!~"{local_model_regex}"',
    )
    for panel, routes in ((local, local_routes), (cloud, cloud_routes)):
        target, = panel["targets"]
        terms = " or ".join(
            f'increase({metric}{{{route},team!="litellm-internal-health-check"}}[1h])'
            for route in routes
        )
        assert target["expr"] == f"sum by (api_provider) ({terms})"
    assert cloud["gridPos"]["y"] == local["gridPos"]["y"]
    assert cloud["gridPos"]["x"] == local["gridPos"]["x"] + local["gridPos"]["w"]


def test_every_query_reads_the_prometheus_datasource(panels):
    for panel in panels:
        assert panel["datasource"] == DATASOURCE
        for target in panel["targets"]:
            assert target["datasource"] == DATASOURCE
