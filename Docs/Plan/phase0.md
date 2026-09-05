# Phase 0 — T2 wire layer, corpus-validated

Mission (from `AGENTS.md`): build a faithful, self-hosted PvP Vainglory
private server. Phase 0 is the **provable warm-up**: stand up a running local
gateway + match-server stub that speaks the decoded wire protocol end-to-end,
validated against the captured corpus.

Phase 0 does **not** make a real client play — that is gated by the T1 fork at
the bottom. Phase 0 proves **T2** (transport + crypto + handshake) so T3 (the
authoritative sim) builds on a verified base.

## Canonical corpus paths (outside the repo — read-only by IP rule)

| Path | Contents |
|---|---|
| `C:\Users\terasumi\AppData\Local\Temp\vg_max\` | Main corpus. `mock_gcp.py` (round-trip proof), `vgdecode.py` (reusable decoder), 8 `.pcap`, `.vgr` recordings, decompiled `libGameKindred_decompiled.c`, extracted TSVs/pickles/screenshots |
| `…\vg_max\vgr\vgrtmp\` | 25 `.vgr` chunks, match id `ea4c7fda-…-b9f511e0-…` (first uuid = recording/session, second = match id) |
| `D:\Downloads\vg\` | Source input: extracted APK/OBB (`com.superevilmegacorp.game`, OBB 1.39 GB), `FINDINGS.md`, `FORMAT.md`, `asset_index.tsv`, emulator `cap/`, PC store build (`pc/Vainglory 4.13/`) |

**Rule:** read/analyze/index freely; never copy corpus bytes (`.pcap`, `.vgr`,
decrypted payloads, textures, models, the binary) into this repo. The two
scripts in `server/` (`mock_gcp.py`, `vgdecode.py`) are **our own code**, not
payloads, and are in-repo by design.

## What T2 must speak (from `Docs/Teardown/vainglory-protocol-wire.md` §15)

- **Framing**: `[u16 BE len][body]`, `len` excludes the 2 header bytes. Walk
  consumes 100 % of both directions (0 remainder).
- **Crypto**: Blowfish ECB, block 8 B, **per-match key**
  `MD5(SALT_64B ‖ match_id_string)`; words read/written as LE uint32 halves →
  decrypt `swap4(bf.decrypt(swap4(block)))`. Greeting stays plaintext; every
  later frame decrypts to `[u16 BE opcode][payload]`.
- **Route request (client first)**: `00 05 "<backend-ip>"` (134 B zero-padded)
  — client connects to a generic endpoint and names the backend to join. The
  port is dynamic per match; never filter by port.
- **Heartbeat relay (2112)**: server→client `89 00` every 10 s; client→server
  `8a 80 12 34 56 78` every 10 s. Plaintext, duplicated control channel.
- **C2S join / steady-state** (from `vg_max\c2s_map.txt`): `1000` (client sends
  its session uuid), `1112`, `1131`, `1118`, `1123` (build lock), `1119`,
  `1134` (shop open), `1137` (hero-ready ack), `1133` (buy-close), `1157`
  (level-up), `1012` (move/targeted-cast, two f32), `1081`, keepalive `0` every
  2 s (`[0000][u32 tick]`, tick ≈ 513/s).

## Server package layout

```
server/
  wire.py        # NEW — transport/crypto core: framing, key derive, enc/dec,
                 #        route-request, heartbeat; both sides
  decode.py      # NEW — corpus decoder (based on vgdecode.py) + .vgr reader
  gateway.py     # NEW — gateway: accepts route-request, assigns a match port
  match_server.py# NEW — match socket: handshake + frame loop + event emission
  mock_gcp.py    # kept as reference round-trip proof
  vgdecode.py    # kept as reference reusable decoder
```

`wire.py` is the single source of truth for the byte-layer; `gateway.py` and
`match_server.py` are thin sockets around it. T3 (the sim) later replaces the
hardcoded `match_server.py` event emission.

## Acceptance criteria (Phase 0)

1. `server/wire.py` derives the Blowfish key from `SALT + match_id` and round-
   trips a frame through `enc`/`dec` byte-identically (the `mock_gcp.py` proof,
   now as a real module + unit test under `server/test/`).
2. `server/decode.py` decodes **`vgfull.pcap` with match id
   `b9f511e0-11cd-4cfa-ad62-dc8612b8d270`** and reproduces the known opcode
   histogram (top: 0x042e / 0x042b / 0x041d / 0x043e / 0x03f8 …) from §15.8.
3. `server/decode.py` walks the 25-`.vgr` corpus with the `[u16 len][u16
   opcode][payload]` grammar → 31,266 frames, zero walk failures (§15.6).
4. `server/gateway.py` + `server/match_server.py` run locally; a test client
   completes route-request → GAME_SETUP(1001) → SNAPSHOT(1114) → heartbeat
   (`89 00`), matching the flow the real client expects for a solo-bot lobby.

## The T1 fork (the gate after Phase 0)

Phase 0 cannot be authenticated by a *real* client yet, because the client
learns the gateway/match endpoint through the **TLS-443 platform RPC** (menu →
auth → matchmaking), whose schema was boundary-blocked and remains unknown.
Two ways forward — pick one before wiring a real client:

- **A. Repack the client** (allowed). Patch the client to (a) skip the menu RPC,
  or (b) hardcode our gateway address, so it can be pointed at a local server.
  Requires knowing what the RPC injects before the match socket opens (roster,
  auth token, match config). We can recover this by observing the client's
  expected handshake inputs.
- **B. Emulate the RPC.** Stand up our own preauth + JSON-RPC that answers
  `rpc.kindred-live.net:443`-style calls with our gateway address. Highest
  fidelity, but the schema is unknown and it is the largest unknown in the
  whole build.

Recommendation: **A first** for a local PvP test (fast, we own the client), and
**B only if we want unmodified clients to connect.**

## External-risk note

`$TEMP\vg_max\` is scratch in the Windows temp dir — disk cleanup can wipe it.
If the corpus must survive long-term, move it to a durable location (operator
decision; do not move it automatically).
