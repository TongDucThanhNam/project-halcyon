# Vainglory wire protocol — the match connection decoded to the frame layer

§15 numbering is inherited for stable cross-references (§13 movement, §14
netcode, §15 this leaf). This leaf is the payload-level continuation of the
netcode leaf: §14 characterised the architecture from counters and strings;
§15 opens the actual byte stream. Evidence labels per the router README.

Everything here is **[Observed]** from a full-match packet capture taken
2026-09-03 on the user's own rooted emulator (LDPlayer 9, Vainglory 4.13.4,
community backend). Boundary status: see §15.7.

## 15.0 Method — reproducible capture pipeline

One solo-bot 3v3 match captured end-to-end (menu → hero select → load →
~5 min play → AFK surrender → menu), 353 s of stream, 5,816 packets.

1. Capture runs on the **guest**, as root, on the real interface:

   ```
   adb -s emulator-5554 shell "su -c '/system/xbin/tcpdump -i wlan0 -s 0 \
     -w /sdcard/vgfull.pcap tcp and not port 5555 </dev/null >/dev/null 2>&1 &'"
   ```

   Traps that cost a full match session each:
   - **`-i any` silently captures nothing** on this tcpdump 4.9.2/Android 9
     build — the process runs, the file stays 0 bytes. Use `wlan0` (the
     only real NIC; there is no `eth0`).
   - tcpdump buffers `‑w` output (4 KB stdio); a live capture shows 0 bytes
     until the buffer fills or the process gets a clean `pkill -TERM`
     (which flushes). A 0-byte file mid-capture is not proof of no traffic.
   - `su -c 'kill …' 2>/dev/null` — the redirect outside the quotes runs
     the NEXT command unprivileged; tcpdump then fails with "You don't
     have permission" and the failure looks like a filter problem.
   - Git Bash mangles `adb pull /sdcard/...` into a Windows path. Use
     `//sdcard/...`.
   - A `port 7095` filter captured **zero** packets for a whole match:
     the match-server port is **dynamic per match** (§15.1). Filter by
     interface and drop only adb (`tcp and not port 5555`).

2. Known-event timeline: every adb tap is logged with host epoch time
   (`date +%s.%N` before/after each scripted action — movement bursts,
   ability casts). The pcap and the tap log are correlated by burst
   pattern (period ~9.5 s is unambiguous; host/guest clocks need no
   sync for that).

3. Offline analysis (all in TEMP, never in the repo): TCP reassembly by
   capture order with wrap-aware sequence placement (sorting by raw seq
   breaks at the 2³² wrap and silently reorders the stream), then the
   frame walk of §15.3.

## 15.1 Endpoint topology during a match (Observed)

All GCP. Local guest 172.16.1.4.

| Remote | Port | Role | Measured volume (353 s match) |
|---|---|---|---|
| 34.53.88.87 | **7034 (dynamic)** | **the match connection** — plain TCP, no TLS (0 TLS-handshake bytes in 2,850 payload packets) | 917,493 B down / ~2 KB up |
| 34.160.208.252 | 443 | platform rpc (`rpc.kindred-live.net`), real TLS | 13.5 KB down / 10.6 KB up total |
| 35.233.231.76 | 2112 ×2 | relay control plane — heartbeat only (§15.2) | 1,404 B per connection |
| 34.160.58.175 | 80 | `preauth.*` bootstrap | CLOSE_WAIT residue |

Key structural findings:

- **The match port is dynamic per match.** An earlier session observed
  `136.66.77.13:7095`; this capture is `34.53.88.87:7034`; the Windows PC
  client used `34.105.13.248:7089`. Never filter by port.
- **The first bytes on the match socket are sent by the client and name
  the backend as an ASCII IP**: frame body `00 05 "34.53.88.87" 00…00`
  (134 B, zero-padded). That is a **route request to a gateway/relay
  frontend**: the client connects to a generic GCP endpoint and tells it
  which backend to join. 7034 is not "the game server" — it is the door.
- **The gateway answers the greeting with a 5 B plaintext ack**:
  `[u16 BE 3][00 06 00]` (vgfull.pcap t=+0.199 s). The client fires its
  first encrypted c2s frame ~1 ms after receiving it; without the ack it
  never speaks on the socket at all (2026-09-06 local-stack A/B, see the
  mobile-local-stack leaf). Captured opener order, relative to the route
  request: C route +0.000 → S ack +0.199 → C 1000 +0.200 → S 1001
  +0.397 → C 1112 +0.400 → S 1108 + 1107×275 + 1113 +0.593.
- **The match-key string is the `matchId` field of the platform `update`
  reply whose `state` is `playing`** — the client writes it into
  session+0xa8 before opening the match socket. [Observed] A/B on our own
  client 2026-09-06: `playing` payload without `matchId` → the client
  keys `MD5(SALT‖"")` (the session-string ctor default); adding
  `matchId` flips it to `MD5(SALT‖matchId)`, the key this capture was
  decoded with. The c2s 1000 payload is a different string — the
  client's session id (a JWT in our local flow, a UUID in this capture)
  — not the key input.
- Match state does **not** flow over 2112 and does **not** flow over the
  TLS 443 connection. The 443 stream carries only ~24 KB for a whole
  match (platform chatter).

## 15.2 The 2112 relay is a pure heartbeat channel (Observed)

Both relay connections carry, for the entire session:

