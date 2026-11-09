"""Validate the local LLM KPI trends dashboard."""

import json
from pathlib import Path
import re

import pytest


LANES = ("gpu-primary", "gpu-secondary", "mac-primary")
LANE_MATCHER = 'accelerator=~"gpu-primary|gpu-secondary|mac-primary"'
# Local router lanes that report api_provider="openai"; the output-token
# selectors must name them or their tokens land in the cloud series.
LANE_IDS = ("qwen3.5-9b-4080", "qwen3.5-9b", "qwen3.6-35b-a3b")
DATASOURCE = {"type": "prometheus", "uid": "victoriametrics"}
DASHBOARD = (
    Path(__file__).resolve().parents[3] / "dashboards" / "local-llm-kpi-trends.json"
)
CENTS_METER = (
    Path(__file__).resolve().parents[3] / "dashboards" / "ai-cents-meter.json"
)
METRICS = (
    Path(__file__).resolve().parents[3] /
    "dashboards" / "litellm-all-prometheus-metrics.json"
)
SCOREBOARD = (
    Path(__file__).resolve().parents[3] / "dashboards" / "local-llm-scoreboard.json"
)
HEALTH_CHECK = 'team!="litellm-internal-health-check"'
DAILY_TITLES = (
    "Daily generated tokens per accelerator",
    "Local vs cloud output tokens per day",
    "Router requests per day by key alias · top 10",
    "GPU duty cycle (secondary)",
)


@pytest.fixture(scope="module")
def dashboard():
    return json.loads(DASHBOARD.read_text())


@pytest.fixture(scope="module")
def panels(dashboard):
    return dashboard["panels"]


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


@pytest.mark.parametrize("uid, url", [
    ("local-llm-kpi-trends", "/d/local-llm-scoreboard"),
    ("local-llm-scoreboard", "/d/local-llm-kpi-trends"),
])
def test_the_lane_dashboards_link_each_other_by_uid(uid, url):
    other = json.loads(
        (Path(__file__).resolve().parents[3] / "dashboards" / f"{uid}.json").read_text()
    )
    links = other["links"]
    assert len(links) == 1, f"The {uid} dashboard needs one dashboard link"
    link, = links
    assert link["url"] == url


@pytest.mark.parametrize("lane", LANES)
def test_token_utilization_draws_each_lane_against_goal_and_aim(panels, lane):
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
    assert len(matches) == 1, f"{lane} needs exactly one token utilization target"
    panel, target = matches[0]
    assert panel["type"] == "timeseries"
    assert target["instant"] is False
    defaults = panel["fieldConfig"]["defaults"]
    assert defaults["unit"] == "percent"
    assert defaults["noValue"] == "0"
    assert defaults["custom"]["thresholdsStyle"]["mode"] == "dashed"
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


def test_daily_generated_tokens_use_the_rate1h_counter_sources(panels):
    panel = titled(panels, "Daily generated tokens per accelerator")
    assert panel["type"] == "timeseries"
    assert panel["interval"] == "1d"
    custom = panel["fieldConfig"]["defaults"]["custom"]
    assert custom["drawStyle"] == "bars"
    assert custom["stacking"] == {"mode": "normal", "group": "A"}
    targets = {target["refId"]: target for target in panel["targets"]}
    assert targets["A"]["expr"] == (
        'sum(increase(vllm:generation_tokens_total'
        '{job="llm_gpu_engine",accelerator=~"gpu-primary|"}[1d]))'
    )
    assert targets["B"]["expr"] == (
        'sum(increase(llamacpp:tokens_predicted_total'
        '{job="llm_gpu_engine",accelerator=~"gpu-secondary|"}[1d]))'
    )
    assert targets["C"]["expr"] == (
        "sum(increase(litellm_output_tokens_metric_total"
        '{job="llm_router",model="mlx-community/Qwen3.8-27B-4bit",'
        f'{HEALTH_CHECK},accelerator=~"mac-primary|"}}[1d]))'
    )
    assert [target["legendFormat"] for target in panel["targets"]] == list(LANES)


