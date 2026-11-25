"""ZFS quota and replica freshness alerts aggregate by their underlying cause."""

from conftest import ALERTING, load_provisioning


QUOTA_UID = "zfs-quota-tree-near-full"
REPLICA_UID = "zfs-replica-copies-stale"


def _rules_by_uid():
    rules_by_uid = {}
    for path in sorted(ALERTING.glob("*.yml")):
        for group in load_provisioning(path.name).get("groups", []):
            for rule in group.get("rules", []):
                rules_by_uid.setdefault(rule["uid"], []).append(rule)
    return rules_by_uid


def _unique_rule(uid):
    matches = _rules_by_uid().get(uid, [])
    assert len(matches) == 1, f"Expected exactly one rule with uid {uid}, got {len(matches)}"
    return matches[0]


def test_zfs_alert_rules_exist_once_and_use_warning_severity():
    rules_by_uid = _rules_by_uid()

    for uid in (QUOTA_UID, REPLICA_UID):
        matches = rules_by_uid.get(uid, [])
        assert len(matches) == 1, f"Expected exactly one rule with uid {uid}, got {len(matches)}"
        assert matches[0]["labels"]["severity"] == "warning"


def test_quota_alert_checks_headroom_against_a_positive_quota():
    quota_expr = _unique_rule(QUOTA_UID)["data"][0]["model"]["expr"]

    assert "zfs_dataset_quota_bytes" in quota_expr
    assert "> 0" in quota_expr
    assert 'name!~".*@.*"' in quota_expr
    assert "node_filesystem_" not in quota_expr


def test_replica_alert_checks_replica_snapshot_age_by_source():
    replica_expr = _unique_rule(REPLICA_UID)["data"][0]["model"]["expr"]

    assert "bulk/replica/" in replica_expr
    assert "26*3600" in replica_expr
    assert "node_filesystem_" not in replica_expr