- server → client: `89 00` (2 B) **every 10.003 s**;
- client → server: `8a 80 12 34 56 78` (6 B, constant including the
  `0x12345678` literal) every 10 s.

Plaintext, unencrypted, no framing shared with the match protocol. The two
connections received byte-identical totals (3,436 B each) — a duplicated
control channel, not load-balanced data. The same port answers HTTP GET
with an nginx/1.22.0 default page (netcode leaf §1). Conclusion: 2112 is
liveness/session presence only. The earlier "match idle ≈4.7 KB/s each
way" from §14 §2 was interface-level counting contaminated by adb traffic
and packet overhead; payload truth is §15.5.

## 15.3 Frame grammar (Observed — the grammar is closed)

The match stream is a sequence of frames:

```
+00  uint16 BE  length      // body length; EXCLUDES these 2 bytes
+02  byte[]  body           // 'length' bytes
```

Proof of the grammar is exhaustive, not sampled: walking with
`i += 2 + length` consumes **915,507/915,507 s2c bytes into 32,640
frames** and **1,986/1,986 c2s bytes into 162 frames** with zero
remainder in both directions.

Trap worth writing down: treating the length as *inclusive* (`i += L`)
parses ~28 frames and then desyncs — the failure mode looks like "the
stream changes framing mid-match" but is purely the wrong stride.

Both directions use the same grammar. A frame is not self-describing at
the byte level (no visible type field — the type lives inside the
obfuscated/encoded body, §15.4/§15.6).

## 15.4 Payload encryption — Blowfish ECB, per-match key (Observed; corrected same session)

**Correction of an intermediate claim.** The first read of this section
called the payload "8-byte repeating XOR obfuscation, placeholder-grade".
That was a special case, not the mechanism: the payload is **Blowfish ECB
with a per-match key** (block size 8 B), so every zero-padded block
encrypts to the *same* 8 bytes — which is exactly the repeating
`40 FA 87 7B 09 C4 B4 2E` pattern observed. The wire-level evidence in
this section (phase locked to frame bodies, 1,586 zero-runs, static
across 915 KB) all stands — ECB is stateless per block — but the
"static XOR / simplified crypto consistent with the community operator"
inference is **retracted**: the cipher is the original per-match Blowfish
design and the community server still issues per-match keys.

Full decryption was achieved and **verified against our own capture**:

- key = `MD5(SALT_64B || match_id_string)` — match id = the **second**
  UUID in the `replayManifest-*.txt` filename (`b9f511e0-11cd-4cfa-…`
  for this match; the first UUID is the recording/session id);
- 64-byte salt is hardcoded in `libGameKindred.so` (published by the
  HackedGlory RE archive, byte-order confirmed against our capture —
  see §15.8 credit note);
- Blowfish words are read as little-endian uint32 halves: decrypt with
  `swap4(bf.decrypt(swap4(block)))`;
- verification on this match: key `8022d4cab1243a338ed24bc1e6c0f8fa`,
  `BF(key, 00…0)` = `40 FA 87 7B 09 C4 B4 2E` — the exact observed
  zeros pattern. The greeting frame stays plaintext (sent before key
  application); every later frame decrypts to `[2B BE opcode][payload]`.

## 15.5 Traffic shape — what a match actually sends (Observed)

Frame-size histogram across the whole match:

| Direction | Size | Count | Reading |
|---|---|---|---|
| s2c | 16 B | 22,629 | the steady-state entity/event delta firehose |
| s2c | 24 B | 8,088 | second delta class |
| s2c | 40 B | 843 | mid-size events |
| s2c | 8 B | 726 | minimal control |
| s2c | 128 B | 174 | structured updates |
| s2c | **2,592 B** | **85** | the **initial full-state sync** |
| s2c | other (104/752/1,616…) | ~40 | handshake + rare events |
| c2s | 8 B | 138 | one per movement tap + keepalives |
| c2s | 16 B | 22 | one per ability cast |
| c2s | 134 B | 1 | route-request greeting |

Timeline (bucketed from the pcap):

- **Load/hero-select (first ~25 s)**: near-zero 16 B traffic — the match
  world does not exist yet.
- **Match start**: an 85-frame burst of 2,592 B frames in **9.1 s**
  (median gap 0.10 s) ≈ 220 KB — the initial full world state, then
  *never again* for the rest of the match.
- **Steady state**: 90–110 × 16 B frames/s plus ~25 × 24 B/s —
  ~2.6 KB/s payload downstream (≈21 kbps). This refines §14 §2's
  interface-level 4.7 KB/s (adb + per-packet overhead inflated it).
- **Client input**: in every scripted gameplay window the c2s rate equals
  the scripted tap rate (5 commands per ~9.5 s burst → ~5 c2s frames in
  the matching 10 s bucket) — **one 8 B/16 B frame per touch action**.
  The 160 non-greeting c2s frames across the capture include menu-phase
  taps and session keepalives outside the match window. This is the
  input-stream model proven at the protocol layer: in-match input is
  single bytes per player action.
- **Match end** (surrender accepted): all streams close ~285 s in.

Protocol shape corroborates the string evidence (netcode leaf §3): a
one-time full snapshot followed by per-entity event deltas over TCP with
`TCP_NODELAY` is exactly the shape that `Game_Replay`/PacketRecorder can
deterministically replay.

## 15.6 The decoded stream is on disk — `.vgr` auto-recordings (Observed, 2026-09-03)

