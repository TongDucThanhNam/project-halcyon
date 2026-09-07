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

## Reverse-mapping failures seen live (2026-09-06)

Three distinct symptoms, all routing, all fixed without touching the server:

- **Black screens (~8 KB screenshots)** after an app relaunch: the adb
  server had restarted and dropped every reverse mapping — including the
  platform ports, so the menu RPC never reached the host. Re-add **all
  four** (`8080`, `8443`, plus the current gateway/heartbeat ports) and
  check `adb reverse --list`, not just `adb devices`.
- **"Unable to connect :-/"** with only the gateway/heartbeat mappings
  restored: the platform half (`8080`/`8443`) was still missing. The guest
  NAT redirects 80→8080 and 443→8443, so no direct 80/443 mappings exist —
  the set is exactly those four ports.
- **Gateway port drift**: with a stale elevated stack still holding
  7100/2112, the fresh stack serves 7102/2114 (ports advertised through the
  shared hot-reloaded `answers.json`). The reverse set must name the
  *current* gateway/heartbeat ports, and `adb reverse` must be re-run after
  every adb-server restart regardless of app state.

Also on this date: random native deaths with identical `libhoudini.so`
signatures (tombstones in `$TEMP/halcyon_stack/`) occur in menu phases with
the local server uninvolved — do not attribute client disappearances to our
bytes without checking `logcat -b events` for `am_crash` and comparing
tombstone signatures.

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

## Roster live validation failed (2026-09-06)

**[Observed]** Restarted the local stack with the working-tree roster
implementation (`python -B -u -m server.platform.local_stack`). Rechecked
UID 10060 IPv4/IPv6 local-only rules and existing ADB reverse mappings:
guest 7100 routes to host 7101, heartbeat 2112 to 2113; HTTP/TLS use
8080/8443. No remote backend was contacted.

The launcher initially remained blank; explicitly starting the installed
`com.superevilmegacorp.nuogameentry.NuoActivityGame` activity reached the
menu. Selected Solo Bots / 3v3 / Very Easy, then hot-stepped the existing
platform answers through pending_auto, matched_partners and playing.
The existing synthetic match-found reply displayed **5v5 Solo Bots** despite
the 3v3 menu selection; mode consistency remains an additional open issue.

Two joins (host log 10:59:50 and 11:00:01) adopted the expected match-id key,
received c2s 1000, logged c2s 1112 and 1131 (6 B each), and ended in EOF
approximately one second later. No 1118 echo, 1123 or 1137 was logged.
Neither connection reached the scheduled roster-dump log. The client
returned to its splash screen; Android crash logs show GL-thread SIGSEGV,
SEGV_MAPERR, null dereference at 0x10 for both corresponding game processes.
The native-translation backtraces do not identify a protocol field.
Guest clock timestamps differ from the host clock.

**[Observed discrepancy, cause unverified]** The identity presented in this
local c2s 1000 is a JWT prefix, not the corpus's 36-byte UUID. Both roster
builders retain only its first 36 bytes. The corpus UUID equality test
therefore does not establish correct identity binding for this live flow.
Do not assert this mismatch caused the crash without a controlled comparison.
Likewise, 1011 zero stats cannot explain a frame that was never sent in
these attempts. Isolate opener reconstruction, 1118 and early snapshots
before proceeding to entity-spawn work.

Artifacts remain outside the repo under `$TEMP/halcyon_stack/`:
`roster-*.png` (menu steps and post-join splash),
`roster-client-crash.txt`, `roster-live-gateway.txt`,
`roster-stack-stdout.txt`, `roster-stack-stderr.txt`, and the pre-run
configuration backup `roster-answers-before.json`.
The game was force-stopped to end the crash loop; `answers.json` now returns
`update.state="menus"`. The updated stack remains running and local-only
routing remains installed. No client files were changed.

Checks: 41/41 tests passed with ResourceWarning treated as errors and
bytecode writes disabled. This is a failed **live acceptance** result,
not a failing unit test and not a closed roster gate.

## Hero-selection crash isolated and fixed (2026-09-06)

**[Observed]** Used an external probe harness
`$TEMP/halcyon_stack/roster_probe_stack.py` with the current setup/catalog
builders and controlled snapshot variants. All game routing remained local.
The script is a diagnostic harness, not the production launch command.

| Host time | Variant | Result |
|---|---|---|
| 11:13:57 | HEAD snapshot shape, rebuilt 1001/1108, no 1118/stream | Countdown and empty panels, alive until deliberate stop |
| 11:14:26 | New populated snapshot alone | EOF/crash about one second later |
| 11:15:15 | New snapshot, IDs=`ffff`, hashes=`10c2bad9` | Hero picker, Guest + two allied bot names, unsolicited c2s 1118 |
| 11:16:14 | Change **only IDs** to `ffff`, retain derived hashes | Hero picker; choosing Adagio and locking emits 1118 and 1123 |
| 11:17:39 | Change **only hashes**, retain derived IDs | EOF/crash |
| 11:18:17 | Unpicked snapshot; echo client 1118 and update local hero | Guest portrait populated, selectable hero changes acknowledged |
| 11:24:51 | Corrected normal `server.platform.local_stack` | Hero picker and portrait; Adagio selected 11:25:26, lock received 11:25:28; connection survives |

The immediate crash trigger is the generated value in the **hero-selection
ID field**, previously mislabelled player ID. Initial slots need `ffff`.
This comparison did not need to alter the JWT identity or game mode; those
were not the necessary correction for the observed crash.

