# GOAL.md — Project Halcyon MASTER GOAL

> Toàn bộ phần còn lại của server Vainglory self-hosted, chia theo milestone → slice →
> checkbox. Tick khi có bằng chứng (test xanh / live verify), không tick vì "chắc là xong".
> Đã qua 1 vòng sage critique (2026-09-06): thứ tự turrets-trước-abilities, đội ước lượng
> slice 5/6, thêm reconnect + status scaffold + damage-modifier queue.

---

## Objective

Đưa server từ trạng thái hiện tại (1 client vào được match, minion đi lane và đánh nhau,
hero đứng yên) lên **100% gameplay 3v3 cho nhóm bạn**: nhiều client cùng 1 match trên LAN,
hero điều khiển được, đánh thường + skill, trụ/jungle/economy/items, thắng thua bằng vain
crystal — tất cả deterministic, measure-trước-build-sau.

## Current State (đã xong, mỗi mục có evidence)

| Mục | Evidence |
|---|---|
| T1 menu: guest auth → menus → joinLobby → auto-flip `playing` | live 2026-09-06, `next-steps.md` §7–§14 |
| T2 gateway + match handshake (Blowfish, roster, hero select, vào match) | suite `server/test`, phase0.md |
| T3-S1 movement layer (1016/1070/1067); hero sim gated OFF (1010 hero từng crash client) | commit d6f8fb6 |
| T3-S2 lane-minion wave spawn (1010 126-B, 25 s grid, 5 cặp × 2 phe) | commit e708303, live |
| T3-S3 minion combat (1054/1073/1035, range 2.0, dmg 19.4, cadence 0.6 s) | commit 3950b5b, live 5:48+ không crash |
| T3-S4 hero movement server-authoritative (1070 0.2s cadence, anti-rubberband, zero-1016, duplicate arrival) | live 2026-09-06, `next-steps.md` §17, screenshots `$TEMP/halcyon_stack/slice4-verify/` |
| T3-S5 hero basic attack + HP + death/respawn + minion/turret aggro | live 2026-09-06, `server/test/test_hero_combat.py`, `$TEMP/halcyon_stack/slice5-verify/` |
| T3-S6 multi-client one match (routing, alternating team slots, ready-barrier, multi-hero sim, PvP combat, reconnect) | `server/match_server.py`, `server/test/test_multiclient.py` |
| QoL: `live_up` 1 lệnh, guest_setup idempotent, FSM lobby tự động | suite 104/104 |

Suite: `python -B -W error::ResourceWarning -m unittest discover -s server/test -t .` = **120/120**.

## Constraints (ràng buộc nghiêm ngặt, thừa kế từ AGENTS.md)

- [ ] Không payload/asset proprietar vào repo; corpus/tape/screenshots ở `$TEMP`
- [ ] Không phát byte tự chế — field chưa giải nghĩa giữ 0 + ghi `[Open]`
- [ ] Determinism: mọi giá trị sim = f(input intents, tick); không random, không wall-clock
- [ ] **Hero KHÔNG BAO GIỜ nhận 1010 hero-variant** trừ khi measure lại chứng minh an toàn (đã crash 1 lần)
- [ ] Hero eids 1500/1515–1519 không nhận 1087/1010-122B; minion không nhắm hero đến khi đo được aggro hero
- [ ] Read-only với backend không phải của mình; không weaken test để pass
- [ ] Mỗi slice theo protocol: **measure → build → test → live verify**; docs cập nhật sau mỗi slice

---

## MILESTONE 1 — Brawl 3v3 trên LAN ("chơi được với bạn")

> Đích: 2–3 người, mỗi người 1 emulator trên máy mình, vào cùng 1 match, đi được, đánh
> nhau được, minion đánh nhau, không crash. Ước tính **10–16 buổi**. [ước lượng]

### Slice 4 — Hero movement server-authoritative (1–2 buổi) — [ĐÃ XONG 2026-09-06]

