"""Validate the Hermes cron alert and its dashboard link."""

from conftest import load_provisioning


def test_hermes_cron_no_success_alert_links_to_failing_jobs_panel():
    document = load_provisioning("hermes-cron-jobs.yml")
    assert len(document["groups"]) == 1
    group = document["groups"][0]
    assert group["name"] == "hermes-cron-jobs"
    rule, = group["rules"]

    assert rule["uid"] == "hermes-cron-no-success"
    annotations = rule["annotations"]
    assert annotations["__dashboardUid__"] == "hermes-cron-jobs"
    assert annotations["__panelId__"] == "4"
    expr = rule["data"][0]["model"]["expr"]
    # Outcome copies race between log sources, so joins key on host and job, never the full agent label.
    assert "unless on (host, job)" in expr
    assert "* on (job) group_left (job_name)" in expr

