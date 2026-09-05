# Vainglory netcode and backend — measured, not probed

Spun out of the map leaf on 2026-09-03 (section number **§14 inherited** from
the monolith era) and merged with the backend-liveness report previously kept
outside the repository (`D:/Downloads/vg/FINDINGS.md`, 2026-07-31).

Boundary (binding): everything here is **passive observation of the user's
own devices** plus static analysis of released files and public DNS /
Certificate-Transparency records. No packet was crafted, no connection was
decoded, no TLS was terminated, no service was scanned. Endpoint identity
comes only from resolving public hostnames and reverse-DNS of observed IPs.

## 1. Backend topology (Observed)

Discovery chain: `Startup.ini` in the APK/PC build declares the bootstrap
`preauth.superevilmegacorp.net` (PC build uses `preauth.superevil.net` —
same IP), which answers every path with a 25-byte body
`rpc.kindred-live.net:443`. The rest of the names came from Certificate
Transparency on `kindred-live.net`, not from traffic capture.

| Service | Host | Evidence |
|---|---|---|
| Bootstrap / preauth | `preauth.superevilmegacorp.net` (and `.superevil.net`) | HTTP 200 → `rpc.kindred-live.net:443`; both alive and repointed at the community backend |
| Platform RPC | `rpc.kindred-live.net` → 34.160.208.252:443 (×2 connections) | JSONRpc over HTTPS (binary strings); held from menu through match |
| CDN / assets | `static.kindred-live.net` | GCS-backed, public object read |
| Game servers | `game-servers-{us-west1,europe-west1,asia-northeast1,asia-southeast1,southamerica-east1}.kindred-live.net` | resolve + valid TLS; GCP region identifiers |

Operator: **not SEMC** — a community-run stack ("VAINGLORY ∞" on the splash)
on Google Cloud. Timeline corroborated by an nginx `Last-Modified:
2022-09-19` on the relay, `kindred-live.net` registered 2022-10-20, and the
147219 build dating to September 2022.

Ports observed from live clients (all Google Cloud,
`*.bc.googleusercontent.com`):

| Remote | Port | Seen | Reading |
|---|---|---|---|
| 34.160.58.175 | 80 | PC client | preauth HTTP |
| 34.160.208.252 | 443 | PC + Android clients | rpc.kindred-live.net |
| 34.105.13.248 | 7089 | PC client | raw protocol, no HTTP/TLS — game/match server |
| 136.66.77.13 | 7095 | Android client, **opens exactly at match start, survives the match** | match server |
| 35.233.231.76 | 2112 | PC + Android, persistent from menu | session/relay (nginx banner on PC) |

Legacy SEMC-era hosts (`platform.superevilmegacorp.net`,
`gamefeeds.superevilmegacorp.net`, `5v5.vainglorygame.com`, …) are
NXDOMAIN; `www.vainglorygame.com` still resolves but is not on the game
path.

## 2. Traffic signature — three windows, one session (Observed, 2026-09-03)

Method: `wlan0` counters from `/proc/net/dev` sampled at 0.4 s on the rooted
emulator (runtime leaf §6); menu baseline 40 samples, in-match 120 s window
(274 rate samples), plus a 25 s window with the hero actively driven via adb
taps. No payload inspection at any point.

| Window | rx median | tx median | Character |
|---|---|---|---|
| Menu (baseline) | 892 B/s | 2,827 B/s | keepalive + store chatter |
| In match, hero idle | 4,676 B/s (p90 6,448; max 40,757) | 4,101 B/s (p90 4,719) | continuous both ways |
| In match, hero driven | 4,697 B/s (unchanged) | 5,166 B/s (+26 %) | tx scales with input |

Three load-bearing observations:

1. **The stream never sleeps.** Across 274 in-match intervals neither rx nor
   tx dropped below 50 B/s once — a continuous bidirectional heartbeat +
   state channel, not bursty snapshot delivery.
