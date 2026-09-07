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
| 1114 | **SNAPSHOT 2592 B** | = **6 × 161 B roster records** (1113 join-slot layout corrected below; applying it to 1114 still needs independent verification) — the 85 big frames in §15.5 are full-scoreboard dumps (~2 Hz in combat), not world state |

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
| 1010 | ENTITY_FULL_UPDATE | **two payload variants: 126 B (no HP) and 122 B (HP@+36, maxHP@+40)**; eid@+0, class id@+4, write-tick@+8, x/z/y@+12/16/20, facing cos/sin@+24/32. The former "124/128 B; id@+8" row counted the opcode into the length and misread the +8 write-tick as entity id — full offset evidence and the hero-1010 falsification in §15.8 "1010 measured on the wire" (corrected 2026-09-06) |
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
handle; `__Kindred_Player_Bot__` uuid sentinel for bots). [2026-09-06
live correction: slot base is **+8** with an 8-byte prefix inside each
161-byte slot. The intermediate +16 interpretation split that prefix off
and mislabelled the next slot prefix as a tail. Correct offsets and hero
selection semantics are in the roster block below.] Gold column
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

**Roster / join-completion exchange closed (2026-09-06, vgfull.pcap +
c2s.bin re-decode; encoders live in `server/roster.py`).** The join gate
after the opener burst is the **player roster**, and its binding mechanism
is now field-exact:

- **c2s 1000** = 70 B payload: the account session uuid (36 B ASCII) + 34 B
  zero pad. Match 1's Guest uuid `ea4c7fda-…` is the account session — it
  recurs across matches, so 1000 is presentation, not per-match binding.
- **1118 hero selection** (live-corrected): c2s `[u32 hero_id][u32
  selection_hash][6B 0]`, s2c echoes the selection. The client sends it
  without any preceding s2c 1118. Live selection pairs: Amael =
  `(925, 0x2fd7245d)`, Adagio = `(244, 0xf9fd7554)`; clicking a different
  hero changes the pair. These are **not per-match player credentials**.
  The first field recurs in 1006 (+164), 1011 (+0), and 1113 slot (+9);
  the second recurs in 1011 (+4) and 1113 slot (+13). Internal hash
  semantics and the full hero/skin ID table remain open.
- **1006 PLAYER_INFO = 222 B**, one frame per player, roster order, sent
  as two identical groups of 6 (`1006×6 → 1135 → 1006×6`): handle 64 B @+0,
  session uuid 36 B @+64, hero eid u32 @+160, selected hero id u32 @+164,
  **committed selection hash u32 @+168** (supersedes the "XP-class f32"
  reading — same bytes; see the post-lock block below), const `0x9241f10e`
  @+172, loadout/tail union
  @+176..221 (local: 5×FNV1a("")=811c9dc5 + `ff ff 00 ff` + `00 02 01 00` +
  `01 00`; bots: derived 16 B guid + `f1dedae3`-class u32 + `ff ff ff ff` +
  `00 02 01 00 01`) [union semantics Open, minor].
- **1135 MODE_NAME** = `*mode*` zero-padded to 70 B (no u32 prefix — vs
  1108 which is `[u32 0][*mode*]`, same 70 B).
- **1011 hero block = 750 B**: hero id u32 @+0, selection hash u32 @+4, eid u32 @+8,
  **team u32 @+12 (values 1/2)**, `ff ff` @+16, hero-stat f32 run @+18…
  (content hero-specific, not mapped), tail `…ff ff ff ff [u8 slot-class]`.
  Stream order = reverse roster order, each block followed by 7 ×
  **1162 TIMER_TICK** (`[u32 eid][u32 tag][u16 0][f32][8B tail]`, same
  global tag set for every hero).
