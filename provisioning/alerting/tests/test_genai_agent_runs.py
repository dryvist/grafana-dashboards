"""Validate the five-tag metric view in the GenAI dashboard."""

import json
from pathlib import Path
import re

import pytest


TAGS = ("agent", "tier", "privacy_class", "model", "accelerator")
DASHBOARD = (
    Path(__file__).resolve().parents[3] / "dashboards" / "litellm-genai-otel.json"
)


@pytest.fixture(scope="module")
def agent_runs():
    dashboard = json.loads(DASHBOARD.read_text())
    panels = [panel for panel in dashboard["panels"] if panel["title"] == "Agent run attribution"]
    assert len(panels) == 1, "Provide one five-tag agent run table"
    return panels[0]


def test_agent_runs_preserve_five_dimensions_on_the_span_counter(agent_runs):
    target, = agent_runs["targets"]
    query = re.fullmatch(r"sum by \(([^)]+)\) \(llm_span_calls\{([^}]+)\}\)", target["expr"])
    assert query, "Use the emitted counter directly, including single-sample series"
    dimensions = [dimension.strip() for dimension in query[1].split(",")]
    assert set(dimensions) == set(TAGS)
    assert len(dimensions) == len(TAGS)
    assert set(query[2].split(",")) == {f'{tag}!=""' for tag in TAGS}


def test_agent_runs_use_an_explicit_instant_table_datasource(agent_runs):
    assert agent_runs["type"] == "table"
    assert agent_runs["datasource"] == {"type": "prometheus", "uid": "victoriametrics"}
    target, = agent_runs["targets"]
    assert target["instant"] is True
    assert target["range"] is False
    assert target["format"] == "table"
    assert target["datasource"] == agent_runs["datasource"]


def test_agent_runs_display_all_five_tag_columns(agent_runs):
    transform, = agent_runs["transformations"]
    assert transform["id"] == "organize"
    options = transform["options"]
    assert options["excludeByName"] == {"Time": True}
    assert [options["indexByName"][tag] for tag in TAGS] == list(range(len(TAGS)))
    assert not set(TAGS) & options["renameByName"].keys()
    assert agent_runs["options"]["showHeader"] is True
