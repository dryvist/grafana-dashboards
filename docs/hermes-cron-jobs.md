# Hermes cron jobs

The [Hermes cron jobs dashboard](../dashboards/hermes-cron-jobs.json) shows jobs with a recent delivered
or silent run, the 24-hour success rate by agent, run outcomes over time, and jobs that failed
without a delivered or silent run in six hours.

The dashboard uses the `victoriametrics` datasource and the `hermes_cron_run_outcome` gauge, one sample per run
outcome, which the panels count with `count_over_time`.
When job profile data is available, the success-rate panel attributes runs through the job ID;
without it, the panel groups runs by the agent label on the gauge.

The warning alert links to the failing-jobs table and fires when a job has failed runs without a delivered or silent run in the last six hours.