2. **Movement costs uplink, not downlink.** Driving the hero raised tx 26 %
   while rx stayed flat. That is the signature of a *client-streams-input*
   model (orders/pings/aim up; sparse events down) and against a
   *server-simulated-snapshot* model, where downlink would scale with world
   motion. Consistent with the determinism-first design: the authoritative
   simulation is cheap to describe, so events stay tiny.
3. **One telemetry burst per match.** A single tx spike of 1.0–1.6 MB/s for
   ~1.2 s (t≈41 s, total ≈2–3 MB) with no matching rx — consistent with the
   `DispatchQueue_PacketRecorder` flushing a batch (replay/telemetry
   upload) [Inferred — payload opaque by design].

rx did creep from 4,094 (first 30 s) to 4,978 B/s (last 30 s) as the match
developed — more entities/events, still trivially small.

**Superseded in part (2026-09-03, protocol leaf §15.5):** these are
interface-level counters — they include adb traffic and per-packet
overhead on the same NIC, so the absolute numbers are inflated. The
payload-level truth from a full-match capture: ≈2.6 KB/s downstream,
≈6 B/s upstream. The *relative* signature (tx scales with input, rx does
not; one continuous stream, never silent) is confirmed and refined: the
client sends exactly one 8–16 B frame per touch action.

## 3. Transport facts from binary strings (Observed)

From `libGameKindred.so` (stripped; vocabulary only, no disassembly):

- `TCP_NODELAY` — Nagle disabled on the game socket; small writes go out
  immediately. The single cheapest "feels instant" decision.
- Custom packet vocabulary: channel-based send with ACK/re-ACK tracking and
  sequence concepts — a hand-rolled reliability layer letting the sim
  multiplex channels with different needs over one connection.
- `DispatchQueue_PacketRecorder` + `Game_Replay` — every match can be
  recorded and replayed from the packet stream, which only works if the
  protocol is deterministic-event-shaped rather than snapshot-shaped.
- GCD-style serial queues (`__Render_Serial_Queue`, `__Update_Serial_Queue`,
  `__Main_OS_Serial_Queue`, `DispatchQueue_AnimSample/Composite/FogOfWar/
  PacketRecorder/ParticleFX/RenderEval`) — the frame is a pipeline of
  dependent serial stages, not a monolithic main loop.
- Honest absence: no tick/lockstep/snapshot vocabulary anywhere in strings.
  Absence of vocabulary is weak evidence, but everything *present* is
  coherent with event-stream-over-TCP and nothing supports snapshot
  streaming.

## 4. Why this feels smooth since 2012 (engineering synthesis)

The measurements close the loop with `vainglory-movement-anatomy.md`:
Vainglory's smoothness is not bandwidth or graphics — a full match carries
≈21 kbps of payload downstream and single bytes of input upstream
(protocol leaf §15.5), trivial by any standard. It is an architecture:

> a deterministic, fixed-tick simulation where clients stream tiny input
> intents up a Nagle-off reliable channel, receive tiny deterministic events
> back, replay them through a pipelined frame (input → sim → anim-sample →
> composite → render), and mask latency with prediction + dedicated
> locomotion blends (`run_start`, arrival radius, turn-rate-limited
> rotation).

Everything expensive is decided locally and identically on every machine;
the network only ships the decisions. That is exactly the determinism
boundary Veilbound already enforces (`AGENTS.md` hard boundary 1), which is
why the transfer cost is low. The operational lesson for Veilbound's future
net slice: measure your own traffic windows the same way before choosing
between input-stream and snapshot — the answer is observable in the rx/tx
symmetry, no protocol knowledge required.

## Boundary and what changed (2026-09-03)

At the time §1–§4 were written, the project boundary forbade packet
decoding; everything above was reproducible from counters, DNS and strings
alone — and that was enough to characterise the architecture. On
2026-09-03 the user explicitly unlocked the boundary (own-device capture
and decode sanctioned; the retained line is read-only on the wire — no
probing of their servers, no crafted/injected packets, no TLS
interception). The wire has since been captured and decoded to the frame
layer; the results, the correction of §2's absolute numbers and the
capture playbook live in `vainglory-protocol-wire.md` (§15).