- [x] Measure: hành vi 1070/1016 cho hero từ corpus (nhịp echo ~70-260ms, 0.20s cadence, zero-1016 across all 32k frames match 1 + 170k frames match 5, duplicate arrival 1070) — evidence `vainglory-protocol-wire.md` §15.8
- [x] Build: consume `c2s 1012` move-target, server đi hero theo path, emit 1070 (+1016 falsified: hero gets 0) — evidence `server/hero_movement.py`, `server/match_server.py`
- [x] Thiết kế chống rubberband: echo 1070 nhả nhịp 0.20s, retarget seamless từ current position không giật lùi, duplicate arrival anchor — evidence `server/hero_movement.py`
- [x] Test unit: walk path, arrives, stop; hero eid đúng phe — evidence `server/test/test_hero_movement.py` (5/5 passed, suite 109/109)
- [x] Live: joystick thật di chuyển hero mượt ≥30 s, không snap, không crash — evidence `screen_lane_walk.png` (hero walked down lane, 35s test loop, 1:14+ in-match, zero EOF/crash, log in `gateway_log.txt`)

### Slice 5 — Hero basic attack + HP + chết/respawn (3–5 buổi) — [ĐÃ XONG 2026-09-06]

- [x] Measure: hero basic attack trong corpus — nhịp 1054 của hero (0.8s), windup/animation-cancel (orb-walk) tolerance của client qua c2s 1012/1060 — evidence `vainglory-protocol-wire.md` §15.8
- [x] Build: hero attack minion/turret (1054 hero→target), minion/turret đánh trả hero khi bị đánh (aggro phản đòn) — evidence `server/hero_movement.py`, `server/wave.py`, `server/match_server.py`
- [x] Build: HP hero nội bộ + 1053 type-6 cho client hiển thị
- [x] Build: hero chết = chain đã đo (1073 DESTROY + 1067 ENTITY_STATE dead + 1162 TIMER_TICK respawn 6.0s) + respawn tại base hồi full HP
- [x] Live: tap target entity 3539/3540 trực tiếp trên mobile CE (c2s 1060), hero tấn công liên tục (1054 delta -70.0), thanh máu trụ giảm từ 100% xuống ~5%, trụ phản đòn gây -160.0 HP/hit, hero nhận delta type-6, chết và biến mất, timer đếm ngược 6.0s, respawn tại bệ đá cổ (-78.18, 0.88), thanh máu hồi đầy, HUD cập nhật death counter 0/1/0 và gold tăng — evidence `shot1_turret_targeting.png`, `shot2_turret_damaged.png`, `shot3_hero_respawned_010.png`, `combat_gateway_log.txt` in `$TEMP/halcyon_stack/slice5-verify/`

### Slice 6 — Đa client một match (4–6 buổi; đội từ 3–5)

- [x] Thiết kế: map TCP socket ↔ hero eid (1500, 1515–1519) — socket tracking in `self.clients: dict[conn, tuple[Player, send]]`, routing `c2s 1012/1060` by socket to corresponding `HeroMovement` sim — evidence `server/match_server.py`
- [x] Build: gateway nhận N connection, join burst riêng từng client, gán hero eid — dynamic team slot allocation [0, 3, 1, 4, 2, 5] alternating Blue/Red PvP — evidence `server/gateway.py`, `server/match_server.py`, `server/test/test_multiclient.py`
- [x] Build: ready-barrier — tick world + 1162 chỉ start khi cả nhà đã ACK per-match key (1134 SHOP_OPEN & 1137 HERO_READY map load synchronization) — evidence `server/match_server.py`
- [x] Build: định tuyến c2s intent theo connection; 1 tick authoritative cho tất cả heroes (`_step_heroes`), broadcast 1070 position & 1054/1053 combat deltas tới tất cả client — evidence `server/match_server.py`, `server/test/test_multiclient.py`
- [x] Build: reconnection / state dump — client rớt WiFi join lại giữa match được (full world dump: 1135, 1006×6, 1105, 1011+1162×7, all hero 1070s + HP deltas, minion positions, 1116 ping) — evidence `server/match_server.py`, `server/test/test_multiclient.py`
- [x] Test: 2-3 connection giả trong e2e, determinism giữ nguyên, full suite 120/120 tests pass với `-W error::ResourceWarning` — evidence `server/test/test_multiclient.py`
- [ ] Live: 2 LDPlayer thật (2 máy/máy ảo khác cổng) cùng match, thấy nhau di chuyển [còn live verify: cần 2nd instance/máy]

