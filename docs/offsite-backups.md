# Encrypted offsite backups

Deployed and verified September 30, 2026. The VPS runs the job independently of the PC.
The public website and seat collection are unchanged.

## Operation

`cinema-offsite-backup.timer` starts daily at 03:15 UTC, with up to two minutes of
jitter (05:15 Warsaw in summer, 04:15 in winter). Persistent scheduling catches a
missed run after boot. The separate local backup timer remains enabled.

Each run creates a consistent SQLite snapshot, validates its schema, full integrity
and foreign keys, encrypts/uploads it using restic over B2's S3 interface, downloads
and decrypts it, compares SHA-256 and row counts, and checks repository integrity.
Only after these checks pass does retention prune old snapshots. It keeps seven daily
and four weekly recovery points; these sets can overlap. B2 deletes hidden versions
under our `cinema-pilot-v1/` prefix after one day. Other prefixes are untouched.

The job runs as `cinema-pilot` with systemd hardening, a 768 MiB memory limit,
50% CPU quota, a 20-minute service timeout and a single-run file lock. Individual
restic operations time out after five minutes. There is no immediate automatic retry;
an operator can rerun a failed job, and the next daily run also retries.

```sh
sudo cinema-pilot-health
sudo systemctl list-timers cinema-offsite-backup.timer
sudo systemctl start cinema-offsite-backup.service
sudo journalctl -u cinema-offsite-backup.service -n 20 --no-pager
```

Health includes the last verified cloud restore, failure phase and bucket storage.
The existing 15-minute Telegram evaluator alerts on failed, stuck (>20 minutes),
missing or stale (>26 hours) backups and storage warnings, and reports recovery.
The independent external heartbeat still handles loss of the VPS itself.

## Secrets and recovery

Root-only files in `/etc/warsaw-cinema/`:

- `offsite-backup.json`: bucket-scoped B2 application credentials.
- `offsite-restic-password`: separate encryption password.
- `offsite-recovery.json`: recovery bundle containing both plus repository location.

Systemd passes the first two files through `LoadCredential`; credentials and raw
provider/restic error responses are never logged. The recovery bundle is also saved
outside Git at `C:\Users\Kacper Szatkowski\.cinema-backup-recovery\offsite-recovery.json`.
Its directory permits only the Windows owner and SYSTEM. This JSON contains secrets
in plaintext protected by filesystem permissions: keep a further copy in a password
manager or other encrypted storage. Losing the restic password makes backups unusable.

Recovery procedure on a trusted machine:

1. Install restic and the matching application release from Git/build artifacts.
2. Read the protected recovery bundle privately. Supply repository and B2 credentials
   through environment variables and the restic password through a protected password
   file; never paste values into chat, command history or logs.
3. Use `restic snapshots`, then `restic dump <snapshot-id>
   /var/lib/cinema-offsite/cinema.sqlite3` redirected to a new protected file.
4. Validate SHA-256 against the saved run status where available, full SQLite integrity,
   foreign keys and application schema. Test read-only API access against this copy.
5. Only during an approved recovery window, stop writers and replace the live database
   using the validated copy. Recreate service credentials separately, then restart and
   check health, refreshes and durable jobs. Never start a second collector against a
   restored clone during a drill.

Backups contain the application database, including observation/job and alert state.
They do not contain the whole host, Telegram/heartbeat credentials, SSH keys or code.
Full replacement-server recovery and external outage exercises remain separate work.

## Cost bounds

Snapshot size is capped at 128 MiB pending review. Bucket storage, including hidden
versions, warns at 1 GiB. Uploads stop if current storage plus a conservative 256 MiB
reserve reaches 2 GiB. These are application guardrails, not a provider billing cap:
other buckets, concurrent uploads, requests and download traffic are not capped here.

B2's checked allowance is 10 GB free storage; downloads have a separate allowance.
Daily verification downloads data, so free storage does not guarantee zero total cost.
Current backups are tiny (~0.20 MiB stored for the first run). Review usage as history
grows and configure provider billing alerts if a payment method is added.

Sources: [B2 pricing](https://www.backblaze.com/cloud-storage/pricing),
[restic B2/S3 setup and lifecycle](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html),
[restic retention](https://restic.readthedocs.io/en/stable/060_forget.html).

## September 30 cloud recovery evidence

First successful run: 15:24:59 UTC / 17:24:59 Warsaw.
Snapshot `269d385394f554d4f0fc9af4d0f6fdebfc7a21863eaf75c60bad2113cd4282a6`.

- SQLite snapshot: 1,208,320 bytes; B2 bucket including versions: 209,210 bytes.
- SHA-256: `098b0bf000662849b32e9e90267e4435eb49f441e4f947c635a6bb44e5453cd1`.
- Restored: 7 imports, 868 screening rows, 990 jobs, 381 seat observations.
- Automatic cloud download/decryption, full integrity, foreign keys, schema, checksum,
  row counts and restic repository check passed before retention.
- A second cloud download was transferred privately to the Windows PC. Its hash and
  integrity matched; the actual API returned HTTP 200 for readiness and screenings.
  The file hash stayed unchanged after those reads.
- Local drill artifacts: ignored `tmp/cloud-restore-20260930/`.
- Live collection remained healthy: 313/313 completed scheduled windows successful at
  17:25 Warsaw, no overdue jobs or active incidents. This is not a full 24-hour Arkadia trial.

Offline tests cover failed/corrupt restores preventing pruning, scope/privacy checks,
hidden-version accounting, lifecycle conflicts, budget stops and failure/recovery alerts.
The first unattended timer run is still pending; inspect its result the next day.