- **1113 SNAPSHOT layout**, corrected by full-byte reconstruction:
  `8 B countdown (f32 ×2) + 16 × 161 B slots + 6 B zero padding = 2590 B`.
  Slot base `8 + 161*k`: occupied u8 +0, **zero-based slot index** u8 +1,
  pick flags u16 +2, marker `ff ff ff 00` +4, team u8 +8 (1/2),
  **selected hero id** u16 +9 (`ffff` while unpicked), eid u16 +11,
  selection hash u32 +13, handle region 80 B +17, identity region 64 B +97.
  Empty slots retain their index and marker, team=0, hero/eid=`ffff`,
  hash=`10c2bad9`. Initial local hash is zero; initial bot hashes are
  `10c2bad9`. Corpus UUIDs occupy 36 B of the identity region; this does
  not imply the field is only 36 B wide. The previous +16/has-next/
  one-based-slot interpretation is superseded.
- **Live crash isolation:** rebuilt 1001/1108 are byte-identical to the
  corpus. Old snapshot + rebuilt opener survives; new snapshot with
  generated hero IDs crashes before any s2c 1118 or stream. Changing only
  hero IDs to `ffff` restores hero selection; changing only hashes does
  not. A valid client-selected pair then renders the local hero portrait.
  The truncated JWT identity was not necessary to change for this fix;
  the current encoder nevertheless preserves the available 64-byte region.
- **Cadence and lock:** captured snapshots arrive around 2.5 Hz; later
  snapshots show 7.0→0.0 and flags `0101`. A single pre-pick snapshot
  **does render a functioning hero picker** and the client interpolates
  its countdown. The earlier claim that a silent snapshot stream alone
  explains a dead picker is disproved. Clicking Lock In sends c2s 1123
  (6 B zeros). Current local code acknowledges selections, updates only
  the local slot on lock, and streams the countdown; the post-lock
  gameplay transition is still open. Do not equate this with full join
  completion or emit fabricated 1011 hero blocks before a selection.
- Corpus c2s order remains 1000 → 1112 → 1131 → 1118 (selection) →
  1123 (lock) → 1119 `[f32][00 00]` → 1134 → 1137
  `[u16 0][u32 eid][01 00]` → 1133. Only through 1123 is live-verified
  with the current local implementation; the meaning of 1119 needs
  additional evidence.

**Post-lock world-init exchange closed (2026-09-06, ACK-precise trace of
vgfull.pcap; implemented in `server/match_server.py` + `server/roster.py`).**
Method: for every c2s frame, the TCP ACK of the segment carrying it names
exactly how many s2c bytes the client had received — causality without
timestamp guessing. Two corrections of the 2026-09-06 morning readings are
included (1119 semantics; 1006 +168). Sequence, measured:

- **c2s 1123 + c2s 1119 ride one TCP segment** (lock + commit, one UI
  action). 1119 is `[u32 committed hash][00 00]` — NOT a generic confirm
  and not an f32: the client resolves the loadout at lock time and sends a
  hash *different* from its clicked 1118 pair (corpus: clicked
  `(925, 2fd7245d)`, committed `4260123e`). The committed hash replaces the
  clicked hash everywhere downstream (1113 slot +13, 1006 +168, 1011 +4).
- s2c answer to the lock: **1113 (slot 0101, clicked hash) → s2c 1123 echo
  (6 B zeros) → 1113 (committed hash) → s2c 1119 echo `[u32][00 00]`**.
  Countdown still shows the pick pair (296.5/300.0) at this point.
- **Bot assignment + lock countdown restart**: a burst of **8× identical
  1113 at (7.00, 7.0)** in which *every* slot is 0101 with its hero — bots
  carry fixed (hero, hash) pairs (396/bc155def, 244/f9fd7554, 399/4a490296,
  254/9d1ad5d3, 924/e25acb56; the 244 pair equals what a live client click
  produces, so the hash is a hero/skin property). The countdown then ticks
  at **~10 Hz** (vs ~2.5 Hz pre-lock) to 0.05.
- **At 0: 1006×6 (final) + 1132 (6 B zeros)** — then the wire is silent
  ~23 s while the client loads the map; the client answers with
  **c2s 1134 + c2s 1137 in one segment** (ack exactly through 1132).
