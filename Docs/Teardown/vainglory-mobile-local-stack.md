# Mobile CE client against the local stack — 2026-09-05

## Result and boundary

**[Observed]** The installed Android **4.13.4 (147219)** client reached its
main menu and exposed a responsive **PLAY** flow against our own local
`server.platform.local_stack`. No APK, native library, or OBB was changed.
Guest/session RPCs occur internally even though this CE menu has no login UI.
PC menu behavior is not evidence of the target mobile client's UI requirements.

**[Observed]** PLAY → SOLO BOTS → 3V3 → VERY EASY issued `joinLobby` and stayed
on a loading panel. The configured answers contain no `joinLobby` handler;
the stub returns the configured generic `{"code":0,"returnValue":{}}`.
No hero selection, match entry, or gameplay was reached. This run proves
local menu access; it does not prove a working match server or PvP simulation.
The current blocker is the transition after `joinLobby`. Its required response,
any notification sequence, and the surviving client path to match entry remain
**[Unverified]**. Implementing a lobby is not yet an evidence-backed next step.

All game connections outside guest loopback were rejected for the game's UID
before launch. Tests involved only the operator's emulator and server.
Screenshots, request journals, and the answers snapshot remain outside the repo.

## Verified environment

| Field | Observed value |
|---|---|
| LDPlayer | `D:/LDPlayer/LDPlayer9/ldconsole.exe`, index `0` |
| Host ADB | `C:/Android/Sdk/platform-tools/adb.exe` |
| Chosen serial | `emulator-5554`; `127.0.0.1:5555` also appeared |
| Package | `com.superevilmegacorp.game` |
| Launcher | `com.superevilmegacorp.nuogameentry.NuoActivityLauncher` |
| Display | `1600x900` (`adb shell wm size`) |
| Game UID during this run | `10060`; rediscover with `dumpsys package` after reinstall |
| ADB shell / root | `uid=2000`; `su -c id` returned `uid=0` |
| Host HTTP / TLS | `127.0.0.1:8080` / `127.0.0.1:8443` |
| Host gateway / heartbeat listener | `127.0.0.1:7100` / `127.0.0.1:2112` |

## Recovery and routing that worked

Both ADB transports initially reported `device` while `shell id` timed out.
`ldconsole.exe reboot --index 0` restarted the emulator but left stale ADB
connections. Host `adb kill-server`, `adb start-server`, and
`adb connect 127.0.0.1:5555` restored responsive shell service. Always select
the serial explicitly and bound command timeouts; an online transport is not
proof that shell service works.

The recovered emulator had its original hosts file and no reverse mappings.
This run kept adbd unprivileged. It used **four high-port reverse mappings**,
with guest NAT handling ports 80 and 443:

```text
adb -s emulator-5554 reverse tcp:8080 tcp:8080
adb -s emulator-5554 reverse tcp:8443 tcp:8443
adb -s emulator-5554 reverse tcp:7100 tcp:7100
adb -s emulator-5554 reverse tcp:2112 tcp:2112
```

The following are **guest root commands**, passed through `adb shell su -c`
as one correctly quoted command string. They describe the installed rules;
do not repeatedly append duplicates. The UID is specific to this installation.

```sh
iptables -I OUTPUT 1 -m owner --uid-owner 10060 ! -d 127.0.0.0/8 -m comment --comment halcyon-local-only -j REJECT
ip6tables -I OUTPUT 1 -m owner --uid-owner 10060 ! -d ::1/128 -m comment --comment halcyon-local-only -j REJECT
iptables -t nat -I OUTPUT 1 -d 127.0.0.1 -p tcp --dport 80 -m comment --comment halcyon-local-route -j REDIRECT --to-ports 8080
iptables -t nat -I OUTPUT 1 -d 127.0.0.1 -p tcp --dport 443 -m comment --comment halcyon-local-route -j REDIRECT --to-ports 8443
```

Create `/data/local/tmp/halcyon-hosts-20260905` containing the original
localhost entries plus all seven names from
`server/platform/setup_hosts.ps1`, each mapped to `127.0.0.1`. Set mode 0644,
then bind it over `/system/etc/hosts` using guest root:

```sh
mount --bind /data/local/tmp/halcyon-hosts-20260905 /system/etc/hosts
```

Writing files through ADB stdin (`shell su -c 'cat > ...'`) worked in this run.
There was no system remount, block-device change, or `adb root` operation.
The earlier remount/root-service wedge is a reason to retain this tested route,
not a confirmed diagnosis of its underlying emulator bug.

## TLS trust was the first actual mobile blocker

The first launch reached
`http://preauth.superevilmegacorp.net/kindred/live/147219-status-redirect`.
The local server then logged `TLSV1_ALERT_UNKNOWN_CA`; the screenshot showed
**Unable to connect** and no platform RPC was recorded.

