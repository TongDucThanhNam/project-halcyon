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

The external implementation brief has a focused review in
`vainglory-implementation-brief-review.md`. It records source-backed
`queryPendingMatch`/`update` field leads from VGReborn and separates them from
unverified schemas and obsolete PC recommendations. Open it when using those
leads; they have not yet been validated against this mobile client's consumer.

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

## Match-entry exchange verified end-to-end (2026-09-06)

Running investigation (§143) closed on the platform tier. With
`server/platform/local_stack.py` + hot-reloaded `answers.json` (run dir
`$TEMP/halcyon_stack/`, artifacts `m2-probe*.png`, journal `rpc.jsonl`):

**The verified exchange (client 4.13.4 CE, Solo Bots 5v5):**

1. `joinLobby` reply must ack the queue: `{"code":0,"returnValue":
   {"state":"pending_auto","numPlayers":6}}`. An empty `returnValue:{}` is
   never enough — the client just spins in `update` polls forever.
2. `update` is the FSM driver. Verified state chain (string table
   0x1af126d–0x1af12e8, parser 0x00dbebfc–0x00dbef10):
   `menus→1, pending_auto→2, pending_custom→3, matched_partners→4,
   match_pending→5, playing→6 (+host/port/proxy_host/proxy_port)`,
   plus `spectating`/`post_match`. `matched_partners` is a real state, not a
   payload variant — it is the only state that also parses
   `numQueuedEntries` (int → ctx+0x108). **`match_pending` sent directly
   while queued is ignored** (probe I, 255 polls, no reaction).
3. `update.state="matched_partners"` + `numQueuedEntries` → the client fires
   `queryPendingMatch` (params `[""]`, ~1/s retry loop) and renders the
   MATCH FOUND / ACCEPT / DECLINE screen. This is the checkpoint trigger
   the session goal asked for.
4. `queryPendingMatch` reply shape (handler 0x00da7e88; key lookups are
   `{ptr,len,len|0x100000}`): `returnValue` must be an object with
   `code:int →+0x60`, `matchId:string →+0x28`, `ttl:float →+0x40`,
   `isValid:bool →+0x58`, `responses:[{playerUUID:string, response:int,
   acceptDelay:float}] →+0x48`. With `isValid:true` + a self entry
   `response:1`, the client marks the local player accepted (green icon).
5. Acceptance auto-advances (solo bots): the client sent `acceptMatch`
   unprompted once the FSM ran menus→pending_auto→matched_partners with a
   synced `matchId` and a valid qPM reply. (In probe K, with a stale
   `matchId` and a mid-session FSM it never fired.)
6. `update.state="playing"` with `host`/`port` → the client opens the match
   TCP connection to that address (adb-reversed gateway) and sends the
   §15.1 plaintext route request. Gateway log: `routed to backend
   '127.0.0.1'`. **acceptMatch's reply was never consumed** — the client
   connects purely from the `playing` update state.

**Platform answers that work** (all in `$TEMP/halcyon_stack/answers.json`):
session bootstrap (getPlayerForGuestAccount/startSessionForPlayer) unchanged;
`joinLobby` = pending_auto ack; `update` = the state chain above (hot-flip
per stage); `queryPendingMatch` = isValid:true + self roster;
`acceptMatch` = session-bootstrap copy + `pingHostPortInfo:[{host,port,
site,region}]` (shape from bootstrap parser 0x00d9f7c0–0x00d9fc4c — the
array elements parse `host`, `port`, `site`, `region`).