- **World dump, one burst**: 1135 → 1006×6 → 1105 (6 B zeros) → per hero in
  *reverse* roster order: 1011 (750 B payload) + 1162×7 → **1087×39**
  (entity-allocation blobs: `[u32 eid][u32 eid][u16][u16][u16 new_eid][u16
  type]…` with sequential new entity ids — the strongest spawn-opcode lead
  for the §2 gate) → 1055×6 (`[u32][10 B zeros]`, derivation open) →
  s2c 1134 echo → s2c 1137 echo (`00 00 05 dc 01 00` = `[u16 0][u16 eid]
  [u16 0100]`) → **1116** (~1 Hz afterwards): 16 × `[u32 eid][u16 flags]` +
  6 B pad (102 B), local flag 0100, bots 0101.
- **1006 +168 correction**: it is the *committed selection hash* u32 (the
  "final XP-class f32" reading was the same bytes misread as a float).
  Local tail: 7×FNV1a("") (not 5) @+176..204, `ff ff 00 ff` @+204,
  `00 02 01 00` @+208, `00 00 00 01` @+212. Bot tail: zeros @+176, shared
  16 B guid @+180 (derivation unknown — md5/FNV of sentinel+match id do not
  match), `f1dedae3` @+200, `ff ff ff ff` @+204, `00 02 0<team> 00` @+208,
  `01 00 00 00` @+212.
- **1011 tail pinned**: `ff ff ff ff` @+741, slot-class u8 @+745 (slot 5 →
  05). Stat run +18..740 is hero-specific kit content, still unmapped.
- **1162**: values all 0.0; the 8 B tail carries the real flags; tag set =
  3 global + per-hero extras [Open].
- **Steady pre-game stream** after the dump: 1053×6 + 1086×6 every ~0.3 s,
  1087/1086 allocation runs, 1116 ~1 Hz. The full gameplay firehose
  (1067/1070/1054/1010…) starts only after **c2s 1133** (build-select close).
- Decoder note: `decode.walk_stream` now decrypts small 8-aligned bodies,
  so 1112/1119/1123/1131/1132/1105/1116/1134/1137/1055 appear as named
  opcodes in decodes (previously bucketed as raw opcode-0 frames).

**World layer live: map render + first server-controlled movement
(2026-09-06 evening, LDPlayer 4.13.4 against the local stack).** The
post-1137 entity stream is served as a real-time *tape* — every s2c frame
the corpus server sent in 0..12.5 s after its 1137 echo, paced by
`[u32 t_ms][u16 len][body]` records (`server/world_tape.py`; file outside
the repo). Live-measured results:

- The client accepts the tape bootstrap and **enters the match**: full HUD
  (minimap, 1:0x timer, 600 gold, ability bar), the three allied heroes in
  the spawn circle with nameplates and level-1 HP bars, camera follow on
  the local hero. No re-queue, no crash attributable to our bytes (the
  remaining random crashes are the known libhoudini segfaults — identical
  signatures in menu phases, see the mobile leaf).
- **c2s 1133 accompanies the "Choose a Build" overlay** — it fired 8–10 s
  into the tape replay, exactly when the overlay appears, so "open/announce"
  fits live behavior better than the archived "close" label [Open: the
  corpus client sends 1133 once; overlay dismissal used Android BACK and
  produced no c2s frame].
- **New c2s op-0 variant**: 6-byte payload `[f32 uptime][00 00]`, one every
  ~2 s during world load/play; the f32 rises ~2.0 per sample (client
  uptime/clock ticker). The corpus c2s keepalive class is the 2-byte-tick
  form; whether the corpus also carries the 6-byte form is unchecked
  [Open]. Transport lesson: parsing op-0 strictly as 2 B **kills the match
  socket mid-world-load** and the client re-queues — consume variants.
- **Movement slice closed live**: c2s 1012 `[f32 x][f32 y][6B 0]` → s2c
  1070 `[u32 eid][f32 x][f32 y][u16 0]` at a 0.2 s cadence moves hero eid
  1500 on screen (measured live: spawn −78.18/0.88 → target −70.25/3.01,
  camera follows). The spawn pair equals the f32s at 1011 stat-run +18 —
  the block's position fields are confirmed by behavior, not just bytes.