**Selection meaning/direction:** c2s 1118 arrives with no prior s2c 1118.
Amael selected = `(925, 0x2fd7245d)`; clicking Adagio changes it to
`(244, 0xf9fd7554)`. These values are stable across the probe and normal
stack. S2c acknowledges the chosen pair. The client sends 1123 (6 B zeros)
on Lock In. The earlier "server-issued player credential echoed by client"
claim is disproved. A single snapshot was sufficient to display a usable
picker, so streaming was not the missing prerequisite either.

**Layout:** the corrected 8-byte countdown / 16 slot records / 6-byte
padding builder matches every byte of the first corpus snapshot. Each
record includes its own 8-byte prefix (occupied, zero-based index, flags,
marker). Field regions place the identity in 64 bytes; the corpus's UUID
only used 36. The implementation now preserves the live identity prefix.
Precise offsets are in the wire leaf §15.8.

**Remaining gate:** after lock the client remains connected on a dark
waiting overlay; the corrected server does not send placeholder gameplay
blocks. No live 1119/1137 or game world was observed. Bot choices and the
post-lock transition, valid hero initialization and full selection ID/hash
validation are open. This is hero-selection acceptance, not gameplay or
complete join acceptance.

External evidence: `probe-baseline.png`, `probe-new-only.png`,
`probe-prepid.png`, `probe-select-adagio.png`, `probe-lock-adagio.png`,
`probe-interactive*.png`, `selection-final-initial.png`,
`selection-final-adagio.png`, `selection-final-locked.png`,
`selection-stack-stdout.txt`, `selection-stack-stderr.txt`, and the matching
host windows in `gateway_log.txt`, all under `$TEMP/halcyon_stack/`.
`roster_compare.py` reproduces opener equality and exposed the missing slot
prefix bytes. Repository regression tests now check full initial-snapshot
equality and the client-initiated selection flow (44/44 green).

Handoff state: normal stack restarted again at host 11:30 with serialized
gateway logging (prevents reader/writer log-line loss). The emulator is
left at the working, unlocked hero picker (`selection-ready.png`);
`answers.json` returns `playing` with the same local match route. The
probe harness is stopped. Logs for this launch are
`selection-ready-stdout.txt` / `selection-ready-stderr.txt`; the latter
is empty. All routing remains local-only.

## Post-lock world-init served (2026-09-06, evening) — live run pending

The "remaining gate" above is now implemented from the corpus: an
ACK-precise trace of vgfull.pcap (tooling outside the repo,
`$TEMP/vg_max/trace_after_lock.py`) decoded the full lock → loading →
world-init exchange, and the normal stack now serves it: 1123 echo,
1119 commit echo (the committed hash replaces the clicked one), bot hero
assignment with the 8× locked-snapshot burst at 7.0 s, ~10 Hz countdown to
0, final 1006×6 + 1132, and the world dump (1135, 1006×6, 1105,
1011+1162×7 reverse, 1055×6, 1134/1137 echoes, 1116 ~1 Hz) once the client
reports 1134/1137 — plus a 40 s dump fallback for clients that skip the
tutorial-build flow. Sequence and field corrections are recorded in the
wire leaf §15.8 "Post-lock world-init exchange closed"; the state machine
lives in `server/match_server.py`.

Corpus-side verification: 56/56 tests including byte-equality of the
all-locked final 1113 and the final 1006 group against vgfull.pcap. Live
verification is still outstanding. Next run's checklist, in order:

1. Lock In → the client should leave the dark overlay into the locked
   countdown (portraits populate, ~7 s).
2. Loading screen (~23 s in the corpus) → c2s 1134 + 1137 in the local
   match log.
3. Map render. If it stays black: first suspect is the missing 1087
   entity-allocation batch, then zero 1011 stat runs, then the derived
   1055 tags — each has a measured corpus counterpart to rebuild from.

## LAN Exposure and Remote Client Configuration (Slice 7, 2026-09-07)

To allow physical devices or separate emulators on the same local area network (LAN) to join matches together:

### 1. Host side (Server machine)
- The stack listens on `0.0.0.0` by default (`--bind-host 0.0.0.0`), accepting connections from loopback as well as the host's LAN adapter (e.g. `192.168.1.3`).
- Inbound Windows Firewall rules for TCP ports `80, 443, 8080, 8443, 7100-7102, 2112-2114` can be installed via:
  ```powershell
  powershell -ExecutionPolicy Bypass -File server/platform/setup_firewall.ps1
  ```
- The gateway IP announced to clients during `joinLobby` is configured via `--match-host <LAN_IP>`:
  ```powershell
  python -m server.platform.live_up --match-host 192.168.1.3
  ```

### 2. Guest side on remote friend machine
Run the idempotent setup script pointing to the host machine's LAN IP:
```sh
python -m server.platform.guest_setup --host 192.168.1.3
```
This single command automatically:
1. Generates `/data/local/tmp/halcyon-hosts-20260905` mapping `rpc.kindred-live.net`, `platform.superevil.net`, etc. to `192.168.1.3`.
2. Clones system CA certificates and installs the Halcyon root certificate `41e9eb4e.0`.
3. Bind-mounts the overlays over `/system/etc/hosts` and `/system/etc/security/cacerts`.
4. Configures iptables firewall: permits traffic to `192.168.1.3`, while strictly rejecting any non-loopback traffic to prevent leakage to SEMC public servers.
5. Verifies guest DNS resolution: `rpc.kindred-live.net` -> `192.168.1.3`.

