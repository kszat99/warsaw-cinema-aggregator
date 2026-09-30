# VPS read-only security review — September 30, 2026

Observed around 21:32 Warsaw. No VPS settings were changed, no services restarted,
and no packages installed. This is a configuration review, not a compromise assessment
or penetration test.

## Findings, in priority order

1. **Unnecessary public listener:** TCP 631 (CUPS printing) listens on all IPv4 and
   IPv6 interfaces. A single external IPv4 TCP connection from the development PC
   succeeded. The process belongs to snap.cups.cupsd.service, executable
   /snap/cups/1262/sbin/cupsd. Configuration has Port 631 and WebInterface Yes.
   Access rules exist; reachable TCP does not prove unauthenticated administration.
   Review snap dependencies before disabling it, or restrict it to local access.
2. **No host firewall:** UFW inactive; nft ruleset empty; IPv4/IPv6 iptables INPUT,
   FORWARD and OUTPUT policies ACCEPT. Provider firewall settings were not inspected.
   Plan default-deny inbound with explicit SSH allowance, IPv4 and IPv6, existing
   session retained and a second successful login verified before closing it.
3. **SSH passwords remain enabled:** public-key authentication works, but password
   authentication is also allowed. Root password login is prohibited; root key login
   remains permitted. Validate owner key login and OVH recovery-console access before
   changing authentication. Consider key-only SSH and disabling direct root login.
4. **Updates need a reboot:** running kernel 6.8.0-136; reboot-required lists
   linux-image-6.8.0-142-generic, linux-base and libc6. Automatic security-update
   timers are enabled/active and today's log says all upgrades installed. Cached apt
   listing shows none pending; package indexes were not refreshed during this review.
   Plan a maintenance reboot outside seat-check windows, not an immediate restart.
5. **Local data permissions broader than intended:** /var/lib/cinema-pilot is 0755,
   database 0644, so other local users could read it. This does not expose SQLite over
   the network. Shared service units default StateDirectoryMode to 0755 despite
   UMask=0077; correct the unit setting as well as current permissions in a later fix.

## Positive controls verified

- Main cinema services use cinema-pilot, a nologin account with no sudo permission.
- NoNewPrivileges, ProtectSystem=strict, ProtectHome, PrivateTmp and memory limits
  are enabled for collection, refresh, alerts and offsite backup.
- All files under /etc/warsaw-cinema are root-owned 0600, including recovery material.
  Contents were not printed.
- SSH directory is 0700; authorized_keys is 0600.
- Application installation is root-owned.
- No public HTTP/API or database listener observed. Public TCP listeners were 22 and
  631; DNS listeners were loopback-only.
- Seat worker and refresh/alert/offsite timers stayed active throughout the review.

## Next work (not performed)

Address unnecessary printing exposure and establish a carefully staged firewall.
Then tighten state-directory permissions and SSH after verifying recovery access.
Schedule a maintenance reboot. IPv6 external reachability and OVH perimeter settings
need separate validation. Do not infer a security incident from these findings.