- Dump-order corrections from the tape decode (supersedes the bullet
  above): the dump burst is 1135 → 1006×6 → 1105 → (1011 + 1162×7) in
  reverse roster order → **1087 allocations (~241 entities over the 12.5 s
  window, 40 B blobs, sequential new eids from 0x7d6) → 1055×6 sits
  between the 1087 batch and the s2c echoes** (the earlier reading sent
  1055 right after the hero blocks — wrong place) → 1134/1137 echoes →
  delta stream 1053/1086/1067/1085/1164/1045 + 1010 full updates ×27.
  The 2592 B frames in that window are 1113 roster snapshots (the ~10 Hz
  lock countdown), not world state.

**1010 ENTITY_FULL_UPDATE measured on the wire (2026-09-06 night, match 1,
all 173 frames of the match decoded; second pass same night on the `.vgr`
match-5 corpus — all 6,472 1010s of 169,963 parsed frames — tools
`measure_1010*.py` in `$TEMP/vg_max/`, outside the repo).** Two payload
variants exist: **126 B** (no HP — all 173 of wire match 1; 821 of match 5)
and **122 B** (HP — 5,651 of match 5). Offset map of the 126-B variant
(evidence = per-offset distinct-value counts + cross-frame correlation
over all 173):

| Off | Type | Content | Evidence |
|---|---|---|---|
| +0 | u32 | entity eid (upper u16 always 0; 21 eids, range 292..372) | 21 distinct at +3, +0..2 constant 0 |
| +4 | u32 | entity-class id — **exactly 4 values** (`c10b41da`, `3df641a9`, `4dd5b7d0`, `eb39ce55`), each mapping 1:1 to an eid group (e.g. `eb39ce55` → {365..368}) | semantics [Open] (prefab/archetype hash is the guess) |
| +8 | u32 | global entity-write tick: +1 per consecutive frame (whole first burst 3539..3565 is +1/frame), jumps between bursts in step with the rest of the entity stream (Δ776 over 15.0 s = 51.7/s right after load; Δ264 over 25.0 s = 10.6/s later) → a shared write counter, not a fixed-rate clock; production rule [Open] | 173 distinct, strictly monotonic |
| +12 | f32 | x (observed ±88.5) | |
| +16 | f32 | z/height — **0.00707 in 167/173** (`3be7a8f8` = ground); rare elevated 0.067/0.174/0.487/0.808/1.747 | |
| +20 | f32 | y (0.51..42) | |
| +24 | f32 | facing **cos** | every (+24, +32) pair is a unit vector (all 56 non-default pairs |v|=1.0000) |
| +28 | f32 | 0.0 always | 173/173 |
| +32 | f32 | facing **sin** (idle default pair (0.0, 1.0) ×117) | |
| +36..+87 | — | **zero in 173/173** — no HP/maxHP fields in this shape (the `.vgr` row above is the 122-B variant below) | |
| +88..95 | 8 B | class tail: `01`×8 (114), `03 01 01 01`+u32 `xx xx b9 ff` (50), `d9 29 b9 ff e5 29 b9 ff` (9) | [Open] |
| +96..98 | 3 B | zeros (114) or one rotating `01` among the three (59) | [Open] |
| +112..115 | 4 B | `ff ff ff ff` (164); `00`/varied bytes in 9 effect-class frames | [Open] |
| +116 | u8 | second monotonic counter: +1 per frame in a burst (06..1e), small gaps (+2/+3) across bursts → own counter, not +8's low byte (3539&0xff=0x13 ≠ 06) | [Open] |
| +117/+118 | u8 | 0x01 / 0x00 always | 173/173 |
| +119..121 | 3 B | `01` then class pairs (`ff`,02 / `ff`,00 / `01`,02 / `01`,00…) | [Open] |
| +122..125 | 4 B | zero (observed frames) | |

