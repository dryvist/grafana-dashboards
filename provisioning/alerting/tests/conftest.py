"""Shared helpers for the alert provisioning tests."""

import json
import os
from pathlib import Path
import subprocess


ALERTING = Path(__file__).resolve().parents[1]


def load_provisioning(filename):
    return json.loads(subprocess.check_output(
        [os.environ.get("YQ", "yq"), ".", str(ALERTING / filename)],
        text=True,
    ))


def dashboard_uids():
    return {
        json.loads(path.read_text())["uid"]
        for path in (ALERTING.parents[1] / "dashboards").glob("*.json")
    }
