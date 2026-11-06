"""Validate model-serving alert provisioning with yq and pytest."""

import json
import os
from pathlib import Path
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