**The 122-B HP variant (match-5 `.vgr` corpus, 5,651 frames).** Same
offset map through +32, then **+36 f32 current HP, +40 f32 maxHP** and
every tail field shifted −4 vs the 126-B layout (so the record simply ends
4 bytes earlier). Measured maxHP histogram = the §15.6/§15.8 tiers
(turrets 5000/3000, lane-minion 450-class); tails carried by the sample
template: +96..103 `03 0f 03 03 03 03 03 03`, +119..121 `01 ff 01`
[Open]. Length reconciliation of the old leaf row: 124 = 122+2 and
128 = 126+2 (opcode counted into the record); the old `id@+8` column is
the +8 entity-write tick, not an eid — its first-burst values 3539–3565
coincide exactly with the old table's sequential "static id" run
3539–3565, which is how placement names got joined onto tick numbers
[Interpretation].

- **Entity coverage**: 1010s exist **only for non-hero entities** — match 1:
  21 eids 292..372 (minions, jungle, camp statics at x=±71.28/y=12.93);
  match 5: 0 of 6,472 frames carry any hero eid. Combined census
  **0 / 6,645 hero-1010s across both corpora**: no 1010 for any hero eid
  (1500/1515–1519) anywhere, including the pre-1137 phase — **hero state
  rides 1011 blocks + the 1070 stream + 1053/1086 deltas; the real server
  never sends a hero 1010.** (Minions/statics do get 1010s, with HP in the
  122-B variant — the wave-1 measurement below falsified that guess:
  lane minions spawn via the 126-B 1010 + 1016 + 1070 + 1067 sequence.)
- **Live falsification of the hero-1010 extension (2026-09-06 14:58,
  LDPlayer against the local stack)**: the server emitted a measured-shape
  126-B hero 1010 for eid 1500 right after the tape completed; the client
  EOF'd the match socket **1 s after the first hero-1010** (first frame
  14:58:18 → EOF 14:58:19) and re-queued at 14:58:28. Conclusion: the
  absence of hero-1010 in the corpus is a real server behavior, not a
  capture gap; sending one breaks the client.
- **Pacing**: first burst of 25 coalesced frames at +6.43 s after the 1137
  ack (client-finish catch-up, one per tick), then per-entity refresh
  ranging ~1 s pairs (camp statics, teleport-class mirrored x re-spawns)
  to ~6 s (busiest statics, 40 frames/244.6 s).
- Emission (halcyon server): `roster.build_entity_full_update` writes only
  these two measured maps; the shared `world_tick` (+8) and `seq_1010`
  (+116) are per-stream deterministic counters (+1 per entity write / per
  1010). Hero 1010 is **default-OFF** behind `HALCYON_HERO_1010=1` (the
  live abort above); `HALCYON_NO_TAPE=1` skips the corpus tape so the
  sim-only world (1070/1116) can be tested live without deleting the tape
  file.

**Lane-minion wave spawn measured on the wire (2026-09-06 night, vg5
`.vgr` match-5 corpus, wave-1 window decoded from the 7034 flow; tools
`measure_1087*.py` in `$TEMP/vg_max/`, outside the repo).** The wave-1
throat is **not** a 1087 batch: lane minions spawn via the **126-B 1010
variant + 1016 move intent + 1070 position + 1067 state**, ten entities
per wave in five mirrored right/left pairs:

- **Grid**: wave 1 lands at **+22.974 s after the 1137 ack**, interval
  **exactly 25.0 s** (six starts pinned: 22.974 / 47.96 / 72.99 / 98.06 /
  123.14 / 148.22) — this **corrects the "60 s" wave reading** the
  HackedGlory table and the mechanics leaf carried. Pairs offset
  **0.00 / 0.92 / 1.94 / 2.86 / 3.88 s** inside a wave.
- **Eids**: allocated sequentially from 4610 across the whole match
  (wave 1 = 4610..4619, wave 2 = 4620..4629), **even = right side, odd =
  left side** — the same sequential-per-wave mechanic §15.6 saw as
  4314→5871 on the older corpus.