def test_daily_output_tokens_split_local_and_cloud_like_the_cents_meter(
    panels, local_model_regex
):
    panel = titled(panels, "Local vs cloud output tokens per day")
    assert panel["type"] == "timeseries"
    assert panel["interval"] == "1d"
    custom = panel["fieldConfig"]["defaults"]["custom"]
    assert custom["drawStyle"] == "line"
    assert custom.get("stacking", {}).get("mode", "none") == "none"
    targets = {target["refId"]: target for target in panel["targets"]}
    metric = "litellm_output_tokens_metric_total"
    split_regex = "|".join((*local_model_regex.split("|"), *LANE_IDS))
    local_routes = (
        'api_provider="hosted_vllm"',
        f'api_provider="openai",model=~"{split_regex}"',
    )
    cloud_routes = (
        'api_provider!~"hosted_vllm|openai"',
        f'api_provider="openai",model!~"{split_regex}"',
    )
    for ref_id, legend, routes in (
        ("A", "Local", local_routes),
        ("B", "Cloud", cloud_routes),
    ):
        terms = " or ".join(
            f"increase({metric}{{{route},{HEALTH_CHECK}}}[1d])"
            for route in routes
        )
        assert targets[ref_id]["expr"] == f"sum({terms})"
        assert targets[ref_id]["legendFormat"] == legend


def test_local_and_cloud_output_regexes_stay_complements_over_the_lane_ids(
    panels, local_model_regex
):
    panel = titled(panels, "Local vs cloud output tokens per day")
    metric = "litellm_output_tokens_metric_total"
    selectors = {}
    for target in panel["targets"]:
        match = re.search(
            rf'{metric}{{api_provider="openai",model([=!])~"([^"]+)"',
            target["expr"],
        )
        assert match, f"{target['refId']} needs an openai model selector"
        selectors[target["refId"]] = match
    assert set(selectors) == {"A", "B"}
    assert selectors["A"].group(1) == "="
    assert selectors["B"].group(1) == "!"
    local_ids = selectors["A"].group(2).split("|")
    cloud_ids = selectors["B"].group(2).split("|")
    assert len(local_ids) == len(set(local_ids)), "Duplicate local model id"
    assert len(cloud_ids) == len(set(cloud_ids)), "Duplicate cloud model id"
    assert cloud_ids == local_ids, "The selectors must complement one id set"
    assert set(LANE_IDS) <= set(local_ids)
    assert set(local_model_regex.split("|")) <= set(local_ids)


def test_router_requests_per_day_rank_key_aliases_with_the_health_check_excluded(
    panels,
):
    panel = titled(panels, "Router requests per day by key alias · top 10")
    assert panel["type"] == "timeseries"
    assert panel["interval"] == "1d"
    target, = panel["targets"]
    assert target["expr"] == (
        "topk(10, sum by (api_key_alias) (increase("
        f"litellm_proxy_total_requests_metric_total{{{HEALTH_CHECK}}}[1d])))"
    )


def test_duty_cycle_averages_the_recorded_busy_percent_per_day(panels):
    panel = titled(panels, "GPU duty cycle (secondary)")
    assert panel["type"] == "timeseries"
    assert panel["interval"] == "1d"
    target, = panel["targets"]
    assert target["expr"] == (
        f"avg_over_time(accelerator:busy_percent:avg5m{{{LANE_MATCHER}}}[1d])"
    )


def test_429_and_queued_request_series_reuse_the_metrics_dashboard_metrics(panels):
    metrics_json = METRICS.read_text()
    panel = titled(panels, "Router 429 rate and queued requests")
    targets = {target["refId"]: target for target in panel["targets"]}
    assert targets["A"]["expr"] == (
        'sum(rate(litellm_proxy_total_requests_metric_total'
        '{status_code="429"}[$__rate_interval]))'
        " or (0 * sum(rate(litellm_proxy_total_requests_metric_total"
        "[$__rate_interval])))"
    )
    assert targets["B"]["expr"] == "sum(litellm_admission_queued_requests)"
    assert "litellm_proxy_total_requests_metric_total" in metrics_json
    assert "by (status_code)" in metrics_json
    assert "litellm_admission_queued_requests" in metrics_json


@pytest.mark.parametrize("title", DAILY_TITLES)
def test_daily_panels_advance_in_one_day_steps(panels, title):
    panel = titled(panels, title)
    assert panel["interval"] == "1d"
    assert panel["maxDataPoints"] == 10000
    for target in panel["targets"]:
        assert target["interval"] == "1d"


def test_trends_default_to_one_week_of_utc_days(dashboard):
    assert dashboard["timezone"] == "utc"
    assert dashboard["time"] == {"from": "now-7d", "to": "now"}
    assert dashboard["uid"] == "local-llm-kpi-trends"
    assert dashboard["title"] == "Local LLM KPI trends"
    assert dashboard["templating"]["list"] == []


def test_every_query_reads_the_prometheus_datasource_without_template_variables(
    panels,
):
    for panel in panels:
        assert panel["datasource"] == DATASOURCE
        for target in panel["targets"]:
            assert target["datasource"] == DATASOURCE
            assert "${" not in target["expr"]