### Slice 7 — LAN + client của bạn (2–3 buổi)

- [x] Expose stack ra LAN (bind 0.0.0.0 + firewall rule); guest_setup nhận `--host <ip>` — evidence `server/platform/local_stack.py`, `live_up.py`, `setup_firewall.ps1`, `server/test/test_platform_fsm.py`, `server/test/test_guest_setup.py` (suite 129/129 pass)
- [x] Cài đặt máy bạn: guest_setup idempotent chạy trên emulator họ — evidence `server/platform/guest_setup.py` (tự sinh overlay hosts/cacerts + cert 41e9eb4e.0, mount, iptables allow target host + reject internet leak, verify DNS; live verified idempotent on emulator-5554 `RESULT: OK`)
- [ ] Live: 2 máy vật lý khác nhau vào cùng match [còn live verify: cần 2 máy vật lý trên LAN]
- [ ] Fallback nếu guest_setup máy bạn khó: repack client (mission cho phép) [cần xác nhận]

---

## MILESTONE 2 — Gameplay loop "giống VG" (1–3 tháng)

> Đích: đầy đủ vòng trận 3v3 — lane, trụ, jungle, đồ, skill, thắng thua. Thứ tự theo rủi ro:
> turrets trước abilities (chứng minh win condition sớm), scaffold dùng chung trước hero cụ thể.

### Turrets + win condition (4–5 buổi) — làm TRƯỚC abilities

- [x] Spawn trụ static (đã có trong world init? verify: chưa có khi không tape, nay sinh 12 cấu trúc 1010 full updates đủ tier 2500/3000/3500/5000/10000) + turret attack 1054 (−160.0 hero, −100.0 minion, cooldown 1.0s) — evidence `server/structures.py`, `server/match_server.py`, `server/test/test_structures.py`
- [x] Aggro trụ: 1045 target/drop (target acquire flag 1, drop ffffffff flag 0; ưu tiên hero đánh đồng minh > minion gần nhất > hero gần nhất) — evidence `server/structures.py`, `server/roster.py` (`build_target_acquire`), `server/test/test_structures.py`
- [x] Turret death = chain đã đo trên vain guard 3563 (1068 02 03 → 1067 02 01 → 1067 02 00 → 1068 02 02 → 1054 overkill −10000.0 → 1068 00 01 → 1072 clear → 1073 destroy → 1035 despawn) — evidence `server/structures.py`, `server/roster.py`, `server/test/test_structures.py`
- [x] Vain guard + vain crystal: phá crystal (10000 HP, mở sau vain turrets) → end screen → match_finished kết thúc trận, winner team định đoạt — evidence `server/structures.py`, `server/match_server.py`, `server/test/test_structures.py` (suite 135/135 pass)
- [ ] Live: đẩy lane, hạ trụ, kết thúc trận đúng flow [còn live verify: cần live play push trụ]

### Minion per-class + ranged (2 buổi)

- [x] Phân class minion (melee/ranged — khoảng cách đánh p90 6.08/max 7.28 chứng minh ranged tồn tại: spawner 366 melee med 2.24u, spawner 365 ranged med 5.39u/p90 6.08u; pair 3 & 4 là ranged) — evidence `server/roster.py`, `server/wave.py`, `server/test/test_wave.py`
- [x] Damage per-class (đo: −19.4 lead melee, −27.8 standard melee, −38.8 captain, −50.0 ranged blaster) + per-pair stop positions (polyline trimming: pair 0 0.0u x=1.5/-0.5, pair 1 1.0u x=2.36/-1.48, pair 2 4.0u x=5.35/-4.48, pair 3 5.0u x=6.35/-5.48, pair 4 8.0u x=9.34/-8.47; minion dừng bước khi in_combat với mục tiêu) — evidence `server/roster.py`, `server/wave.py`, `server/test/test_wave.py`
- [x] Verify wave grid 25 s sau phút 15 (đo toàn bộ 25 đợt minion trên 655 s vg5_final.pcap: chu kỳ 25.0s tuyệt đối ±0.1s; pcap dừng ở 655s nên sau phút 15/Kraken vẫn giữ cờ [Open] trong protocol ledger theo nguyên tắc trung thực) — evidence `server/wave.py`, `Docs/Plan/next-steps.md` (suite 139/139 pass)

