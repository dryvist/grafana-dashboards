"""Every alert goes to the channel its severity calls for, at a bounded repeat.

Critical alerts notify a critical Slack contact point and repeat at most every
4 hours. Anything else needs no immediate action: it carries no rule-level
notification_settings, so it inherits the default policy from
ansible-proxmox-apps (grafana_stack notification-policies.yml.j2), which
repeats at most once a day.
"""

import re

import pytest

from conftest import ALERTING, load_provisioning


CRITICAL_RECEIVER_PREFIX = "critical-slack"
CRITICAL_MIN_REPEAT_SECONDS = 4 * 3600
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def seconds(duration):
    parts = re.findall(r"(\d+)([smhdw])", duration)
    assert parts and "".join(n + u for n, u in parts) == duration, duration
    return sum(int(n) * UNITS[u] for n, u in parts)


RULES = [
    (path.name, rule)
    for path in sorted(ALERTING.glob("*.yml"))
    for group in (load_provisioning(path.name).get("groups") or [])
    for rule in group["rules"]
]


@pytest.mark.parametrize("filename,rule", RULES, ids=[r["uid"] for _, r in RULES])
def test_rule_routes_by_severity_with_a_repeat_floor(filename, rule):
    severity = (rule.get("labels") or {}).get("severity")
    settings = rule.get("notification_settings")
    if severity != "critical":
        assert settings is None, (
            f"{filename}: non-critical {rule['uid']} must inherit the daily default policy"
        )
        return
    if settings is None:
        return  # The default policy's critical route applies.
    assert settings["receiver"].startswith(CRITICAL_RECEIVER_PREFIX), rule["uid"]
    assert seconds(settings["repeat_interval"]) >= CRITICAL_MIN_REPEAT_SECONDS, (
        f"{filename}: {rule['uid']} repeats more often than every 4 hours"
    )