The playbook's step 2 paid out immediately. `libGameKindred.so` strings
name `DispatchQueue_PacketRecorder`, `Game_Replay` and
`replayManifest.txt` — and the client **auto-records every match** to its
external cache:

```
/sdcard/Android/data/com.superevilmegacorp.game/cache/
  replayManifest-<match-uuid>.txt                 # 74 B: the match uuid
  <match-uuid>-<recording-uuid>.0.vgr … .24.vgr   # ~40–60 KB each, 1.1 MB/match
```

`.vgr` is the **post-decryption recording** of the same match captured in
§15.0 (timestamps interlock: chunks written every ~10 s while the pcap
ran). Evidence it is decoded, not encrypted: entropy 3.36 bits/byte,
57.7 % zeros, plaintext identifiers inline — player name `Guest`,
`*GameMode_HF_SoloBots*`, heroes `Grumpjaw/Adagio/Baptiste/Viola`, bots
`Alpha…Epsilon Bot`, `__Kindred_Player_Bot__`. The wire's Blowfish
ciphertext (§15.4) appears nowhere in it — it is the decoded layer.

Semantic readings already extracted (all [Observed]):

- **Positions are plain big-endian f32 triples** (x@+0, y-ish@+4, z@+8):
  the known 30-anchor table is found verbatim (LCampA −40.915/20.251,
  Kraken 23.6, turret 17.06, shop −88.5 …), and filtering those out
  leaves clean **mover trajectories** (minion lanes along z≈0.5–5.5,
  jungle walkers).
- **Every record carries the match clock as a BE f32**: the dominant
  non-zero float per chunk is 20.0 → 80.0 → 150.0 → 220.0 → 240.0 s
  across chunks 2/8/15/22/24 — exactly the ~10 s chunk cadence, with
  sub-second variants (157.3 = 2:37). The recording is tick-stamped, so
  events can be laid on an exact timeline.
- **Rule-layer parameters are readable**: BE f32 blocks like
  `45 9c 40 00` ×2 (≈5,000.0 — vain/turret-class HP) and 1.0 constants
  sit adjacent to position records — the same param-block shape the heap
  route found (map leaf §11).

**Record grammar (table level) — decoded (Observed, same session).** Each
snapshot section is a fixed-stride entity table. Static-object records
are **132 bytes**, big-endian, and column-readable:

| Offset | Type | Meaning (evidence) |
|---|---|---|
| +0 | u32 | entity id — static anchors occupy 3533–3565 in descending table order (LturretO 3545, LturretM 3546, LturretB 3547, RTurretB 3541→`0d d5`, LCampA 3558, LMine 3560, CenterKraken/Mid 3561/3562, LShop 3565); 73 distinct ids in one chunk (3533–3617) |
| +4/+8/+12 | f32 ×3 | x, y, z — y is the ground-snap constant `3b e7 a8 f8` = 0.0071 (map leaf §11), LShop y 0.808, positions bit-match the 30-anchor table (RShop 88.57/1.747/0.51) |
| +16, +24 | f32 | rotation cos/sin pair — turret 0.9659/0.2588 = **15°**, consistent with the ±75° base-turret yaw set |
| +28, +32 | f32 | **max-HP / HP** — see the tier table below |
| +44 | f32 | radius-like (shop 2.5, turret 0) |
| +68, +72 | f32 | paired range-like columns — turret 800/800, shop 0/0 |
| +80…+95 | bytes | per-state flags (`01…03 0f 03 03`) |
| +104 | u32 | `ff ff ff ff` (−1 sentinel) |
| +108 | byte | entity-class tag (turret 0x0e, shop 0x20) |
| +109…+131 | bytes | shared engine template tags + per-record counter (`00 00 01 72`) and a trailing f32 |

Records sit at a constant 132-byte stride in **descending id order** — a
full-table dump per section, 2 clock-stamped sections per ~10 s chunk
(≈5 s cadence).

**Correction + closure (2026-09-03, later same day).** The "132-byte
record" is not a record format — it is **frame header + payload**: the
whole `.vgr` is a frame log `[token u32][len u32 BE, includes opcode]
[opcode u16][payload len−2]`, and the table walks it as 8 + 124 bytes.
Walking all 25 chunks with this grammar: **31,266 frames, zero walk
failures**. The table above therefore shifts by the 8-byte header, and
the authoritative field map is the payload of opcode **1010
ENTITY_FULL_UPDATE** (124/128 B): `+0 u16`, `+2 u16`, `+4 class-dep
field`, `+8 u32 id`, `+12/+16/+20 f32 x/y/z`, `+24/+28 cos/sin yaw`,
`+32 f32 1.0 (scale)`, **`+36 f32 HP`, `+40 f32 maxHP`** (verified
against anchors: LShop x −88.5, y 0.808, HP **448** — the "450" above
was a rounded read; tier numbers 2500/3000/3500/5000/10000 confirmed).

Because the stride is fixed, column-wise diffing the 25 chunks yields
the combat timeline directly: HP columns moving = damage events, ids
appearing = spawns, position columns moving = movement. Combined with
the semantic layer (§15.8) that delivery path is complete: ledger rows
8–10 are served.