The existing local platform certificate is a self-signed CA with the required
hostname SANs. Its OpenSSL `subject_hash_old` was `41e9eb4e`. Android's CA
filename convention uses this old subject hash plus an index; see the
[AOSP certificate-store instructions](https://android.googlesource.com/platform/system/ca-certificates/+/refs/heads/android11-mainline-release/README.cacerts).
Compute the hash again if the certificate changes.

With the game force-stopped, guest root copied the existing system CA directory
into a new external overlay, added **only the public certificate** from host
`$TEMP/halcyon_stack/platform_cert.pem` as `41e9eb4e.0` (0644), set the directory
to 0755, and mounted the overlay:

```sh
mkdir /data/local/tmp/halcyon-cacerts-20260905
cp -a /system/etc/security/cacerts/. /data/local/tmp/halcyon-cacerts-20260905/
# Transfer the public certificate into that directory as 41e9eb4e.0.
chmod 644 /data/local/tmp/halcyon-cacerts-20260905/41e9eb4e.0
chmod 755 /data/local/tmp/halcyon-cacerts-20260905
mount --bind /data/local/tmp/halcyon-cacerts-20260905 /system/etc/security/cacerts
```

The existing CA files were preserved. No private key went into the guest.
After restarting the game, TLS and menu startup succeeded. The existing
`answers.json` was left unchanged: bootstrap body `rpc.kindred-live.net:8443`,
local guest/session replies, and the currently configured WebSocket notify
payload `{"friends":[]}`. These replies include a synthetic diagnostic skin
manifest from the PC investigation, not a recovered complete content catalog.

## Evidence

Captures are under `$TEMP/halcyon_stack/mobile-20260905/`:

- `launch.json`, `launch.png`, `launch-http_log.txt`: baseline offsets,
  first launch, and the certificate rejection.
- `trust-retry.json`, `trust-retry-later.png`, `trust-retry-rpc.jsonl`:
  successful restart, visible main menu, and platform requests.
- `play-menu.png`, `solo-menu.png`, `difficulty-menu.png`, `lobby-wait.png`:
  actual UI path and the lobby loading panel.
- `answers-used.json`, `summary.json`: exact external configuration snapshot
  and a summary without authentication material.

The recorded 262.3-second RPC window had one each of `getPlayerForGuestAccount`,
`startSessionForPlayer`, `getPlayerInfo`, `getSkinManifest`, `getTalentsData`,
`exitLobby`, and `joinLobby`, plus 135 `update` requests. There was no
`endSession` or repeated manifest request in that window. This is a bounded
observation, not a long-duration stability claim.

`joinLobby` supplied three parameters: an empty string, a JSON-encoded lobby
configuration string, and revision `147219`. The configuration selected
`lobby: solo_bots`, `difficulty: very_easy`, handle `Guest`, and social cosmetic
fields. The 3v3 choice was visible in the UI; no explicit map field was present
in this captured call. Do not invent a lobby response from this request alone.

## Revised next step — establish the match-entry exchange

The operator reports that current CE no longer exposes the original party/lobby
feature. Historically, SEMC's
[2020-07-01 CE update](https://www.vainglorygame.com/news/vainglory-community-edition-update-edtheshred/)
explicitly put further party development on hold while describing the game as
playable. That announcement is historical context, not a fresh verification of
every feature in the current service.

Do not equate the missing player-facing party feature with the internal RPC
named `joinLobby`. This client demonstrably sends that RPC for `solo_bots`;
the name alone establishes neither its reply schema nor a functioning party
system. The loading panel with our generic reply does not establish which
fields or events would advance it.

Existing Android observations include a successful match and a match socket
opening at game start (`vainglory-netcode-backend.md` §1–2). They establish that
a match-entry path existed in the observed client/service combination. They
do not supply decoded HTTPS platform replies, or prove that the same path is
reachable with our current synthetic session data.

The next bounded investigation should:

1. Check the existing successful-run artifacts for preserved platform results
   or client state around match entry. Treat TLS-only captures as an explicit
   missing source of reply bodies.
2. Use the sanctioned local runtime route to identify what the client consumes
   after the captured request, if accessible. Require a concrete field read,
   state transition, or accepted event before implementing that behavior.
   Do not resume the stopped broad binary-RE or codec-cracking campaigns.
3. Produce a documented exchange supported by evidence, or a precise list of
   missing inputs. If the stock path cannot be established, evaluate a deliberate
   client repack for direct local match entry as a separate, unverified option.

Acceptance for this investigation is an evidenced transition toward the local
match socket, or an explicit evidence gap. Hero selection and a restored lobby
are possible later milestones, not promised results of the current findings.

## Reset and rollback

Bind mounts and these guest firewall rules are temporary for this emulator
boot. Reboot removes them; adbd/server restarts can also remove reverse mappings.
For an explicit rollback, force-stop the game, unmount the hosts and CA overlays,
delete only these exact tagged firewall rules with `-D` instead of `-I ... 1`,
and remove each of the four reverse mappings with `adb reverse --remove`.
The copied files can remain inert under `/data/local/tmp`; no filesystem
deletion is needed to restore routing or trust. Restore the local-only rules
before any subsequent active local-server test.