- **Per-pair burst order** (corpus raw order; right first, states
  left-first): 1010(right) → 1016(right) → 1070(right @ spawn point B,
  71.280/12.930) → 1010(left) → 1016(left) → 1070(left @ −B) →
  1070(left @ lane point A, ±70.841/12.788) → 1070(right @ A) →
  1067(left, state 00) → 1067(right, state 00); each pair's two 1067s
  flip to state `0f` **+0.10 s** after its own spawn.
- **Minion 1010 id-map (126-B)**: +0 = **spawner eid** (wave-1 pairs use
  366, 366, 367, 365, 365 — both sides of a pair share the spawner eid),
  +4 = class `eb39ce55` (the same class the §15.6 static table mapped to
  the spawner group 365..368), +8 = the new minion eid. Position,
  facing (0,0,1), +88 tail and +116 seq all match the 126-B map above;
  the seq byte continues the global 1010 counter. Side-dependent bytes:
  +96..98 (`00 00 01` right / `00 01 00` left) and +119..121
  (`01 01 02` right / `01 00 01` left).
- **1016 ENTITY_FLOAT (14 B)**: `[u8 seq][f32 x][f32 y][5×0]` — the seq
  byte is its own per-entity counter; the target is the walker's first
  lane point.
- **1067 ENTITY_STATE (14 B)**: `[u32 eid][u8 side][u8 01][u8
  state][7×0]` — side `01`=left / `02`=right (unvalidated values
  rejected by the builder), state `00`=spawned, `0f`=moving.
- **Walk**: 1070 heartbeat every **1.33 s** along the team lane polyline
  (right: 17 points from B to (1.500, 5.500); left: 18 mirrored points;
  list in `server/roster.py` `LANE_PATH_*`), measured ground speed
  **4.5 u/s**; heartbeats **continue at rest** after arrival (idle
  walkers keep emitting their stop position).
- **What is absent**: no 1087, no 122-B HP 1010, no 1053/1086 in the
  wave-1 spawn window — the "1087 minion-wave throat" phrasing above was
  the pre-measurement guess and is falsified; the 122-B HP variant
  belongs to statics (eids 292..400: turrets, shops, camps), which spawn
  in the dump phase, not with the wave.
- **Sim simplification to keep visible**: the halcyon director walks
  every pair the full polyline to (±1.5, 5.5); the corpus shows pairs
  2–5 halting earlier (x ±9.5..10.5) — per-pair stop positions are
  [Open] constants, not yet measured individually.

**Combat events measured on the wire (2026-09-06 night, vg5 corpus,
tools `measure_combat{,2,3}.py` in `$TEMP/vg_max/`).** The lane-minion
fight, for the T3 combat slice:

- **Engagement**: first minion-vs-minion 1054 at **+39.699 s** — attacker
  4610 (R) holding its path end (1.500, 5.500), victim 4611 (L) holding
  (−0.500, 5.500): **the waves walk to their endpoints and fight there**,
  distance exactly **2.00** (melee range; minion→minion hit distances
  p10 1.41 / median 3.16 / p90 6.08 / max 7.28 → ranged minions exist
  [Open: class split]).
- **1054 COMBAT_DELTA** (layout row above): minion-target frames carry
  the fixed 8-B tail `00 05 04 00 00 00 00 00` (400/400 sampled);
  minion-sourced damage is discrete (histogram peaks −28 ×232, −50 ×136,
  −33, −19, −39…; first-blood hit −19.4), consistent with
  `D = W/(1+A/100)` per class/armor [Open: per-class table].
- **Repeat hits**: gap between consecutive 1054s of one (src,tgt) pair —
  median **0.60 s** (p10 0.00 — multi-attacker volleys; p90 2.68).
- **Minion HP has NO wire source**: 17,037 1053s carry hero-family eids
  only; 0 of 6 minion-targeted 1053s; no 1011, 1162 or 122-B (HP) 1010
  frame ever carries a minion eid. The client computes minion HP itself
  from the 1054 stream (maxHP from local assets) — the input-stream
  model end to end. A server therefore only needs internal HP for death
  decisions; damage totals to death in the corpus exceed/undershoot the
  450 tier per victim (hero damage mixed in), so exact server-side HP
  accounting is [Open].