**Named entity table (id ↔ placement name ↔ HP — the full static
roster).** Joining 1010 positions against the placement table (map
leaf §11): 3539–3543 = R turrets Outer/Middle/Base/Vain1/Vain2,
**3544 = R Vain crystal (10000)**, 3545–3549 = L turrets,
**3550 = L Vain crystal (10000)**, 3551–3554 = R camps A–D,
3555–3558 = L camps A–D, 3559/3560 = R/L Crystal Mines (**5000**),
3561/3562 = CenterKraken/CenterMid (**5000**), 3563 = CenterBottom
(**5000**, the entity that died at c23), 3564/3565 = shops (448);
3533–3538 = spawn/locator class. Chunk-1 records spawn at HP 0/0 and
fill on the next section — first-sight HP 0 is a spawn artifact, not
damage. Static 5000-class at camp/mine/center anchors = objective
locator objects (GenericLocatorHealth family), distinct from the
dynamic jungle monsters [Interpretation: name join is measured, the
locator reading is from the placement class names].

**Dynamic entity HP classes (match 1, 1010 maxHP histogram):** lane
minions 475/505/575/580/600 → 628/730/750/880/930/950 → 1022/1119
(per-wave scaling visible), siege-class 1500/1860, and a **150,000-HP
class ×5 entities** = unkillable spawn-locator class [Partially
verified]. Heroes die and respawn (match 1: eid 1517 died at c13/c18/
c24, 1518 c18, 1519 c19/c23); kill attribution via last 1054 deltas
(1518 ← minion 8866 −91.0, 1519 ← minion 8757 −86.5). Misc opcodes
sampled: 1018 = `[tgt][src][x][y][z]` targeted order, 1019 = position
set (ground-snap y visible), 1037 = minion AI tick (24 B, eid + f32 +
paired counters), 1052 = level-up candidate, 1089/1091/1093 = stat-id
events (2001/2002/2024), 1027 = position+facing.

The dynamic-record envelope previously listed as remaining work is
**closed** — it *is* this frame log; see §15.8 for the per-opcode
semantics and the 3563 death chain.

**Structure HP tiers + first combat timeline (Observed, 2026-09-03 —
full 25-chunk column diff of +28/+32).** The single "turret 3500"
reading above was the base turret; the tiers are real:

| Structure class (ids) | max-HP | Evidence |
|---|---|---|
| Outer turrets (3539 R, 3545 L) | **2500** | both read 2500/2500 in chunk 1 |
| Middle turrets (3540, 3546) | **3000** | untouched all match |
| Base turrets (3541, 3547) | **3500** | untouched all match |
| Vain crystals (3544, 3550) | **10000** | matches the map-leaf heap param block `10000, 360, 360` |
| Vain-guard class (3551–3563) | **5000** | all read 5000/5000 |
| Shop props (3564, 3565) | **450** | prop-class, not destroyable objectives |

Damage timeline, right outer turret 3539 (HP column, one reading per
chunk): 2500 → 2304 (c16) → 2084 → 1720 → … → 1468 (c22) → **555 (c23)
→ 460 (c24)** — under siege from clock ≈160 s to match end. Left outer
3545: damaged from c7 (2500→2442), ground down to 1359 by c13, then
left alone. One 5000-HP vain-guard entity (3563) went to **0 at c23**
(≈ clock 230 s) — the only structure death of the match, coinciding with
the final push before the bot match ended. All other structures left at
full HP. This is the first complete damage-vs-clock series produced
entirely from local artifacts.

Method note: pull chunks via `su -c 'cp …/cache/*.vgr /sdcard/vgrtmp/'`
then `adb pull`. The wire-frame byte signatures do **not** appear in the
recording — the envelope is the client-side representation, not the wire
bytes. Artifacts live in TEMP (`vgrtmp/`, 25 chunks, 1,164,010 B).

## 15.7 Boundary status (binding record)

- **2026-09-03, user directive** ("Mở khoá Boundary… NHANH + efficiency",
  following "tập trung đục vào phần Server đến và đi"): protocol decoding
  from **capture of the user's own device** and native-code RE are
  sanctioned for this campaign.
- Retained line, unchanged: **read-only on the wire** — no scanning or
  probing of their servers, no crafted/injected packets upstream, no TLS
  interception. Every technique in this leaf is passive capture of the
  user's own emulator traffic.
- No pcap, dump or payload byte enters the repository — TEMP only; this
  leaf stores structure, counts and constants (the XOR key is an
  obfuscation constant, not payload content).

## 15.8 Semantic layer — decrypted message catalogue, first pass (Observed)