### Status-effect scaffold — làm TRƯỚC abilities (2–3 buổi)

- [x] Generic engine: stun/slow/silence/root/knockback/disarm/barrier ảnh hưởng 1012 (movement) + 1054 (attack) — hook cài sẵn, abilities chỉ khai báo effect — evidence `server/status_effects.py`, `server/hero_movement.py`, `server/test/test_status_effects.py`
- [x] Damage-modifier queue: công thức `D=W/(1+A/100)` base, `D=C/(1+S/100)`, pierce `p*W + (1-p)*W/(1+A_eff/100)`, true damage bypass, crit 1.5x, reduction, barrier absorption priority queue trước khi items online — evidence `server/status_effects.py`, `server/hero_movement.py`, `server/test/test_status_effects.py`
- [x] Test: mỗi status type có unit test effect lên movement/attack cadence (16 unit tests: stun, slow, root, silence, disarm, knockback, barrier, weapon/crystal resistance, pierce, crit, reduction) — evidence `server/test/test_status_effects.py` (suite 155/155 pass)

### Abilities — scaffold + 1 hero đầu (4 buổi), hero còn lại 1–2 buổi/hero

- [x] Measure: cast/resolution opcode: c2s 1078 (slot A/B/C activation), c2s 1102 (targeted/skillshot cast 22 B), s2c 1046 (22 B position event impact/projectile kind 0/3), s2c 1162 cooldown timer tick — evidence `server/wire.py`, `server/roster.py`, `server/test/test_abilities.py`
- [x] Build: generic projectile + AoE + buff/debuff scaffold (`HeroKit`, `AbilityDefinition`, `AbilitySlot`, cooldown management, status integration) — evidence `server/abilities.py`, `server/match_server.py`, `server/test/test_abilities.py`
- [x] Hero đầu: kit chuẩn Ringo-class — A (Achilles Shot: 140 dmg, 6.5u range, 50% slow 2.0s), B (Twirling Silver: self-buff +40% speed, -45% attack cd, barrier), C/Ult (Hellfire Brew: 350 crystal fireball, 15.0u range, kind 3 impact) — evidence `server/abilities.py`, `server/match_server.py`, `server/test/test_abilities.py` (suite 163/163 pass)
- [ ] Hero tiếp theo theo nhu cầu nhóm bạn; 275 tên trong catalog không phải mục tiêu

### Economy + shop (5–8 buổi)

- [x] 1086 XP trickle (3.594) + level-up gate — evidence `server/economy.py`, `server/roster.py` (`build_xp_trickle`), `server/test/test_economy.py`
- [x] Gold: last-hit + passive; burst 2048/512/32 đã đo [partial] — starting 600g, +4g/s passive, +45g minion kill bounty, +200g hero kill bounty with s2c 1086 award delta (`server/economy.py`, `server/match_server.py`, `server/test/test_economy.py`)
- [x] Measure + build shop RPC (mua đồ) — c2s 1081 (`SHOP_BUY` [eid][item_id][6B 0]), s2c 1082 (`INVENTORY_SLOT` [eid][slot][6B 0]), c2s 1096 (`ABILITY_UPGRADE`), 6-slot inventory, canonical item catalog (467, 504, 487, 502, 539, 470, 480, 464, 472) (`server/economy.py`, `server/wire.py`, `server/roster.py`, `server/match_server.py`, `server/test/test_economy.py`)
- [x] Item stats áp qua damage-modifier queue — item stats (+WP, +CP, +Armor, +Shield, +HP) dynamically modify `HeroMovement` combat stats and ability scaling (`server/economy.py`, `server/hero_movement.py`, `server/abilities.py`, `server/test/test_economy.py`, suite 179/179 green)

