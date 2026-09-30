import json
from pathlib import Path

import httpx
import pytest

from cinema_agg.server.database import migrate
from cinema_agg.server.offsite import backup_and_verify, health, STOP_STORAGE
from cinema_agg.server.offsite_b2 import B2, PREFIX


class Remote:
    def __init__(self, size=0):
        self.size = size

    def check_lifecycle(self):
        pass

    def stored_bytes(self):
        return self.size


class Restic:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def run(self, *args, output=None):
        self.calls.append(args[0])
        if args[0] == self.fail:
            raise RuntimeError("simulated")
        if args[0] == "backup":
            self.data = Path(args[-1]).read_bytes()
            return b'{"message_type":"summary","snapshot_id":"1234abcd"}'
        if args[0] == "dump":
            output.write(b"corrupt" if self.fail == "corrupt" else self.data)
        return b"{}"


def test_round_trip_before_retention(tmp_path):
    source = tmp_path / "live.sqlite3"
    migrate(source)
    worker = Restic()
    state = {}
    backup_and_verify(source, tmp_path / "stage", Remote(), worker, state)
    assert worker.calls == ["backup", "dump", "check", "forget"]
    assert state["outcome"] == "success"
    assert state["restored_counts"]["seat_observations"] == 0
    assert not (tmp_path / "stage" / "cinema.sqlite3").exists()
    assert source.exists()


@pytest.mark.parametrize("failure", ["backup", "dump", "corrupt", "check"])
def test_failed_upload_or_restore_never_prunes(tmp_path, failure):
    source = tmp_path / "live.sqlite3"
    migrate(source)
    worker = Restic(failure)
    with pytest.raises((RuntimeError, ValueError)):
        backup_and_verify(source, tmp_path / "stage", Remote(), worker, {})
    assert "forget" not in worker.calls
    assert source.exists()


def test_storage_stop_prevents_upload(tmp_path):
    worker = Restic()
    with pytest.raises(ValueError):
        backup_and_verify(
            tmp_path / "missing", tmp_path / "stage", Remote(STOP_STORAGE), worker, {}
        )
    assert not worker.calls


def test_offsite_health_failure_stale_and_recovery(tmp_path):
    db = tmp_path / "live.sqlite3"
    assert health(db, 1000)["status"] == "not_configured"
    (tmp_path / "offsite-enabled").touch()
    assert health(db, 1000)["status"] == "missing_or_invalid"
    state = {
        "outcome": "failed",
        "started_ms": 100,
        "last_success_ms": 100,
        "phase": "upload",
    }
    target = tmp_path / "offsite-status.json"
    target.write_text(json.dumps(state))
    assert health(db, 1000)["status"] == "failed"
    state.update(outcome="running", last_failure_ms=200)
    target.write_text(json.dumps(state))
    assert health(db, 1000)["status"] == "failed"
    state["outcome"] = "success"
    state["last_success_ms"] = 300
    target.write_text(json.dumps(state))
    assert health(db, 1000)["status"] == "ok"
    assert health(db, 27 * 3600_000)["status"] == "stale"


def b2_client(*, origin="https://api001.backblazeb2.com", buckets=None, public=False):
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path.endswith("b2_authorize_account"):
            return httpx.Response(
                200,
                json={
                    "accountId": "account",
                    "authorizationToken": "test-token",
                    "apiInfo": {
                        "storageApi": {
                            "apiUrl": origin,
                            "s3ApiUrl": "https://s3.eu-central-003.backblazeb2.com",
                            "allowed": {
                                "buckets": buckets
                                if buckets is not None
                                else [{"id": "bucket", "name": "cinema-backups"}],
                                "capabilities": [
                                    "listFiles",
                                    "readFiles",
                                    "writeFiles",
                                    "deleteFiles",
                                ],
                            },
                        }
                    },
                },
            )
        assert request.url.host == "api001.backblazeb2.com"
        if request.url.path.endswith("b2_list_buckets"):
            return httpx.Response(
                200,
                json={
                    "buckets": [
                        {
                            "bucketId": "bucket",
                            "bucketType": "allPublic" if public else "allPrivate",
                            "revision": 1,
                            "lifecycleRules": [
                                {
                                    "fileNamePrefix": PREFIX,
                                    "daysFromHidingToDeleting": 1,
                                    "daysFromUploadingToHiding": None,
                                }
                            ],
                        }
                    ]
                },
            )
        payload = json.loads(request.content)
        if "startFileName" not in payload:
            return httpx.Response(
                200,
                json={
                    "files": [{"contentLength": 5}, {"contentLength": 7}],
                    "nextFileName": "next",
                    "nextFileId": "id2",
                },
            )
        return httpx.Response(
            200, json={"files": [{"contentLength": 9}], "nextFileName": None}
        )

    return httpx.Client(transport=httpx.MockTransport(handle)), calls


