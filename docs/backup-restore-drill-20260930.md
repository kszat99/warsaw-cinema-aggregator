# Independent restore drill — September 30, 2026

Verified at 13:00:59 UTC / 15:00:59 Warsaw. Code/schema: `0006_seat_retry`.

A fresh consistent SQLite backup was created on the VPS using the existing backup
command, transferred over verified SSH, and validated on the Windows development PC.
Production workers were not stopped and the live database was not restored or changed.

## Evidence

- Backup: `backup-restore-drill-20260930T1300.sqlite3`.
- Size: 1,187,840 bytes.
- SHA-256 on VPS and PC:
  `9c96a02cd164217a092802b03f0b73b892712536da7963d61f121a63bd4dec46`.
- SQLite full integrity check: `ok`; foreign-key check: no violations.
- Preserved rows: 7 imports, 868 screening snapshot rows, 990 seat jobs,
  316 observations and 3 alert-state records.
- Actual application against restored file: `/health/ready` HTTP 200;
  `/api/v1/screenings?limit=5` HTTP 200 with five screenings.
- Backup hash unchanged after read-only API verification.
- On a separate working copy, two planner runs left job count at 990: no duplicates.

Local files are in ignored `tmp/restore-drill-20260930/`: the verified backup,
`planner-restore.sqlite3`, and `evidence.json`. They are not committed to GitHub.
The protected VPS backup remains in `/var/lib/cinema-pilot/backups/`; a private
transfer copy is in `/home/ubuntu/cinema-pilot-upload/`.

This demonstrates recovery of database/application reads and planner state on another
machine. It does not prove a full replacement-server deployment, automatic offsite
uploads, restoration of credentials or a cloud-download recovery procedure.

## Offsite destination recommendation (historical proposal)

Owner requested a free option. Recommend Backblaze B2, pending owner account creation:

- [Official pricing](https://www.backblaze.com/cloud-storage/pricing): first 10 GB free;
  free downloads up to three times average monthly stored data, with paid overage.
- [Official signup](https://www.backblaze.com/sign-up/cloud-storage): no credit card
  required to start. Verified September 30, 2026; recheck terms during setup.
- At the present snapshot size, 11 full retained copies are about 13 MB before
  compression/encryption overhead. This is an estimate at current size, not a lifetime
  free-storage guarantee.

Proposed implementation after account setup: private bucket, scoped application key
stored only in root-protected server configuration, encrypted backups with a recovery
secret also saved outside the VPS, scheduled uploads, bounded retention/storage warning,
and failed/stale upload alerts. Validate upload and download/restore before marking
offsite protection complete. Select tooling during implementation; no cloud credentials
or bucket are configured yet and no upload service is enabled.

Update, September 30 at 17:25 Warsaw: account setup, encrypted cloud upload and
cloud-download restore are now complete. See [current offsite runbook](offsite-backups.md)
for the deployed schedule, recovery evidence and remaining limitations.