With the key derived (§15.4) every frame of our capture decrypts to
`[2B BE opcode][payload]`. Top of the catalogue from this match
(32640 s2c / 162 c2s frames, 73 distinct s2c opcodes, dominant range
0x03e8–0x0490 = the client's 171-case dispatch switch):

| Dir | Opcode | Count | Payload reading (from samples) |
|---|---|---|---|
| s2c | 0x042e | 5,946 | entity id + f32 pair — per-entity state deltas |
| s2c | 0x042b | 5,330 | id + flag bytes (static ids seen, e.g. `0d ed`=LShop) |
| s2c | 0x041d | 5,090 | id `05 dc`=1500-family (hero-attached) + u16 fields |
| s2c | 0x043e | 4,390 | two id fields (1500,1500) + u16 tail |
| s2c | 0x03f8 | 3,546 | **two in-map f32, no id** (38.9/19.28 …) ≈10 Hz — observer/hero position stream |
| s2c | 0x041e | 2,104 | minion id (`10 db`=4311-family) + structure id (`05 ed`=LShop) — aggro/attack events |
| s2c | 0x0415 | 1,799 | same-id pair + u16 count |
| s2c | 0x0453 | 275 | `*SymbolName*` strings over the wire (`*Adagio*`) — ability/symbol events |
| c2s | 0x03f4 | 21 | **two in-map f32 = move/cast target coordinate** (−75.77, −2.67 — matches the left-spawn area the script tapped) |
| c2s | 0x0411 | 5 | `ff ff ff ff` + u16 |
| c2s | opcode 0 | 123 | plaintext-region keepalives (pre-key control frames) |

Entity id families reconcile with the `.vgr` tables (§15.6): static
anchors 3533–3617, minions allocated sequentially per wave
(4314 → 5871), 1500-family hero-attached.

**Named opcode catalogue (their decompiled dispatch, cross-checked with
our samples).** Their `FUN_100123fa0` switch names the decimal range
1000–1135; mapped onto our capture the counts line up:

| # | Name (their archive) | Our reading |
|---|---|---|
| 1000 | PLAYER_UUID | inside the 2592 B snapshot burst |
| 1001 | GAME_SETUP | setup burst only |
| 1005 | PLAYER_HANDLE | names (`Guest`, bot names) |
| 1006 | PLAYER_INFO | setup burst |
| 1016 | ENTITY_FLOAT (16 B) | velocity/distance-class floats |
| 1053 | **ENTITY_STAT** `[2B][2B eid][4B BE f32][1B stat_type]` | stat_type 3 = move speed (2.5–3.5), 6 = **HP delta = the wire's damage event**, 8 = cooldown/attack speed (0.2–4.8), 0 = attack 0–90 |
| 1067 | ENTITY_STATE | id + state enum |
| 1070 | POSITION `[2B][2B eid][4B X][4B Y][2B]` | ~20 Hz per active entity; X −90…+90, Y −10…+20 — our 0x03f8 stream (two in-map f32, no id) is the observer variant of this |
| 1086 | ENTITY_PROP | gold/XP counters |
| 1087 | ENTITY_DATA (40 B) | per-entity blob |
| 1107 | HERO_CATALOG | `*HeroName*` strings — our 0x0453 `*Adagio*` events |
| 1108 | GAME_MODE / 1135 | MODE_NAME `*GameMode_HF_SoloBots*` |
| 1114 | **SNAPSHOT 2592 B** | = **6 × 161 B scoreboard records** (+8 slot, +15 team, +18 eid, +24 handle 32 B, +104 uuid 36 B, **+16 gold u16**) — the 85 big frames in §15.5 are full-scoreboard dumps (~2 Hz in combat), not world state |

Coordinate system note: wire positions share the map leaf's coordinate
frame (X −90…+90 matches the 30-anchor table extents), so wire and
`.vgr` positions plot onto the same minimap directly.

**Payload semantics closed to the field level (2026-09-03, second pass
same day).** The `.vgr` log *is* the decrypted s2c stream — five opcode
counts match the wire capture of the same match exactly (1053: 5,090,
1086: 4,390, 1054: 2,104, 1045: 1,799, 1067: 5,330), so the client-side
recording and the wire are one dataset. Full 25-chunk walk: 31,266
frames. Field maps [Observed]:

| Op | Name | Payload (decoded) |
|---|---|---|
| 1010 | ENTITY_FULL_UPDATE | 124/128 B; id@+8, x/y/z@+12/16/20, yaw cos/sin@+24/28, scale 1.0@+32, **HP@+36, maxHP@+40** |
| 1053 | HERO_STAT | `[u32 eid][f32 value][u8 type][5B tail]` — hero-family eids only; type 6 = HP delta (−600…+402), 8 = cooldown/atk-speed (1…16.8), 4 = range events (turret ±800 at siege moments), 2 = −150…+30, 0 = −10000…+6 |
| 1054 | COMBAT_DELTA | `[u32 src][u32 tgt][f32 delta][8B tail]` — negative = damage (typical minion hit −27.8; spread −11…−70), positive small = regen-class; **kill blow = giant overkill (−10000.0 on the 3563 death)**; attribution verified: heroes 1515/1516 + minions 6xxx–8xxx vs turret 3539 |
| 1086 | ENTITY_PROP | `[u32 eid][u32 src][f32 amount][u8 0x0c][u8 seq][u16]` — property increments; dominant 3.594 (passive XP-class trickle), bursts 2048/512/32 = scaled counters [partial] |
| 1067/1068 | ENTITY_STATE | `[u32 eid][u8 state][u8 flag]…` / 8 B sub-state — the state machine around deaths |
| 1073 / 1035 | DESTROY / DESPAWN | `[u32 eid][u16]` — entity lifetime end |
| 1162 | TIMER_TICK | `[u32 eid][u32 instance][u32][f32 timer][6B state]` — per-entity countdowns (clock, respawn-class values 5.0/0.5) |
| 1011 | HERO_BLOCK | 748/752 B per-hero binary block (eid + counts + f32 run) — ability/level data [partial] |
| 1006 | PLAYER_INFO | 218/224 B handle records: `Guest, Grumpjaw, Adagio, Baptiste, Krul, Viola` + `Alpha…Epsilon Bot` |
| 1107 | HERO_CATALOG | `*Name*` × 275 heroes downloaded at join |

**Hero entity ids = 1500 + 1515–1519** (six heroes; 1505 never appears).
**Death chain, ground truth (3563, vain-guard, chunks 22–23):** 1068
`02 03` → 1067 state → 1067 flag 01→00 → 1068 `02 02` → **1054 (3563,
3563, −10000.0)** → 1068 `00 01` → 1072 clear → c23: **1073 destroy →
1035 despawn**, 1010 HP = 0. Kill/death detection = 1054 overkill +
1073, answering an open problem of the external archive.

**C→S layer, second match (2026-09-03, scripted-action run).** New
capture with labelled taps (1,390 B up / 116 c2s frames; match port
7044, match uuid `591146df-…`):

| Rel. | Op | Reading |
|---|---|---|
| join | 1000 (c2s!) | client sends its match-session uuid string `ea4c7fda-…` — PLAYER_UUID is bidirectional |
| join | 1112 `0x0458`, 1118 `0x045e`, 1131 `0x046b` | join-phase handshakes (1118 carries a token pair) |
| +17 s | 1123 `0x0463` | build-select/lock confirm |
| +50 s | 1134 `0x046e` | shop-open (timestamp-aligned) |
| +57 s | 1133 `0x046d` | purchase/close confirmation |
| +? | 1137 `0x0471` | `[u16][u32 eid=1500][u16 0100]` hero-ready/loadout ack |
| steady | op 0 | keepalive every **2.00 s**, `[u16 0x0000][u32 0x46d6][u16 tick]` with tick rising ≈513/s |

Honest negative: the movement/ability taps of this run produced **zero**
c2s frames — the first-match tutorial overlay ("Choose a Build" +
pointer arrow) was still active and swallowed map/ability taps. The
move/cast opcode stays **0x03f4 = two in-map f32** from match 1 (21×,
verified by tap correlation there). Shop/purchase opcodes above are
timestamp-aligned but the guest/host clock offset makes the exact
1133-vs-1134 split [Partially verified].

**Mock-gateway round-trip (encode side proven).** A minimal local mock
(TEMP, `mock_gcp.py`) implements the full grammar — `[u16 BE len][body]`
framing, route-request greeting, `89 00` plaintext heartbeat, Blowfish
bodies keyed `MD5(salt‖match_id)` — and a client that decrypts it back
passed: GAME_SETUP(1001) and a 2,590 B SNAPSHOT-shaped frame survive
encode→decode byte-identical, heartbeats stay plaintext. This doubles as
the seed of Veilbound's own multiplayer prototype (input-stream model,
deterministic deltas).