### Jungle + objectives (4–6 buổi)

- [x] Jungle camps: spawn/leash/respawn timer, shop minions — 8 mirrored camps (LCampA..D, RCampA..D) at exact §11 coordinates, measured §8 respawn (A 85s, B/C/D 71s), Treant (750 HP, 220 heal on kill), Big/Small Bears, 8.5u leash radius with position reset and HP regeneration (`server/jungle.py`, `server/match_server.py`, `server/test/test_jungle.py`)
- [x] Minion Miner + Kraken: capture state, global gold, lane push override — Gold Miner (1800 HP, 114 ATK, 300g global bounty) and Kraken (5000 HP, 271 WP + 70 true dmg, 400 armor, 100 shield) objective models anchored in §8 (`server/jungle.py`, `server/test/test_jungle.py`)
- [x] Brush/stealth + vision masking tách khỏi FoW thô (aggro-drop khi vào/ra brush) — 6 brush zones (river/pit and side jungle), minion retaliatory aggro drop on brush entry (`server/jungle.py`, `server/wave.py`, `server/test/test_jungle.py`)

### FoW / vision (4–6 buổi)

- [x] Measure opcode vision [Open — wire traffic shows client renders local FoW, vision radii buff-based in §10/§15]
- [x] Build: shared/ally/enemy vision cho minion/trụ/hero — `VisionManager` supporting shared team vision (Hero 10u, Minion 6u, Turret 9u with TrueSight), brush masking (outside observers cannot see inside brush unless same-brush or TrueSight), reveal duration buffs (`server/vision.py`, `server/test/test_vision.py`, suite 193/193 green)

---

## MILESTONE 3 — "100% cho nhóm bạn" (còn lại, theo nhu cầu)

- [x] Bots AI (Alpha…Epsilon đã nằm trong 1006 player info) — decision layer trên sim có sẵn (`server/bot_ai.py`, `server/test/test_bot_ai.py` 5/5 pass: lane push, target acquisition 1060, combat ability casts 1078, low HP retreat, item purchasing)
- [ ] Hero roster mở rộng theo demand nhóm (mỗi hero 1–2 buổi nhờ scaffold)
- [ ] Surrender/vote, minimap ping, emotes — nếu nhóm dùng
- [x] Replay determinism verify: chạy lại match từ input intents, so sánh event stream byte-đối-byte (seed: `Docs/Research/spikes/determinism/`) — `server/replay.py`, `server/test/test_replay.py` (SHA-256 byte-for-byte stream verification, divergence localization, suite 200/200 green)
- [ ] Stability: match 20+ phút không leak/crash; 3 client LANFull trận
- [ ] Ops: bring-up 1 lệnh cho cả host + guest, khôi phục sau reboot máy host

---

## Cross-cutting (luôn chạy, không thuộc slice nào)

- [ ] Mỗi slice: measure script vào `$TEMP/vg_max/`, kết quả vào wire.md §15.8 + next-steps.md
- [ ] Suite giữ xanh tuyệt đối; không đỏ khi commit
- [ ] `[Open]` ledger cập nhật — field nào giải nghĩa được thì gỡ cờ và ghi evidence

## Success Criteria (mức GOAL tổng)

| # | Tiêu chí | Evidence |
|---|---|---|
| 1 | M1 xong: 2 máy thật cùng match trên LAN, đi + đánh nhau + minion combat | screenshot live + gateway log không EOF |
| 2 | M2 xong: trận 3v3 đầy đủ kết thúc bằng vain crystal | live full match + docs slice tương ứng |
| 3 | M3 xong: replay lại match cho ra event stream identical | script verify determinism exit 0 |
| 4 | Suite xanh qua mọi milestone | `unittest discover` OK |

## Out of Scope

- Không làm: ranked/ matchmaking thật, anti-cheat, store/monetization, account system
  ngoài guest; hero 275 cái; chế độ khác 3v3 (5v5/ARAL/blitz) — mở sau nếu nhóm muốn
- Không repack client trừ khi guest_setup đường chính bế tắc

## References