**T3 blocker (new, precisely bounded):** after routing, the real client
sends **nothing** on the match socket (no PLAYER_UUID(1000), contrary to
the phase-0 stub's assumption) and EOFs/aborts after ~30 s, retrying ~11×,
then surfaces "Is your Wi-Fi still working?". Server-first single frames
(GAME_SETUP 1001 or PLAYER_UUID 1000, encrypted under candidate keys
matchId and JWT-sessionId) produced zero client reaction.

Key-derivation RE (clean `libGameKindred.so`, 45,062,040 B): salt constant
at 0x1ac8e97; `0x00be2540` = `MD5(SALT‖id) → Blowfish::SetKey16` into
global 0x304b238; `0x00be262c` = update-key-if-changed (cache string at
0x304b220), tail-called from `0x008195f8` which feeds
`<session-singleton via 0xd829e0>()->+0xa8` — the match-key string lives
at session offset 0xa8. The unresolved question is exactly one: **which
write fills session+0xa8** (and what the client waits for before its c2s
1000 — §15.5's s2c 104/752/1,616 B handshake frames from the real capture
are the likely missing opener burst). Next bounded step: locate the
session+0xa8 writer and decode the s2c handshake frames from the existing
corpus, then replay that exact burst as the server-first opener.

## Post-route handshake closed (2026-09-06)

This section supersedes the T3 blocker paragraph above. The client now
speaks first, on our stack, with the real key. Capture payload artifacts
stay outside the repo (`$TEMP/halcyon_stack/`: `x1-*.png`, `x2-menu.png`,
`gateway_log.txt` windows 10:06–10:13, `answers.json` rows).

**1. The missing input was the gateway route-ack.** The real gateway
answers the §15.1 plaintext route request with `[u16 BE 3][00 06 00]`
~0.2 s later; the client sends its encrypted c2s 1000 ~1 ms after that.
Without the ack the client sits silent forever — every earlier
"client never speaks" observation reduced to this one missing frame.
Implemented in `server/wire.py` (`ROUTE_ACK_BODY`) and `server/gateway.py`.

**2. The encryption-key input is the `playing` update's `matchId` field.**
A/B on this client, same session, only `answers.json`'s `update` row
changed: `playing` payload without `matchId` → the client keys
`MD5(SALT‖"")` (session-string ctor default; log
`key candidate matched: '<empty string>'`); with
`"matchId": "00000000-…-6666"` in the payload → the client keys
`MD5(SALT‖matchId)`, the same key the vgfull.pcap capture decodes with.
This closes the static-RE question "which write fills session+0xa8"
operationally. The c2s 1000 payload is the client's session id string
(JWT in our flow; a UUID in the real capture) — a different field from
the key input.

**3. The server must adopt the client's key, not assume it.**
`server/match_server.py::_adopt_key` tries matchId / empty string / JWT
sid on the client's first frame and keeps whichever decrypts into the
dispatch range (both variants occur depending on platform answers).

**4. Live-verified join exchange (client 4.13.4 CE, Solo Bots 5v5):**
route request → our ack → c2s 1000 (session uuid) → our opener burst
1001 GAME_SETUP + 1108 GAME_MODE + 1107 ×275 + 1113 snapshot (captured
payloads, pcap order) → **c2s 1112 (6 B) + 1131 (6 B)** → the client
leaves the menu and renders the match screen: team panels (blue/red) and
a countdown interpolating from our 1113 values (set 298.86 s, observed
ticking 4m28s → 4m6s across screenshots). The phase-0 "server-first"
assumption is dead: the client sends 1000 first, once the ack exists.

**5. The "~30 s EOF, ~11 retries" of the earlier blocker was our own
read timeout.** After 1112/1131 the client idles (no keepalives yet), a
30 s `conn.settimeout(30)` killed the join and drove a 30 s reconnect
loop (gateway_log 10:06–10:09). Raised to 300 s
(`server/match_server.py`); the connection then stays up. Keepalives
(op 0 every 2 s) only start in steady state, not during the pick phase.

**Still missing for a full join** (next gate, before §2's movement
slice): the client sends no 1118 (token pair), no 1123 build-select, no
keepalives, and the team panels stay empty — consistent with a missing
player roster (1006 PLAYER_INFO records / player entries in the 1113
snapshot). The client has no slot/team/hero binding to render hero
select. Then: entity-spawn opcode discovery (next-steps.md §2).

**Operational notes:** launch the stack with
`python -m server.platform.local_stack` from the repo root — running the
file as a script puts `server/platform/` on `sys.path` and shadows the
stdlib `platform` module (pycryptodome import crash). Server-side test
coverage: 26/26 (`python -m unittest discover -s server/test`), including
auto-key adoption for both observed client key variants.