CONFIG = {
    "bucket_name": "cinema-backups",
    "application_key_id": "example-id",
    "application_key": "example-value",
}


def test_b2_scoped_private_pagination_includes_versions():
    client, calls = b2_client()
    with client:
        remote = B2(client, CONFIG)
        remote.check_lifecycle()
        assert remote.stored_bytes() == 21
    assert len(calls) == 4


@pytest.mark.parametrize(
    "options",
    [
        {"origin": "https://attacker.example"},
        {"buckets": []},
        {"buckets": [{"id": "1", "name": "other-bucket"}]},
    ],
)
def test_no_token_sent_to_unapproved_origin_or_scope(options):
    client, calls = b2_client(**options)
    with client, pytest.raises(ValueError):
        B2(client, CONFIG)
    assert len(calls) == 1


def test_public_bucket_rejected():
    client, _ = b2_client(public=True)
    with client, pytest.raises(ValueError):
        B2(client, CONFIG).check_lifecycle()


def test_lifecycle_scopes_change_to_repository_and_preserves_other_rules():
    client, _ = b2_client()
    with client:
        remote = B2(client, CONFIG)
        unrelated = {"fileNamePrefix": "other/", "daysFromHidingToDeleting": 10}
        rules = [unrelated]
        mutations = []
        remote.bucket = lambda: {"revision": 7, "lifecycleRules": list(rules)}

        def call(method, values):
            mutations.append((method, values))
            rules[:] = values["lifecycleRules"]
            return {}

        remote.call = call
        remote.check_lifecycle(configure=True)
        assert len(mutations) == 1 and rules[0] == unrelated
        assert rules[1]["fileNamePrefix"] == PREFIX
        assert mutations[0][1]["ifRevisionIs"] == 7
        rules[:] = [{"fileNamePrefix": "", "daysFromUploadingToHiding": 1}]
        with pytest.raises(ValueError):
            remote.check_lifecycle(configure=True)
        assert len(mutations) == 1


def test_backup_incident_and_recovery_delivery(engine, tmp_path, monkeypatch):
    from cinema_agg.server import alerts
    from cinema_agg.server.settings import Settings
    from test_seat_pilot import NOW

    data = {
        "issues": ["offsite_backup_attention"],
        "offsite_backup": {
            "status": "failed",
            "phase": "upload",
            "last_success_ms": NOW - 1000,
        },
    }
    monkeypatch.setattr(alerts, "report", lambda *a, **k: data)
    messages = []
    monkeypatch.setattr(
        alerts,
        "send_telegram",
        lambda msg, settings: (messages.append(msg) or True, None),
    )
    alerts.evaluate_alerts(tmp_path / "seats.sqlite3", NOW, Settings())
    assert "phase: upload" in messages[-1]
    data["issues"] = []
    data["offsite_backup"]["last_success_ms"] = NOW
    alerts.evaluate_alerts(tmp_path / "seats.sqlite3", NOW + 1000, Settings())
    assert "Last verified cloud upload/restore" in messages[-1]
    alerts.evaluate_alerts(tmp_path / "seats.sqlite3", NOW + 2000, Settings())
    assert len(messages) == 2


from test_seat_pilot import engine  # noqa: F401,E402
