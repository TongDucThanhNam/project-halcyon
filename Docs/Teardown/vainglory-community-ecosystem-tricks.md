# Community Ecosystem Tricks & Leads (VGNA, HackedGlory, VGReborn)

## Unmodified-phone deployment review — 2026-10-23

**Operator direction:** prefer a VPN-based deployment for ordinary Android and
iOS installations; do not make repacking/Gadget a player prerequisite. The
earlier Android repack preparation stopped after an isolated decode, before
patching, signing, installation or launch. This direction is not a claim that
full unmodified-phone gameplay acceptance is already qualified. The follow-up
does establish original-Android bootstrap/session and match transport on one
owned phone, with native scalar/HUD acceptance still open.

**Source review, not a live service test.** VGReborn revision
`cabcbfba39d419b83325560dfe0e21efad77d12e` separates VPN transport from TLS:

- [Installer](https://github.com/VaingloryReborn/VGReborn/blob/cabcbfba39d419b83325560dfe0e21efad77d12e/mitm-monitor/install.sh):
  provisions WireGuard and mitmproxy, redirects tunnel TCP/443 to the proxy,
  and explicitly requires the client to trust its CA. Its `--ssl-insecure`
  option concerns the proxy's upstream verification, not the game's trust.
  Do not run this installer: its external forwarding and trust policy are not
  Halcyon's own-server-only design.
- [Monitor](https://github.com/VaingloryReborn/VGReborn/blob/cabcbfba39d419b83325560dfe0e21efad77d12e/mitm-monitor/src/index.ts):
  consumes RPC response logs and associates them with players. This is not an
  implementation of the authoritative simulation or cross-platform admission
  evidence for our exact clients.
- [WireGuard](https://www.wireguard.com/install/) offers Android and iOS
  clients. That establishes a shared transport candidate, not compatibility
  with Vainglory's certificate verifier.

**Trust boundary.** VPN/DNS/NAT can select a destination but cannot make an
untrusted certificate valid for the HTTPS hostname. The owned Android discovery
reports native CAPATH `/system/etc/security/cacerts`, peer verification enabled
and hostname verification enabled. Installing a user CA is therefore not an
established solution for this binary. Android's
[default user-CA policy](https://developer.android.com/privacy-and-security/security-config)
also must not be mistaken for proof of how a native TLS implementation behaves.
iOS supports [explicit trust for an installed certificate profile](https://support.apple.com/en-us/102390),
but the exact iOS client's trust/pinning behavior remains unmeasured.

### Preferred bounded experiment: own-domain bootstrap, no TLS interception

Selected flow (one Android's session/match transport verified below; iOS open):

```text
Original CE client -> owned WireGuard tunnel -> private DNS/bootstrap service
  HTTP preauth status-redirect -> rpc.<operator-owned-domain>:443
  HTTPS RPC with a publicly trusted certificate for that exact hostname
  session/notify URLs -> owned services
  announced gateway/heartbeat -> owned tunnel addresses
```

The local mobile record already establishes an HTTP preauth request and a raw
`host:port` bootstrap reply. `server/platform/local_stack.py:Handler._dispatch`
can serve that body. This justifies testing a different hostname; it does NOT
prove absence of client restrictions or later hard-coded fallbacks.
The legacy default in `_create_guest_player` is `https://rpc.kindred-live.net`;
session/notify/platform URLs also need coherent configuration. The new opt-in
`server/platform/endpoints.py` rewrites these named fields while preserving
tokens, paths and response shape. Changing only DNS or bootstrap is insufficient.

A certificate for an owned domain avoids impersonating the original RPC
domain. [ACME DNS-01](https://letsencrypt.org/docs/challenge-types/#dns-01-challenge)
allows certificate issuance without exposing the game service publicly.
The certificate chain and TLS negotiation require exact-client positive and
negative controls; the follow-up distinguishes what was actually measured.

Next gates, in order:

1. Prepare owned tunnel/DNS/firewall isolation, including IPv6, DNS escape and
   tunnel-loss behavior; do not use community/live game backends as upstreams.
2. On the unchanged Android client, prove bootstrap chooses the owned hostname
   and a valid-certificate RPC succeeds; wrong-host/wrong-CA controls must fail.
   Preserve network/server evidence without screenshots or in-process hooks.
3. Prove fresh-guest/session/notify and match admission, then phone-attributed
   ordinary input/outcomes. Keep native presentation acceptance separate.
4. Repeat on an identified owned iOS build; Android success is not iOS evidence.
5. Only then package per-player VPN configuration and private-server setup.
   Do not distribute game payloads or add a custom VPN app before the shared
   transport is qualified. Gadget remains a separate research option, not the
   selected player deployment route.

### Owned Android execution — 2026-10-23

**Observed, not a release claim:** unchanged CE Android 4.13.4/build 147219
on the unrooted Redmi Note 11 `af339028` reached the owned platform through
WireGuard. No APK/OBB modification, uninstall, injected library, user CA,
system-CA/hosts edit, screenshot or video was used. Google Play sign-in was
cancelled through its identified Android UI controls; it is not an upstream
dependency for this test. Native game menu controls expose no accessibility
labels, so ordinary menu entry needs operator assistance, not guessed taps.

- Operator-owned RPC name: `rpc.halcyon.tongducthanhnam.id.vn`. A public
  Let's Encrypt RSA certificate was issued with DNS-01 using lego 5.5.2;
  staging first, then production. Temporary TXT records were cleaned. No
  game-facing public A/CNAME record, Cloudflare tunnel or Internet listener
  was added. Existing Cloudflare applications were left unchanged.
- Certificate issuer YR2; expires **2027-01-21 03:22:06 UTC**. Renewal is not
  scheduled. Certificate/key/account material stays under ignored
  `Local/runtime/phone-acme/`; never put private keys into documentation/Git.
- `server/platform/phone_vpn.py` uses the optional pinned `mitmproxy_rs`
  **userspace WireGuard transport API**, not its TLS-intercepting proxy.
  One peer, host `192.168.1.3:51820/UDP`, virtual service `10.77.0.1`, phone
  `10.77.0.2`/`fd77::2`; both default routes go into VPN. Only local DNS and
  TCP 80/443/7100/2112 can reach fixed loopback services. Unknown DNS and all
  other destinations are refused; there is no upstream Internet forwarding.
- Live integration caught a wrong API assumption: `original_dst` is the
  **outer** WireGuard UDP destination; `sockname` is the inner application
  destination. The initial run denied valid traffic (failed closed). The
  corrected run records both and successfully serves DNS/opaque TLS. Tests
  now distinguish these addresses instead of assuming they are identical.
- Android's secure settings show WireGuard always-on, lockdown `1`, empty
  bypass whitelist. Connectivity reports both default routes, private DNS
  `10.77.0.1`, `bypassable=false`, UID range `0-99999` including game UID 10290.
  With the tunnel deliberately off, shell TCP attempts to the owned LAN host
  and virtual service both failed immediately with `Permission denied`.
  After restoration, the own-domain HTTPS check succeeded. This is a bounded
  observed/configuration check, not exhaustive per-app leak certification.
- Android system `curl` verified the public chain with
  `/system/etc/security/cacerts`, including TLS 1.2/ECDHE-RSA-AES128-SHA.
  A wrong hostname was rejected (exit 60); unknown DNS was rejected (exit 6).
  Host checks additionally reject a wrong CA. These negative controls are
  **not** measurements of Vainglory's native verifier on deliberately bad
  certificates; that exact-client negative-control gate remains open.
- In the first bounded launch, the actual game used HTTP preauth, then
  `getPlayerForGuestAccount`, `startSessionForPlayer`, `getPlayerInfo`,
  `getSkinManifest`, `getTalentsData` and `update` on the owned hostname's
  TLS listener 9443. WebSocket `/notify` upgraded and sent replies. The game
  remained alive; a Google Play dialog temporarily backgrounded it. A saved
  guest was used: **fresh-guest UI admission has not been demonstrated**.
- After operator-assisted ordinary menu entry, `joinLobby` reached the same
  owned TLS listener. Gateway 7100 routed the phone's connection to a loopback
  match; selected hero 265 is Skye, owner EID 1500/slot 0, tagged identity
  `devtag:a73f79d8ba28`. The server observed roster lock, readiness 1134/1137,
  world initialization, build-select close 1133, then progressing simulation
  ticks. Its application journal records ordinary movement 1012 and shop
  requests 1081 from that connection. The operator separately reported entry
  into the match. This establishes **phone-attributed local match transport**,
  not a native HUD/scalar guard, smooth movement, combat fidelity or a completed
  match. The logged donor 1011 stats for Skye remain an explicit measurement
  gap; they were not altered to obtain transport success.

Evidence: ignored `Local/evidence/phone-vpn-domain-20261023-110956/`:
`public-certificate-check.json`, `phone-transport-check.json`,
`phone-public-tls12.txt`, `phone-wrong-host-rejected.txt`,
`phone-tunnel-down-owned-lan.txt`, `phone-tunnel-down-virtual.txt`,
`connectivity-before-game.txt`, `original-launch.json`,
`original-launch-rpc.jsonl`, `vpn-inner.jsonl`, and `summary.json`. Live match
inputs are in `input-journals/inputs-7776661c7b444fd89e908d7ac7a56b2d.jsonl`;
the follow-up below closes and exactly replays this artifact.
The initial `vpn.jsonl`
is retained as failed-closed evidence, not replaced. Raw journals may contain
session material and remain local. `Local/runtime/phone-stack/` is separate
from the emulator runtime. All platform/gateway listeners bind loopback.

Remaining gates: native nonvisual WORLD/HUD acceptance and phone-attributed
gameplay outcomes; fresh-guest flow; exact-client bad-certificate controls;
iOS client/version and containment;
per-player profiles/multi-peer service; off-LAN hosting, renewal and operational
packaging. Transport success is not deterministic-gameplay or fidelity acceptance.

**Closed-session follow-up, same day:** after the operator confirmed the phone
worked, the game was deliberately stopped and the existing match lifecycle
closed its journal with a successful footer. No source changes occurred during
recording/replay. The existing command
`python Tools/run_scenarios.py --mode replay --journal <closed-journal>` passed
both independent seeds: 10,780 operations, 374 live checkpoints, 54,488 events,
final tick 9,855; all six event/state/recipient/send-outcome artifacts are exact.
Evidence: `Local/evidence/phone-vpn-journal-1792731479464021600/` (`close.json`,
`replay/summary.json`, `semantic-audit-v2.json`, `skye-a-cancel-test.txt`).
There were zero recipient send errors before the recorded client removal;
2,698 afterward during shutdown are retained, not counted as in-play loss.
The native Skye A cancel input is `1041` with null target/action 1 and uses
`1045`, not the ground-cast `1046` echo; the initial audit's classification was
corrected without changing gameplay or weakening a check. The session lasted
about 538 seconds from first recorded operation to close, not a complete
natural match or a 30-minute stability claim. Native presentation/fidelity and
the remaining deployment gates above stay open.

## Research direction correction — 2026-09-12

The operator requested structural understanding of the client and server,
not another campaign of watching client videos. **Use decoded data, identified
native consumers and controlled local replay as the primary research loop.**
Video is supplementary evidence for presentation after a concrete question
has been narrowed. Further ZCode/native-agent delegation is disabled by the
operator; the parent owns subsequent investigation.

The phone work did not establish an independent gameplay reference. A normal
solo/bot menu route and recording transport were exercised, but the
movement/minimap qualification remains incomplete. Do not keep creating
recorder revisions or repeated UI attempts as a substitute for protocol work.

### What the community sources actually contribute

Primary sources were rechecked on 2026-09-12. Their claims remain leads until
matched to our exact build and evidence; agreement with our own derivative
notes is not independent corroboration.

| Source | Useful contribution | Limit |
|---|---|---|
| [HackedGlory protocol writeup](https://github.com/a1cnore/HackedGlory/blob/main/reports/protocol_decryption_writeup.md) | Its transport recovery followed concrete receive, dispatch and key-derivation call chains using static analysis plus existing traffic; it explicitly reports that runtime hooks were unnecessary for that result. | Its older semantic table conflicts with later local measurements. Reuse anchors and methods, not every opcode label. |
| [HackedGlory decoder benchmark](https://github.com/a1cnore/HackedGlory/blob/main/mitm/match_decryption/autoresearch.md) | Automated reconstruction of scoreboard timelines from recorded matches. | The scored target is levels, K/D/CS, gold, XP and winner information. That is neither a recovered simulation nor proof of ability/AI fidelity. |
| [HackedGlory CFF0 research](https://github.com/a1cnore/HackedGlory/blob/main/reports/cff0_decryption_and_balance_extraction.md) | Named definitions and pointer-linked subobjects are an entry point into ability/data structure. | Our mechanics-matrix audit already found pollution in the generated balance database. Reproduce values and links from owned source bytes, with revision/type checks. Do not reopen the solved codec or use heuristic field names as facts. |
| [HackedGlory Android implementation status](https://github.com/a1cnore/HackedGlory/blob/main/mitm/vg_unlock_android/README.md) | A loader shim and no-op control offer a possible route around a particular loader problem. | The documented control works on tested devices; active hook families still fail on one test device. This does not qualify our phone or translated LDPlayer process. |
| [VGNA client](https://client.vgna.net/) | Advertises stat collection, spectator support and a native Windows Replay Hub. These are leads for transport/replay integration and reusable match data. | The page does not expose the authoritative simulation or establish a supported raw-data export API. Do not infer access to its private backend or install a client merely to repeat visual observation. |

### Preferred investigation loop

1. **Start from an unresolved mechanism and a known anchor.** For the client,
   trace an identified opcode handler or named CFF action into the constructor,
   state write and update/destructor path it actually calls. Record binary
   digest, platform, function address, field offsets and evidence. Our wire
   leaf already names handlers, and `Tools/Teardown/inspect_ability_actions.py`
   joins PTCH action-vector entries to native ability names. This is bounded
   analysis of a known path, not whole-program decompilation or an unanchored
   RTTI search. Revalidate any historical address before use; iOS, Android and
   Windows addresses/layouts are not interchangeable.
2. **Mine owned traffic automatically.** Reuse the existing PCAP/VGR readers
   and inspectors. Index by match, direction, EID, actor-slot lifetime, action,
   rank, item state and timestamp. Extract every candidate episode rather
   than hand-driving one cast for each model turn. Preserve missing-state
   flags and select a different match for validation. S2C-only VGR permits
   output/state analysis; it does not supply missing C2S inputs or a complete
   simulation initial state.
3. **Test the client contract locally.** Reuse the current gateway, world-tape
   loader and trace facilities. First prove unmodified replay reaches the
   relevant client state. Then vary one dependency while preserving required
   bootstrap, entity/slot ownership and chronology. Record the resulting
   state/handler outcome. This can establish which message creates an actor,
   starts presentation, changes a pool or releases a slot. A crash following
   arbitrary packet deletion is not a semantic result.
4. **Infer server decisions separately.** Turn recurring official episodes
   into explicit candidate rules: target eligibility, first-hit delay, pulse
   interval, cancellation condition, retargeting and expiry. Compare hypotheses
   on held-out episodes with compatible initial conditions. Only genuinely
   missing discriminating evidence should trigger another ordinary-client
   session, using passive bidirectional data from our own connection where
   available. Our own headless server remains the place for custom clients,
   active packet experiments and deterministic regression tests.
5. **Use runtime observation only to resolve a named missing field.** First
   qualify a matching native ABI/build and resolve the exact loaded module.
   A no-op attach is insufficient. If qualified, a narrow decoded-message or
   post-handler state observer is more informative than pixels. The corr32
   LDPlayer run did not find `libGameKindred` in either enumerated realm;
   that route is parked. No blind reattach loop or automatic repack follows
   from this research direction.

The output of each loop is a small protocol/state contract with source
provenance, an executable local check and separately listed server-rule
unknowns. Count resolved mechanisms and contradictory observations, not
screenshots, tool revisions or nominal decoder coverage.

### First bounded question

**2026-09-12 result:** the [Skye C contract review](../Plan/solo-sandbox-abilities.md#2026-09-12-skye-c-native-contract-and-two-production-corrections)
reproduces ten field lifetimes and 332 owner-attributed hit/damage associations
from the existing owned cache. Native branches and the production event stream
exposed two corrected defects: activation published after damage, and the wrong
cluster/line choice at the exact two-unit threshold. Following the actual native
vtable also showed that a tempting 2.5 constant reaches an accessor that ignores
it in this client; it is not a recovered operational damage radius. This is a
completed first analysis loop, with 37 passing checks and two-process headless
repeatability, while geometry, damage classification and reconnect remain open.

**Skye C: which native actor/state connects the cast to the persistent field,
and what controls its start and retirement?** This addresses the existing
publication-to-pulse and reconnect gaps without searching the whole engine.

Reuse the Skye action/constant evidence in
[the ability leaf](../Plan/solo-sandbox-abilities.md),
`inspect_ability_actions.py`, `inspect_ability_constants.py`, and the owned
VGR/trace parsers. Join native action 4, relevant actor publications, damage
pulses, cooldown and removal records by identity/lifetime. Inspect only the
identified consumers and definition references needed to distinguish those
states. Treat temporal proximity as a candidate relationship until a consumer
or controlled local intervention supports it.

Deliver: one dependency diagram, a byte/field provenance table, candidate
episodes with confounders and one local contract check. Do not claim that a
client presentation timer computes authoritative damage, or that reproducing
recorded damage demonstrates the server algorithm. If a required native path
has no verified anchor, preserve that precise gap and continue the available
offline corpus work; do not fall back to another video automation campaign.

### Corrections to older framing

The original Trick 8 below remains an unaccepted historical proposal. Its
zero-noise/one-action-one-frame assertions and remote custom-client plan are
not the research strategy. The “no binary anchors” stopped-avenue note describes
an earlier unanchored search; it does not erase subsequently documented opcode
and action-table anchors, and does not authorize reopening every binary path.
The runtime leaf's former “active instrumentation” and “zero drift oracle”
claims are corrected there. Client code can reveal parsing, state transitions,
prediction/presentation and any demonstrated shared helpers; it cannot by
itself prove undisclosed authoritative rules.

## Evidence review — 2026-09-07

The original proposal below is retained as an operator-supplied research lead,
not an accepted protocol specification. Its descriptions of community hooks
do not by themselves establish a cause for Halcyon's client crashes. The
current local trace identified a concrete server exception: Adagio's A tried
to attach state to a slotted minion. That defect now has a regression test.

The headless-client idea can reduce the number of rendered clients in a
controlled test, provided authentication, matchmaking, readiness, heartbeat,
and input handling are implemented. These specific claims need correction:

| Proposal claim | Current evidence |
|---|---|
| Any UUID creates an accepted SEMC session; `ROOM_999` selects a private lobby | Unverified. Our local platform accepting an identity does not establish remote acceptance or the semantics of a room code. The [SEMC roadmap](https://www.vainglorygame.com/news/vainglory-community-edition/?p=27342), published 2020-04-01, describes planned local profile data and party codes, not this authentication or lobby contract. |
| Blowfish key is `MD5(SALT || matchId)` | Matches `server/wire.py`: the 64-byte constant plus the ASCII match ID. Framing and the implementation's word ordering are also required. |
| Keepalive is two empty bytes | Incorrect. The decoded body is opcode zero, marker `46 d6`, a u16 counter, and two zero bytes; use the measured framing/cipher and heartbeat handling. |
| `1157` upgrades skill A | Incorrect for the measured mobile flow: `1078` upgrades the selected slot. `1157` occurs in the build-selection exchange. |
| Item activation can be handled as another ability slot | Native targetless item use is `1096`, carrying an owned inventory-instance ID. Repeated Fountain and Flask captures tie this request to their native effects. `1098` carries a ground position and item-instance ID. A server echo is an acknowledgement, not proof that the cooldown permitted activation. |
| Ground skills use `1012`; cooldown uses `1086` | `1012` is movement. Measured casts include `1041`, `1042` and `1102`; `1042` has three floats followed by slot/flag. Cooldowns are `1162`: EID, tag, remaining, duration, six state bytes. |
| All skill CC is encoded in `1054` | Not established. `1054` carries victim/attacker and signed combat damage. Effect state and presentation must be traced separately. |
| A lethal minion hit goes straight to `1073`/`1035` | The 83 measured removal chains first carry `1072` death attribution, retain the corpse for approximately 3.8 seconds, then destroy/remove it. The compact actor slot stays occupied until removal. |
| Five idle heroes produce zero noise and one action per frame | Incorrect. Waves, structures, creatures, resource ticks, timers and other world messages continue. One action can emit many frames; TCP segmentation is not a gameplay event boundary. Compare idle/cast windows and repeated controls by EID, tag and match time. |
| Attacking a dummy at the enemy fountain isolates skill damage | Fountain damage and healing confound the experiment. Put an owned, controlled target outside both fountain zones and other aggro ranges. |
| Custom socket clients on a remote backend comply with Rule 1 | Conflicts with the repository's explicit no-packet-injection boundary for backends we did not stand up. This is a project-scope constraint, not a legal determination. |

Use headless clients against our own server for multi-client consistency,
reconnect, input ownership, and replay tests. Such output validates Halcyon's
implementation; it cannot independently recover SEMC's simulation rules.
Native-rule discovery continues from existing own captures and passive
observation of ordinary client play. A useful experiment records a baseline,
one named action, actor identities, rank/items/HP/energy, decoded responses,
and repeated control trials. See [sandbox acceptance](../Plan/solo-sandbox.md)
and the measured [ability](../Plan/solo-sandbox-abilities.md),
[item](../Plan/solo-sandbox-items.md), and
[lifecycle](../Plan/solo-sandbox-navigation.md) records.

---

Tài liệu mổ xẻ chuyên sâu các kỹ thuật, phát hiện và "tricks" được tìm thấy từ 3 dự án tiêu biểu trong cộng đồng Reverse Engineering Vainglory Community Edition (CE):
1. **VGNA (Vainglory North America)**: Phân tích trực tiếp từ file nhị phân hook `VGNAFeatures` (853 KB Mach-O 64-bit dylib) và log phát hành kỹ thuật `releases.json` (v1.02–1.11).
2. **HackedGlory (`a1cnore/HackedGlory`)**: Phân tích từ `hg-rpc_schemas.json`, `method_schema_sheet.md`, `offline_protocol_surface.md` và `hg-mock_platform_server.py`.
3. **VGReborn (`VaingloryReborn/VGReborn`)**: Phân tích từ `vgreborn-actionDispatcher.ts` và kiến trúc MITM proxy.

Tài liệu này đánh giá cơ chế của từng trick và xác lập lộ trình áp dụng trực tiếp vào **Project Halcyon** (đặc biệt cho T1 Matchmaking, T3 Hero Skin/Map, và bài toán thu thập **Real Data** cho Skill/Combat).

---

## 1. Mổ xẻ 8 Tricks & Phát hiện Kỹ thuật

### Trick 1 (VGNA): Mở khóa Skin trong trận qua `native_alt_skin_selection` & Spawn Hash Injection
*   **Bối cảnh tại Halcyon:** Ở Update 18 (`Docs/Plan/next-steps.md`), chúng ta đã mở khóa full danh sách tướng trong Draft qua `canUseAllHeroes: true` và `unlocks`, nhưng phát hiện tab Skins trong Draft bị mờ xám (greyed out), không phản ứng khi bấm vào.
*   **Cơ chế phát hiện từ VGNA (`VGNAFeatures`):**
    *   Trong bản CE 4.13.4, SEMC đã vô hiệu hóa callback chọn skin tiêu chuẩn trong giao diện draft gốc (`DraftController`).
    *   VGNA phát hiện client vẫn duy trì một đường rẽ nội bộ gọi là `native_alt_skin_selection`. Họ cài 4 hàm hook vtable:
        `_vgna_draft_skin_select_primary_hook`, `_vgna_draft_skin_select_secondary_hook`,
        `_vgna_alt_skin_select_primary_hook`, `_vgna_alt_skin_select_secondary_hook`.
    *   Khi người chơi chọn skin qua đường rẽ này, VGNA trích xuất mã băm `skin_hash`:
        `[vg_replay] Limited Edition alt skin selection source=%s le=%d hash=%08x`
    *   Tại thời điểm tải trận (loading screen), VGNA không tìm cách gọi RPC lên server nữa mà inject trực tiếp hash này vào struct khởi tạo hero spawn:
        `[vg_replay] Limited Edition hero spawn left engine-updated hash=%08x marker=limited-edition-spawn-scope-v1`
*   **Ứng dụng cho Halcyon:**
    *   Chấm dứt việc tìm kiếm API equip skin ở tầng Menu/RPC.
    *   Khi xây dựng gói tin nạp thực thể hero ở T3 (khối 1011 stat-run và 1006 PLAYER_INFO), server Halcyon có thể map trực tiếp mã hash của skin mong muốn vào trường committed hash (`+168` của 1006 / `+4` của 1011). Client sẽ tự nạp model skin tương ứng khi render màn hình load trận.

---

### Trick 2 (VGNA): Kích hoạt 6 Bản đồ 3v3 Halcyon Fold qua Preferences VTable Injection
*   **Cơ chế phát hiện từ VGNA:**
    *   Bản CE 4.13.4 chứa toàn bộ 6 theme bản đồ 3v3 (Mùa Thu, Mùa Đông, Mùa Xuân, v.v.) trong file nén dữ liệu cục bộ, nhưng bị khóa cứng ở map mặc định.
    *   VGNA can thiệp trực tiếp vào bảng ảo (vtable) của giao diện cài đặt:
        `[vg_replay] native 3V3 MAP row inserted into Preferences vector` (tại `vtable 0x14a6920 slot +0x88`).
    *   Thao tác này chèn một dòng tuỳ chọn mới vào danh sách Preferences gốc của game. Khi người dùng chọn, client ghi cờ `vgna_map_variant` và cập nhật trỏ file asset map trên đĩa trước khi khởi động engine render trận đấu.
*   **Ứng dụng cho Halcyon:**
    *   Giữ nguyên server sim T3 chạy trên cùng toạ độ map 3v3 tiêu chuẩn.
    *   Cho phép người chơi đổi theme bản đồ yêu thích trên client bằng cách thiết lập cấu hình asset cục bộ mà không sợ desync toạ độ với server.

---

### Trick 3 (VGNA): Quiesce Observers tránh Crash Null Pointer (SIGSEGV) khi Dodge Draft
*   **Cơ chế phát hiện từ VGNA:**
    *   Khi có người thoát trận trong pha chọn tướng (dodge), `DraftController` layout destructor của `GameKindred` sẽ được gọi để giải phóng tài nguyên.
    *   Nếu các observer (chat, telemetry, log) vẫn còn đăng ký trong vector observer của engine, lúc game chuyển cảnh về Menu hoặc sang Loading, con trỏ treo sẽ gây lỗi `SIGSEGV` (crash văng app).
    *   VGNA triển khai `native-chat-row-retirement-guard-v1`: Tự động thu hồi và đánh dấu offline các wrapper trước khi destructor của `GameKindred` được thực thi.
*   **Ứng dụng cho Halcyon:**
    *   Giải thích nguyên nhân các đợt crash ngẫu nhiên libhoudini/SIGSEGV khi chuyển đổi màn hình accept/draft ở §10 và §14 của `next-steps.md`.
    *   Khi server gửi lệnh reset hoặc hủy draft, server phải gửi tuần tự thông báo kết thúc trạng thái trước khi đóng socket hoặc chuyển state FSM.

---

### Trick 4 (HackedGlory): Giải mã bản chất `equipToSlot` — Không dùng cho Skin
*   **Bối cảnh tại Halcyon:** Ở Update 18, chúng ta đặt nghi vấn liệu client có dùng RPC `equipToSlot` để trang bị Skin hay không.
*   **Cơ chế từ Schema HackedGlory (`hg-rpc_schemas.json`):**
    ```json
    "method": "equipToSlot",
    "request_fields": ["equipToSlot", "player_global_loadout", "hat"],
    "response_fields": ["thumbsUp", "smile", "frown", "toast", "charm", "hat", "social_ping_pack"]
    ```
    *   `equipToSlot` thuần túy quản lý các vật phẩm trang trí phụ trợ: Mũ (hats), bùa chú (charms) và gói biểu cảm ping mạng xã hội (thumbsUp, smile, frown, toast).
*   **Ứng dụng cho Halcyon:**
    *   Loại bỏ hoàn toàn giả thuyết `equipToSlot` dùng cho skin, đóng nhánh nghiên cứu sai hướng.
    *   Nếu muốn mở tính năng biểu cảm ping (social pings) cho người chơi, ta chỉ cần trả schema này trong `getPlayerInfo.player_global_loadout`.

---

### Trick 5 (HackedGlory): Bẫy thời gian thực `timeout_sec: 2` của `acceptMatch`
*   **Cơ chế từ Schema HackedGlory:**
    *   Trong bảng ánh xạ method, `acceptMatch` có trường `"timeout_sec": 2`.
    *   Client đặt giới hạn thời gian chờ cực gắt: Nếu sau khi bấm Accept mà trong vòng **2.0 giây** server không phản hồi xác nhận, client sẽ coi như thất bại và hủy kết nối.
    *   Các hàm khác có độ trễ thoáng hơn: `getSkinManifest` (10s), `queryPendingMatch` (90s).
*   **Ứng dụng cho Halcyon:**
    *   FSM tự động trong `server/platform/local_stack.py` phải trả lời kết quả `acceptMatch` tức thì (< 200ms), không để dồn tác vụ I/O gây trễ quá 2 giây.

---

### Trick 6 (HackedGlory): Cơ chế Client Feature-Gate (`FUN_100131560`)
*   **Cơ chế:**
    *   Client CE chứa hàm kiểm tra tính năng `FUN_100131560`. Một số màn hình và nút bấm bị vô hiệu hóa sẵn trong mã máy client bất kể phản hồi của server.
    *   HackedGlory sử dụng hook `vg_unlock` để ép hàm này luôn trả về true nếu muốn can thiệp sâu vào giao diện PC.
*   **Ứng dụng cho Halcyon:**
    *   Giúp phân định rõ: Đâu là tính năng server có thể mở khóa qua `answers.json` (như danh sách tướng, thông số vàng, elo), và đâu là tính năng bị client chặn cứng ở tầng mã máy.

---

### Trick 7 (VGReborn): Cấu trúc Envelope `queryPendingMatch`
*   **Cơ chế từ `actionDispatcher.ts`:**
    *   Client yêu cầu phản hồi `returnValue.isValid: true` đi kèm mảng `responses` liệt kê trạng thái của các người chơi đã matched.
*   **Ứng dụng cho Halcyon:**
    *   Đã áp dụng thành công trong `Docs/Plan/next-steps.md` §7, giúp hoàn thiện 100% tầng T1 Queue.

---

### Trick 8: Chiến lược Thu thập "Real Data" cho Di chuyển, Combat và Skill Casting bằng Headless Bot Swarm

#### Vấn đề cốt lõi: Chúng ta đang thiếu Real Data gì?
Hiện tại Project Halcyon đã giải mã và xác minh:
1.  **Di chuyển (Locomotion):** Đã có Real Data đầy đủ (`c2s 1012` toạ độ click → `s2c 1070` position updates nhịp 5 Hz / 0.20s). Hero đã di chuyển mượt mà trên màn hình.
2.  **Lính (Minions):** Đã có Real Data (`1010 126-B` + `1016` waypoint + `1070` + `1067` nhịp 25.0s, combat `1054`, chết `1073`+`1035`).
3.  **CÁI CÒN THIẾU:** **Cơ chế thi triển Kỹ năng (Skill/Ability Casting)**:
    *   Khi người chơi bấm Skill A, B, Ult: Client gửi `1012` (skill định hướng mặt đất) hay `1041` (skill tức thời không mục tiêu)?
    *   Server SEMC thực tế trả về gói tin gì để kích hoạt hoạt ảnh (animation), hiệu ứng hạt (VFX), và thời gian hồi chiêu (cooldown)?
    *   Trong các trận đấu thực tế đông người (`vgfull.pcap`), hàng trăm gói tin bay hỗn loạn cùng lúc khiến việc cô lập *"đâu là frame trả về khi Celeste bấm Skill A"* cực kỳ khó khăn nếu không có môi trường thử nghiệm sạch.

#### Giải pháp từ Trick 8 (Headless Bot Swarm):
Tận dụng ý tưởng của VGReborn kết hợp với bộ giao thức T1/T2 mà Halcyon đã hoàn thiện:
```
[5 Headless Python Client Bots] + [1 Real Game Client trên Emulator]
  → Cùng tham gia vào 1 phòng Custom hoặc Hàng chờ CE trên máy chủ chính thức SEMC
  → Trận đấu bắt đầu: 5 bot hoàn toàn đứng yên (AFK) tại nhà chính
  → Người chơi trên Emulator thực hiện ĐƠN LẺ từng thao tác:
      1. Bấm tăng điểm chiêu A (ghi nhận opcode 1157).
      2. Bấm dùng chiêu A vào khoảng trống (ghi nhận c2s và s2c phản hồi duy nhất).
      3. Bấm dùng chiêu A trúng 1 bot đứng yên (ghi nhận gói tin trừ máu 1054 + cooldown 1086 + hiệu ứng).
```

#### Ưu thế vượt trội của phương pháp này:
*   **Dữ liệu siêu sạch (Zero Noise):** Không có người chơi lạ di chuyển, không có lính đánh nhau chen ngang. Mỗi frame mạng thu được qua Wireshark tương ứng 1:1 với hành động vừa bấm.
*   **Tuân thủ tuyệt đối Boundary Rule 1:** Không tấn công, không scan, không can thiệp server SEMC. Đây là 6 kết nối client hợp lệ chơi 1 trận đấu thông thường trên hạ tầng CE công cộng.

---

## 2. Bảng tổng hợp Lộ trình Triển khai

| Trick | Bản chất | Độ ưu tiên với Halcyon | Trạng thái triển khai |
|---|---|---|---|
| **Trick 1: Skin Hash Spawn Injection** | Server T3 metadata | **Cao** (Giải quyết Hero Skin) | Đang mở ở §18; chuyển từ tìm RPC sang bind hash tại T3 world dump. |
| **Trick 2: 3v3 Map Theme Switcher** | Client Asset config | Trung bình (Tùy biến bản đồ) | Áp dụng khi hoàn thiện phần map 3v3 cốt lõi. |
| **Trick 3: Observer Quiesce on Dodge** | Client Lifecycle | Đã giải quyết gián tiếp | Lưu ý trong state machine của match server. |
| **Trick 4: Loại trừ `equipToSlot`** | Schema RPC | **Đã hoàn thành** | Đóng nghi vấn, không tốn thời gian vào `equipToSlot`. |
| **Trick 5: `acceptMatch` 2s timeout** | Protocol Timing | **Đã áp dụng** | FSM của `local_stack.py` phản hồi tức thì < 200ms. |
| **Trick 6: Feature Gate Analysis** | Client Internals | Tham khảo | Dùng để phân định giới hạn can thiệp của server. |
| **Trick 7: `queryPendingMatch` Schema** | Protocol Schema | **Đã áp dụng** | Nền tảng của T1 Matchmaking hiện tại. |
| **Trick 8: Headless Bot Swarm Capture** | Đo đạc Thực nghiệm | **Cao** (Mở khóa Skill/Combat) | Kế hoạch dùng 5 bot giả để thu thập Real Data cho toàn bộ 55 bộ kỹ năng tướng. |
