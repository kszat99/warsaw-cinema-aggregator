from cinema_agg.server.alerts import format_alert_message, format_resolved_message
from cinema_agg.server.pilot_health import refresh_explanation


def evidence():
    return {
        "issues": ["schedule_refresh_stale", "latest_refresh_failed_or_partial"],
        "refresh": {
            "last_success_age_minutes": 450,
            "last_success_at_ms": 1790770378216,
            "latest": {"status": "partial", "finished_at_ms": 1790791965798},
            "scopes": [
                {
                    "cinema_id": "1074",
                    "target_date": "2026-09-30",
                    "outcome": "count_drop_quarantined",
                    "count": 2,
                    "previous_count": 52,
                    "previous_upcoming": 15,
                    "fetched_upcoming": 2,
                    "error_type": None,
                },
                {
                    "cinema_id": "kinoteka",
                    "target_date": "2026-09-30",
                    "outcome": "accepted",
                    "count": 33,
                    "previous_count": 33,
                },
            ],
        },
        "seats": {"successful_jobs": 369, "windows_finished": 369},
        "worker": {"heartbeat_age_seconds": 4.5},
    }


def test_refresh_alert_explains_cause_impact_and_age_relationship():
    data = evidence()
    for issue in data["issues"]:
        message = format_alert_message(issue, data)
        assert "Cinema City Arkadia | 2026-09-30" in message
        assert "previously upcoming 15, returned upcoming 2" in message
        assert "previous schedule retained" in message
        assert "1/2" in message
        assert "369/369" in message
        assert "does not establish a second outage" in message
        assert "historical errors may remain" not in message
    assert "Legacy comparison" not in "\n".join(refresh_explanation(data))


def test_legacy_and_recovery_messages_are_truthful():
    data = evidence()
    data["refresh"]["scopes"][0]["previous_upcoming"] = None
    assert "Legacy comparison used full-day totals" in format_alert_message(
        "latest_refresh_failed_or_partial", data
    )
    data["refresh"]["latest"]["status"] = "complete"
    message = format_resolved_message("schedule_refresh_stale", data)
    assert "Latest run: complete" in message
    assert "historical" not in message