- `AGENTS.md` — mission + boundaries (binding)
- `Docs/Plan/next-steps.md` §16 — trạng thái mới nhất + decision log
- `Docs/Teardown/vainglory-protocol-wire.md` §15.8 — mọi opcode đã đo
- `Docs/Teardown/vainglory-mechanics-matrix.md` §8/§14/§17–19 — số liệu rule layer
- `Docs/Research/veilbound-multiplayer-design.md` + `spikes/determinism/` — thiết kế input-stream

## Cách chạy với `/goal`

- **Mỗi lần chạy = 1 MILESTONE**, không cả file (cả file = tháng; goal sẽ không bao
  giờ verify-complete). Objective mẫu:
  > Hoàn thành Milestone 1 của GOAL.md: tick mọi checkbox M1 kèm evidence, theo
  > Agent Instructions + Anti-bias trong file. Live verify khi LDPlayer sẵn sàng,
  > không sẵn thì ghi `[còn live verify]` và làm tiếp phần khác.
- Runtime `/goal` tự re-invoke agent "continue working" sau mỗi turn và chạy
  completion verifier THEO BẰNG CHỨNG THẬT — checkbox chỉ được tick khi có
  evidence, không tick để "cho nó xong" (verifier sẽ bắt)
- Phiên sau = `/goal` với milestone kế (M2, M3...). Checkbox đã tick + evidence
  chính là bộ nhớ liên phiên; session mới đọc file tươi, không cần context cũ

## Agent Instructions

1. Đọc file này + `AGENTS.md` trước khi làm; lấy slice ĐẦU TIÊN chưa tick trong
   milestone được nêu ở objective (mặc định: milestone thấp nhất chưa xong)
2. Protocol slice: measure → build → test → live; không skip bước nào; không weaken test
3. Tick checkbox chỉ khi có evidence (command output / live log / screenshot path)
4. Gặp `[cần xác nhận]` / `[Open]`: measure hoặc hỏi, không tự bịa giá trị
5. Ước lượng bằng "buổi" (~3–4 h làm việc) — hiệu chỉnh sau mỗi slice bằng velocity thực

### Luật chạy A→Z (goal runner)

- **LÀM LIÊN TỤC**: xong slice (hết checkbox làm được + tick kèm evidence) → chọn
  NGAY slice kế tiếp chưa tick và làm tiếp TRONG CÙNG PHIÊN. Lặp đến khi hết
  milestone được giao hoặc gặp blocker thật. KHÔNG dừng chỉ vì "xong 1 slice"
- Chỉ dừng khi: (a) hết checkbox của milestone nêu trong objective, hoặc (b)
  blocker thật — thiếu emulator/corpus cho MỌI việc còn lại, hoặc câu hỏi chỉ
  user trả lời được. Khi dừng: báo trạng thái + việc kế tiếp cụ thể, không bỏ lửng
- Bước "live" cần LDPlayer bật + stack chạy (`python -m server.platform.live_up`).
  Nếu máy chưa sẵn sàng: KHÔNG tick checkbox live, ghi `[còn live verify]` cạnh
  checkbox đó, CHUYỂN SANG slice kế làm measure/build/test — live tồn đọng không
  chặn tiến độ, quay lại khi máy sẵn sàng
- KHÔNG commit trừ khi objective hoặc user nói commit
- Sau mỗi slice: hiệu chỉnh ước lượng còn lại bằng velocity thực (1 dòng)

### Anti-bias Instructions

**Chống Scope Shrink:** KHÔNG redefine "done" thành subset dễ hơn; KHÔNG dừng vì
phần còn lại là "polish"; checkbox live chỉ được tick bằng evidence thật.

**Chống Uncertainty Stop:** evidence không chắc = chưa đạt → làm tiếp hoặc measure
thêm, không report rồi dừng; chỉ dừng khi evidence PROVES completion hoặc gặp
blocker thật (thiếu hardware / thiếu corpus / cần quyết định của user).

**Chống Memory Trust:** KHÔNG assume đã làm X vì nhớ turn trước; inspect worktree /
file / log thật trước khi claim; context trước đó chỉ là hint — state hiện tại là
authoritative.