- **Minion death is two frames, same instant**: **1073 DESTROY then 1035
  DESPAWN** (`[u32 eid][u16 0]`, tail 0000), no overkill 1054 and no
  1068/1037/1072 frames (the longer chain in §15.8 above belongs to
  structure 3563, not minions). 216 minion deaths, eids 4610+ — first
  three at +51.66/+52.39/+55.48 s after living 26–30 s.
- **1045** (14 B, 4,274 frames): `[u32 a][u32 b][u8 flag][5×0]` where a/b
  are real eids (hero/minion/static; b = `ffffffff` in 66 frames = target
  cleared) — target/aggro events; flag census {0:1417, 1:1274, 7:371,
  8:337, 11:245, 10:237, 2:276, 3:85…} [Open: per-flag semantics].
- **1046** (22 B, sparse): `[u32 eid][f32 x][u32 0][f32 y][u8 kind][3×0]`
  — position-tagged event (projectile/impact-class), kind 00/03 seen
  [Open].
- **1016 during combat**: retargets arrive as `[u8 seq][f32 x][f32 y]`
  with **no eid field** — association is stream-context (the entity the
  surrounding frames speak about), e.g. retarget points at −0.5/5.5 =
  the victim's held position. Frame-order context rule [Open].

**Hero movement & 1070/1016 measured on the wire (2026-09-06 late night, vgfull.pcap match 1 + match 5 vgr, tools `trace_after_lock.py` and `measure_hero_movement.py` in `$TEMP/vg_max/`).** For T3 Slice 4 (hero movement server-authoritative):

- **1016 census for heroes is EXACT ZERO**: 0 of 32,640 frames in match 1 (`vgfull.pcap`), and 0 of 169,963 frames in match 5 (`vgr5frames.pkl`) carry opcode 1016 for any hero eid (1500, 1515–1519). 1016 is *never* emitted for heroes on the wire; it is strictly an entity-waypoint float block for minions, monsters, and camp statics.
- **Hero 1070 POSITION (14 B)**: `[u32 eid][f32 x][f32 y][u16 0]`
  - *Start anchor*: When `c2s 1012` is received from idle, the server emits the hero's current position as an initial 1070 anchor (measured reaction ~70–260 ms depending on packet arrival vs server tick).
  - *Monotone Cadence*: While moving, 1070 frames are emitted strictly every **0.20 s** (5 Hz). Speed is ~5.0 u/s (corpus spans 4.8–6.6 u/s).
  - *Arrival confirmation*: On reaching the destination, the server emits the exact target `(tx, ty)` with duplicate 1070 frames in the same instant (e.g. `pos=(-74.993, -2.195)` duplicated at `t=9.762s`).
  - *Idle silence*: Once arrived, **zero** 1070 frames are sent while stationary. (Corpus shows silence between tap segments).
  - *Anti-rubberband retargeting*: Subsequent `1012` taps during motion update the target seamlessly without snapping back to previous positions or re-emitting outdated start anchors.

**Their open problems vs our local artifacts** — the two archives are
complementary, not redundant:

| Open in HackedGlory (3v3 ARAL captures) | Answered here by |
|---|---|
| Minion/structure entity mapping (they tracked only hero ids 1500–1505) | §15.6 static table: 73 ids decoded, all 6 structure classes + shops placed and HP-tiered |
| Structure/objective HP | §15.6 tier table 2500/3000/3500/5000/10000/448 |
| **Kill/death detection** | **§15.8 death chain: 1054 overkill + 1073 destroy + 1035 despawn, ground-truthed on 3563** |
| **Absolute HP vs deltas** | **1010 122-B variant @+36/+40 (minions/statics only — heroes never get 1010) + 1054 deltas** |
| Wave timers | **corrected 2026-09-06: 25.0 s interval, 10 lane minions/wave (5 mirrored pairs)** — their 60 s / 12–14 reading was a coarser estimate; see the minion-wave block above |
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