**Wave cadence — first rule-layer number off the recording**: new minion
ids appear in bursts at clock ≈30 s and ≈90 s → **60 s wave interval,
~12–14 entities per wave** (both lanes, both teams), matching
chunk-burst sizes; the 1500-family and single-id chunks between waves =
creep/jungle respawns.

**Dispatch switch extracted from the client binary (2026-09-03, third
pass).** The Android Ghidra decompile of `libGameKindred.so` (public
archive, same build) contains the message dispatch as a 167-case
switch over opcodes **1001–1168**; every case has a parse-handler
address, and a large **generic fall-through family** shares one entity-
message path: 1012–1015, 1036, 1041–1044, 1060, 1062, 1066, 1069,
1078, 1080, 1096–1098, 1104, 1109–1113, 1117–1131, 1133–1134, 1138,
1140, 1146–1147, 1156–1158, 1166. Named anchors from their writeup +
our handler mapping (addresses = structure identifiers for
falsifiability): 1010 ENTITY_FULL_UPDATE `FUN_00928854`, 1053 HERO_STAT
`FUN_0092a024`, 1054 COMBAT_DELTA `FUN_0092a0bc`, 1070 POSITION
`FUN_009284bc` (**handler reads exactly two floats**, z filled 0),
1073 DESTROY `FUN_00cfe30c`, 1113/1114/1115 snapshot trio
`FUN_009e07c4/e8/0c`, 1162 TIMER_TICK `FUN_009295f4`, 1137 = per-slot
bit-flag setter over a **16-slot player table** (max-players evidence).
Handler bodies confirm the struct field orders we decoded empirically
(1054: src/tgt/f32 + flag bytes; 1053: eid/value/type + two bools).
C→S and S→C share this opcode space — c2s frames land in the same
switch.

**C→S action layer closed (match 3, uuid `410ce92b-…`, port 7043,
overlay-free run).** Action-to-frame alignment across the guest/host
clock offset (≈+70 s drift; derive it from the first action after the
build-confirm frame):

| Action (scripted) | Frame on the wire |
|---|---|
| ability point → A | **1157 (0x0485)** `[0485 0000…]` |
| ability point → B | **1078 (0x0436)** `[0436 0000…]` |
| targetless cast (B) | **1041 (0x0411)** `[0411 ffffffff 0000]` — `ffffffff` = null target |
| move tap / targeted cast (A) | **1012 (0x03f4)** `[u16 op][f32 x][f32 y][6B 0]` — one opcode for both |
| shop open / buy-close | 1134 / 1133 (second match confirming match 2) |
| keepalive | op 0 every 2.00 s, tick ≈513/s |

Honest caveats: one of two move taps produced no frame (UI-drop is
real); the guest/host clock offset means per-action alignment is ±1 s;
1157-vs-1078 = per-slot assignment is consistent across two matches but
not independently witnessed twice per slot. With this table, **every
player-visible input is now named on the wire**: move/cast 1012,
targetless cast 1041, level-up 1157/1078, shop 1134/1133, join 1000
(uuid, bidirectional)/1112/1118/1123/1131/1137, keepalive 0.

