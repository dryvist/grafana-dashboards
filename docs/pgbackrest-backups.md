# pgBackRest backups

The [pgBackRest backups dashboard](../dashboards/pgbackrest-backups.json) shows
full backup age, newest backup age, the last backup error status, and newest
backup age over time. Each panel groups its series by stanza.

The dashboard uses the `victoriametrics` datasource. Full backup age is grouped
by stanza from `pgbackrest_backup_since_last_completion_seconds` with
`backup_type="full"`. Newest backup age is the minimum age across the metric's
backup type and block incremental series. The alert fires when full backup age
exceeds 8 days, newest backup age exceeds 30 hours, or the latest backup error
status is non-zero.

The last backup status panel and alert use
`pgbackrest_backup_last_error_status{backup_type="incr"}`. The exporter
documents that the incremental last-backup series carries the latest full or
differential value when either is newer than the last incremental backup.
Status `1` indicates one or more page checksum errors.
