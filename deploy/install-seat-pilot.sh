#!/bin/sh
# Run as root with a directory containing the reviewed wheel, requirements and units.
set -eu
upload=$(realpath "$1")
test -f "$upload/warsaw_cinema_aggregator-0.1.0-py3-none-any.whl"
test -f "$upload/requirements.txt"
if ! command -v sqlite3 >/dev/null 2>&1; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq sqlite3
fi
id cinema-pilot >/dev/null 2>&1 || useradd --system --home-dir /var/lib/cinema-pilot --shell /usr/sbin/nologin cinema-pilot
install -d -m 0755 /opt/cinema-pilot
install -d -m 0700 -o cinema-pilot -g cinema-pilot /var/lib/cinema-pilot
if [ -f /var/lib/cinema-pilot/cinema.sqlite3 ]; then
    echo 'Existing pilot database detected: use the documented backed-up update procedure.' >&2
    exit 1
fi
python3 -m venv /opt/cinema-pilot/.venv
/opt/cinema-pilot/.venv/bin/python -m pip install --require-hashes -r "$upload/requirements.txt"
/opt/cinema-pilot/.venv/bin/python -m pip install --no-deps "$upload/warsaw_cinema_aggregator-0.1.0-py3-none-any.whl"
sudo -u cinema-pilot /opt/cinema-pilot/.venv/bin/python -m cinema_agg.server.data --database /var/lib/cinema-pilot/cinema.sqlite3 migrate
install -m 0644 "$upload"/cinema-*.service "$upload"/cinema-*.timer /etc/systemd/system/
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/cinema-seat-pilot.service /etc/systemd/system/cinema-pilot-refresh.service /etc/systemd/system/cinema-pilot-refresh.timer /etc/systemd/system/cinema-pilot-backup.service /etc/systemd/system/cinema-pilot-backup.timer
install -m 0755 "$upload/cinema-pilot-status" /usr/local/bin/cinema-pilot-status
install -m 0755 "$upload/cinema-pilot-health" /usr/local/bin/cinema-pilot-health
echo 'Installed, migrated and verified. Services are not enabled yet.'