**Match-3 s2c corpus** (11,027 frames decrypted) reproduces the match-1
tally shape (1070 position 1,898; 1067 1,893; 1086 1,731; 1053 1,540) —
protocol confirmed stable across matches, ports and keys.

**SNAPSHOT 1113 record, empirically pinned:** 2,590 B payload = 2 f32
header + **6 records at stride 161** ("Guest/Alpha/Beta/Gamma/Delta/
Epsilon" found at +161 steps; eid u16 sits 9 bytes before the 32-byte
handle; `__Kindred_Player_Bot__` uuid sentinel for bots). Gold column
**resolved as a measured negative** (post-audit mining): a full sweep of
every u16/u32/f32 position in the record area across 81 match-3
snapshots — monotone and purchase-dip-tolerant fingerprints — finds **no
per-hero gold-like column**; the HUD gold number is therefore
client-accumulated from the 1086 award stream (+ passive) [Inferred,
consistent with the 3.594-band awards]. Columns that *are* there: +146
u16 = snapshot counter (+1 per snapshot, per-record seed 0…5); the
handle−5…−1 f32 family = XP-class smooth growth, per-record distinct
(e.g. Guest →24,642) [Inferred]; header 2 f32 = countdown pair
(observed 300.0→7.0→0.0 across a capture that joined mid-match and ran
to match end) [Partial]. Remaining 1,624 B of the payload after the
6 records = additional world fields, not yet mapped [Open, minor] —
the clock-calibration attempt (1162 values as ground truth) was
degenerate on match 3 (its 1162 payloads read 0.0).

**Post-audit offline mining (2026-09-03).** Match-3 corpus rebuilt from
vg3.pcap: byte-accurate reassembly by TCP seq (dict per byte — one
contiguous 470,320 B run, zero gaps), then **decrypt-validated resync**:
a mid-stream join starts inside a frame, so a resync scan accepts a
length only when the first Blowfish block decrypts to an opcode in
1001–1168 (worked at stream offset 16 → 10,122 frames, 81 snapshots).
Per-bucket 1054 grouping gives the per-hero DPS curves (end-phase
window: dealt 142–660, taken 1,583–4,135 per hero; one corrupted bucket
from a mid-stream decode slip excluded). Match-1 re-attribution:
combat damage to heroes is fully in 1054; the two overkill events
(3563 kraken-class, 4479 minion) carry zero accumulated 1054 damage and
sit at stream end = match-end teardown, not combat deaths.

**Independent adversarial audit (2026-09-03) — dispatch count reconciled, traffic families closed.** Fired after the completeness claim was challenged; every point below re-verified locally.

- **167 vs 171 resolved [Observed]**: our decompile's dispatch (`FUN_0092b85c(ushort *msg, …)`, reads
  `bswap16(*msg)` then switches) contains **exactly 167 case labels, min 1001 / max 1168, none below
  1001, no pre-switch opcode branch** (full-file re-count: 1,006 unique case labels across 4.97 M
  lines, of which 167 sit in 1001–1168). HackedGlory's "171 cases over `0x000B…0x0490`" is a
  counting-convention difference — their range bottoms at opcode 11, and the file's 477 case labels
  below 1001 belong to separate rpc/session-layer switches — not a hole in this catalogue.
- **Traffic families in a full-match capture [Observed]** (vgfull.pcap, match 1): peer ports =
  match stream 7034 (+ reverse 54700), 2112 heartbeat, 443 rpc (36 packets across the whole match),
  nothing else — no port 853, no second data channel.
- **UDP [Observed]**: 45 s live-device capture filtered `udp or icmp` → 18/18 packets are mDNS
  multicast (224.0.0.251:5353), zero game traffic; and the TCP frame walk already consumes 100 % of
  match bytes with zero remainder, leaving no room for a parallel game-data channel. Voice/telemetry
  channels are **out of the match-protocol claim's scope**. The "Vivox" association from public
  SEMC history is [Unverified] for this build: zero `vivox` strings in libGameKindred.so (voice, if
  present, would live in a separate APK library).
- **Matchmaking handoff [Inferred, cited]**: TLS-443 HTTPS JSON-RPC per the archive's static report
  (auth/party/matchmaking flows) — consistent with our tiny 443 window; no plaintext path observed;
  interception stays outside the read-only boundary.
- **Server-correction/rollback [Inferred from structure]**: no dedicated opcode exists in the
  167-case space (measured absence). Authoritative correction rides re-issued absolute state
  (1010 full update, 1019 position set).
- **1045 refined [Partial]**: `[u32 eid][u32 eid][u8 03][5B 0]` — self-eid duplicated, ≈5.1/s,
  first seen on turret 3539; per-entity state/visibility setter, exact flag semantics open.
- **1086 refined [Partial]**: shape reads `[u32 a][u32 b][f32 v]` (like 1054); v ≈ 3.59–3.75
  dominant = minion-kill award band, matching the measured ≈3.6 gold/minion.
- **Kill attribution corrected [Observed]**: both 1054 overkill events in match 1 (3563
  kraken-class, 4479 minion) arrive with **zero accumulated 1054 damage** and sit at stream end →
  match-end teardown events, not combat deaths. Combat damage to heroes is fully in 1054, giving
  per-hero totals (taken 5,900–16,409; dealt 546–5,466; minions are 55–97 % of damage taken);
  turret damage does ride 1054 (3539: 32 events). Per-hero DPS curves over time = mechanical
  grouping of 1054 by chunk. 80 × 1054 events target eid `0xffffffff` (wildcard) across 16 of 25
  chunks [Open, minor].

**1053 stat-id census (2026-09-03, three corpora pooled: 13,640 events).**
Dispatch shims decode to real handlers: 1052→`FUN_00929fac`, 1053→
`FUN_0092a024` (which builds an event object via `FUN_00d043c0(eid, out,
f32 value, u8 type, bool@+9)` with two more bool flags at payload +10/+11
— the old "[5B tail]"), 1054→`FUN_0092a0bc`. Observed type bytes:

| type | n | semantics | evidence |
|---|---|---|---|
| 0 | 961 | **move speed** (bounded floats; med 4.39, max 6.25) | matches DB `move_speed` (med 3.8, range 2.3–6.5); > base = boots/buffs |
| 1 | 5 | large chunks 782–1327 (kill/assist XP or bounty) [Partial] | hero-only, rare |
| 2 | 3,405 | XP deltas [Inferred: hero-only, passive-cadence, med 9.09, flow ≈ level-12 total] | accounting only |
| 4 | 392 | event scalar, NOT attack range — values ±irregular (−151…+220, e.g. ±80/±109/120) [Partial — distance/offset-like; earlier "range" reading retracted] | census across matches |
| 5 | 23 | ±100 percentage events (buff/debuff %) [Partial] | hero-only |
| 6 | 2,819 | **HP delta** (−600…+402; med +6.0 = regen) | confirmed |
| 8 | 2,856 | **cooldown** (1–16.8 s) | confirmed |
| 9–15 | ~600 | hero boolean flags (combat states; unnamed) [Partial] | 0/1 values |
| 213 | 1 | one-off flag [Open] | — |

New entity band **3768–3778**: receive type-4 range events (8 each), take
and deal small damage — ability/pet/indicator-class entities [Partial].

**Their open problems vs our local artifacts** — the two archives are
complementary, not redundant:

| Open in HackedGlory (3v3 ARAL captures) | Answered here by |
|---|---|
| Minion/structure entity mapping (they tracked only hero ids 1500–1505) | §15.6 static table: 73 ids decoded, all 6 structure classes + shops placed and HP-tiered |
| Structure/objective HP | §15.6 tier table 2500/3000/3500/5000/10000/448 |
| **Kill/death detection** | **§15.8 death chain: 1054 overkill + 1073 destroy + 1035 despawn, ground-truthed on 3563** |
| **Absolute HP vs deltas** | **1010 @+36/+40 per entity every ≈5 s + 1054 deltas** |
| Wave timers | 60 s interval, 12–14 entities (§15.8 above) |
| **Hero assignment** | hero eid family = 1500 + 1515–1519; snapshot 1113 carries eid+handle per record; 1006 order gives roster |
| C→S input format | **closed**: 1012 = move/targeted-cast (x,y), 1041 = targetless cast, 1157/1078 = level-up, 1134/1133 = shop, join seq + keepalive (§15.8 match 3) |
| Ability-cast c2s | **closed**: targeted casts ride 1012 (same as move — a ground-target order), targetless ride 1041 (`ffffffff` null-target) |

Credit and provenance note: the salt bytes and the key-derivation recipe
were published by the public `a1cnore/HackedGlory` RE archive (same
client build 147219); the match id source, byte-order and every number
above were **re-derived and verified against our own capture**. Facts are
cited, not bulk-copied (the archive carries no license). Their archive
additionally holds: their 171-case dispatch count over range `0x000B…0x0490`
(decompiled `FUN_100123fa0`; our switch measures exactly 167 cases over
1001–1168 — see the audit note above for the reconciliation), a decrypted CFF0
balance database, mesh-extraction reports with the skinned-mesh
attribute table (see the mesh-structure leaf for the rigging
architecture), and committed Ghidra corpora for `libGameKindred.so`.

## Reproduce

```
# 1. capture (guest, root) — start BEFORE entering the match
adb -s emulator-5554 shell "su -c '/system/xbin/tcpdump -i wlan0 -s 0 \
  -w /sdcard/vgfull.pcap tcp and not port 5555 </dev/null >/dev/null 2>&1 &'"
# 2. drive the match via adb taps, logging host timestamps per action
# 3. flush + pull
adb -s emulator-5554 shell "su -c 'pkill -TERM tcpdump'"
adb -s emulator-5554 pull //sdcard/vgfull.pcap <TEMP>/vgfull.pcap
# 4. derive the per-match Blowfish key (§15.4) and decrypt each 8-byte
#    block: swap4(bf.decrypt(swap4(block))); message = [u16 BE opcode][payload]
```

Artifacts referenced by this leaf (TEMP, not committed):
`vgfull.pcap` (1,357,284 B), `s2c.bin`/`c2s.bin` (reconstructed streams),
`actions3.log` (tap timeline), `vg2112.pcap` (heartbeat-only capture),
`pkts.pkl` (first-pass packet table); second pass:
`vgr/frames.pkl` (31,266-frame parsed log), `vgc2s.pcap` (1,237,245 B,
match 2), `actions4.log` (labelled action timeline), `vgr2/` (match-2
recordings, 21 chunks), `mock_gcp.py` (round-trip proof).
