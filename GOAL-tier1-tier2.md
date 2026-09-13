# GOAL-tier1-tier2.md — Đóng Tier 1 (Solo Sandbox) + Tier 2 (Bot Match)

> Status reviewed 2026-09-13: this is the dated work plan, not the current
> acceptance report. Use [current status](Docs/Plan/current-status.md) and the
> [seven-gate checklist](Docs/Plan/solo-sandbox-acceptance-status.md) for newer
> repairs and evidence. The full Tier 1/Tier 2 objective remains open.

> Tạo bởi create-goal skill, 2026-09-09. File goal RIÊNG cho giai đoạn đóng
> Tier 1 + Tier 2 theo `README.md` §3; `GOAL.md` master (M1-M3 lịch sử) giữ
> nguyên — hai file song song, file này là bản active cho giai đoạn hiện tại.
> Tick checkbox CHỈ khi có evidence (command output / live log / screenshot
> path). Không tick vì "chắc là xong".

---

## Objective

Đóng hết **Tier 1 Solo Sandbox** (7/7 gate, riêng gate 2/3/5 đang mở lại) và
**Tier 2 PvE Bot Match** (tactical AI) theo định nghĩa trong `README.md` §3,
sao cho một người chơi thật trên client CE 4.13.4 chọn hero bất kỳ được đưa
ra trong draft → đi, đánh thường có đạn bay, upgrade + cast skill A/B/Ult,
mua và dùng item, minion đi lane mượt — tất cả có bằng chứng live trên thiết
bị, suite xanh ≥ baseline 820.

## Context

- **Lý do**: Operator test Skye trên máy thật (2026-09-08) lộ ra: Skye chọn
  được nhưng không có kit (10 lần 1078 upgrade không được ack), không thấy
  đạn đánh thường, minion đi bị giật/về lui. Người chơi báo "minion, sài
  skill, sài item chưa ổn; tier 1 với 2 chưa hoàn thiện".
- **Ưu tiên**: correctness > speed. Live evidence trên thiết bị thật là
  chuẩn nghiệm thu, offline test chỉ là điều kiện cần.
- **Người thực hiện**: AI Agent, chạy theo từng slice với `/goal`.
- **Ngày tạo**: 2026-09-09.

## Current State

| Item | Giá trị (đã verify 2026-09-09) |
|------|-------------------------------|
| Suite | `820 tests OK, skipped=1` (skip = Skye volley corpus ngoài repo) — lệnh ở Success Criteria |
| Worktree | Xanh nhưng **121 file chưa commit**, way ahead of commit `d9e6336` |
| Gate 1 Navigation | ✅ Met (Catherine wall detour, Gwen STUN stop) |
| Gate 2 Basic attacks | 🔴 **Reopened** — thiếu đạn bay nhìn thấy; root cause: thiếu `1037` projectile creation lúc release; fix `projectile_wire.py` đã có trong worktree, **chưa live verify** |
| Gate 3 Abilities | 🔴 **Reopened** — Skye/265 không có kit; fix `SkyeKit` + `skye_wire.py` (volley presentation) + RANK_CURVES đã có trong worktree, **chưa live verify** |
| Gate 4 Items/shop | ✅ Met (bounded matrix) nhưng operator vẫn báo "sài item chưa ổn" → cần live re-verify |
| Gate 5 Waves/turrets | 🔴 **Reopened** — root cause: server chỉ phát đúng 1 lệnh `1016`/actor lúc spawn, goal client đứng yên tại waypoint đầu; fix: `wave.Director` phát lại `1016` khi rẽ lane / đổi pursuit / dừng, đã có trong worktree, **chưa live verify** |
| Gate 6 Jungle | ✅ Met (Treant burn, Gold Miner 300g, Kraken siege) |
| Gate 7 HUD/lifecycle | ✅ Met (Recall 4s, respawn, revival) |
| Hero kits | **10/50+**: Ringo, Catherine, Gwen, Celeste, Lance, Taka, Adagio, Koshka, Amael, Skye (Skye mới nhất). Hero còn lại nhận `Unsupported` kit — chọn là "chết skill" |
| Tier 2 Bot AI | Có: lane push, target acquisition, auto-attack, low-HP retreat, mua đồ. Thiếu: ability combos (A/B/Ult), skillshot dodging, jungle ganking |
| Tier 3 PvP | FoW/brush culling còn thiếu — **ngoài scope GOAL này** |

## Target State

| Item | Giá trị |
|------|---------|
| Gates | 7/7 gate đóng với live evidence ghi trong `Docs/Plan/solo-sandbox-acceptance-status.md` |
| Projectiles | Đạn thường của hero ranged + ranged minion hiện hình trên client (1037 wire đúng socket hash) |
| Abilities | Skye upgrade 1078 được ack, cast A/B/Ult có cooldown 1162 + damage; 4 shape geometry giữ nguyên |
| Minions | Di chuyển lane mượt, không rubberband (1016 re-issue hoạt động) |
| Items | Mua + kích hoạt item trên live session, không defect mới |
| Draft | Không có hero "chết skill" trong draft: hoặc lọc draft theo kit-ready, hoặc đủ kit cho mọi hero đưa ra |
| Tier 2 bots | Bot dùng combo A/B/Ult trong giao tranh, rút lui máu thấp, gank jungle — có unit test + live demo |
| Thứ KHÔNG thay đổi | Wire protocol đã đo, determinism model, navmesh, 7 subsystem khác đã met, guardrails AGENTS.md |

## Constraints (ràng buộc nghiêm ngặt, thừa kế từ AGENTS.md)

- [ ] KHÔNG đưa payload/asset proprietar vào repo; corpus/tape/screenshot ở
      `$TEMP/halcyon_stack/`, `D:/Downloads/vg/` — ngoài repo
- [ ] KHÔNG phát byte tự chế cho field chưa giải nghĩa — giữ 0 + ghi `[Open]`
- [ ] Determinism: mọi giá trị sim = f(input intents, tick); không random,
      không wall-clock trong tick
- [ ] Read-only với backend không phải của mình. Headless bot swarm CHỈ chạy
      against server Halcyon của mình (correction trong
      `vainglory-community-ecosystem-tricks.md`), KHÔNG chống official SEMC
- [ ] KHÔNG weaken test/check để pass — code sai thì sửa code, premise sai
      thì nói rõ premise sai
- [ ] KHÔNG commit trừ khi operator yêu cầu
- [ ] Live acceptance: QA được prepare (position, HP, incoming status) nhưng
      hành động client thật + kết quả nhìn thấy mới là evidence
- [ ] Mỗi slice theo protocol: measure → build → test → live verify; docs
      cập nhật sau mỗi slice
- [ ] Nếu gặp blocker (thiếu emulator/corpus, câu hỏi chỉ operator trả lời
      được): DỪNG, ghi rõ blocker, chuyển slice khác làm được, không workaround tự chế

## Success Criteria

> Mỗi tiêu chí cần evidence PROVES completion. Evidence live = đường dẫn
> screenshot/video/wire-trace ghi vào doc leaf tương ứng.

| # | Tiêu chí | Verification Command | Expected Output / Signal |
|---|----------|---------------------|--------------------------|
| 1 | Suite xanh, không regression | `python -B -W error::ResourceWarning -m unittest discover -s server/test -t .` | `Ran 820+ tests ... OK` (không thêm skip mới) |
| 2 | Gate 2 đóng: đạn thường hiện hình | Live session (lệnh ở Slice A) + wire trace: hero ranged + ranged minion release có `1037`, đạn thấy trong video | Mục mới trong `solo-sandbox-attack-actions.md` + `solo-sandbox-acceptance-status.md` ghi "closed" kèm path `$TEMP/halcyon_stack/...` |
| 3 | Gate 3 đóng: Skye kit sống | Live: chọn Skye, bấm upgrade → có 1078/1082 ack; cast A/B/Ult → có 1162 cooldown + damage 1054 | Mục mới trong `solo-sandbox-abilities.md` + acceptance-status ghi "closed" kèm trace path |
| 4 | Gate 5 đóng: minion mượt | Live: quan sát wave minion đi lane ≥ 2 phút, không hold/drift/rubberband; wire census: nhiều `1016` theo lane turn/pursuit như native (13–18 orders/actor wave đầu) | Mục mới trong `solo-sandbox-wave-turret-acceptance.md` + acceptance-status ghi "closed" |
| 5 | Items ổn định trên live | Live: vào shop mua ≥ 2 item (1 passive + 1 active), kích hoạt active, dùng ≥ 1 consumable; không crash/defect | Ghi nhận trong slice report + acceptance-status giữ gate 4 "met" với evidence mới |
| 6 | Không hero "chết skill" trong draft | Kiểm tra danh sách draft platform trả về vs `create_hero_kit` factories | Mọi hero đưa ra draft đều có kit, HOẶC draft đã lọc theo kit-ready (chọn 1 phương án ở Slice C) |
| 7 | Tier 2: bot tactical AI | Unit test mới cho combo/retreat/gank + 1 live match vs bots mà bot cast skill | Test pass trong suite; mục live trong slice report |
| 8 | Replay determinism giữ nguyên | `python -B -m unittest server.test.test_replay -q` | OK |

### Reference Artifacts

- `Docs/Plan/solo-sandbox-acceptance-status.md` — bảng 7 gate, source of truth
  cho completion Tier 1; gate chỉ đóng khi dòng gate ghi evidence live mới
- `Docs/Plan/solo-sandbox-attack-actions.md`, `solo-sandbox-abilities.md`,
  `solo-sandbox-wave-turret-acceptance.md`, `solo-sandbox-items.md` — nơi ghi
  evidence chi tiết từng gate
- `README.md` §3 — định nghĩa Tier 1/2/3 mà GOAL này tham chiếu

### Completion Condition

Agent kết thúc khi và chỉ khi:
- [ ] Tất cả 8 verification ở trên pass / có evidence thật
- [ ] Cả 7 gate trong `solo-sandbox-acceptance-status.md` ghi "met/closed"
      với live evidence hiện tại (không phải historical)
- [ ] Không regression so với Current State (suite ≥ 820 OK, determinism OK)

## Execution Plan

> Thực hiện theo thứ tự. Bước 1-2 là khối lượng lớn nhất còn thiếu của Tier 1.

1. **Slice A — Live re-acceptance gates 2/3/5** (1-2 buổi):
   LDPlayer + `HALCYON_NO_BOTS=1 HALCYON_TRACE_WIRE=1 HALCYON_EXPERIMENTAL_CAPTURE=1
   python -B -m server.platform.live_up`; vào PLAY → SOLO BOTS → 3V3 → VERY
   EASY, chọn **Skye**. Verify: upgrade skill được ack, cast A/B/Ult, thấy
   đạn thường, minion đi mượt. Ghi evidence vào 3 leaf + acceptance-status.
   Nếu còn defect: bắt bug từ wire trace (`Tools/Teardown/inspect_*`), sửa,
   thêm regression test, live lại. Đây là vòng lặp cho tới khi 3 gate đóng.
2. **Slice B — Item flow live re-verify** (0.5-1 buổi, gộp chung session A
   nếu được): mua passive + active + consumable, kích hoạt, xác nhận hiệu
   ứng (tốc độ boots, damage item). Fix defect phát sinh.
3. **Slice C — Draft không còn hero chết skill** (0.5 buổi + mở rộng theo
   demand): phương án mặc định [khuyến nghị]: lọc danh sách hero platform
   đưa ra draft về đúng 10 hero có kit (sửa `answers`/unlocks trong platform
   layer, không đụng `canUseAllHeroes` infrastructure). Phương án thay thế:
   mở rộng kit — mỗi hero 1-2 buổi theo protocol: `inspect_ability_actions.py`
   + `inspect_ability_constants.py` + cooldown tag từ `inst_dump` → implement
   kit → unit test → live verify. Danh sách hero ưu tiên: [cần xác nhận —
   operator cho list hero nhóm bạn hay chơi].
4. **Slice D — Tier 2 bot tactical AI** (3-5 buổi [ước lượng]):
   - D1: ability combo trong giao tranh (bot có kit → chọn slot theo tình
     huống: A poke, B steroid, Ult khi ≥2 mục tiêu hoặc kết liễu)
   - D2: skillshot dodging (tham số hóa từ hitbox framework có sẵn; mức
     đơn giản: né khi thấy projectile bay tới mình)
   - D3: jungle gank (bot jungle timing + rotate lane khi phe mình áp đảo)
   - D4: live match 1 người vs 5 bot, bot phải cast skill + gank thấy được
5. **Slice E — Full-match regression** (1 buổi): trận 20+ phút không
   crash/leak, replay determinism byte-exact, suite toàn xanh. Cập nhật
   `README.md`/`README.vi.md` tier checklist theo evidence mới.

## Out of Scope

- Tier 3 PvP: FoW/brush coordinate culling, multi-client LAN live với 2 máy
  vật lý (GOAL kế tiếp)
- Trick 1 (skin hash injection), Trick 2 (map themes) trong
  `vainglory-community-ecosystem-tricks.md` — feature riêng, không chặn gameplay
- Ranked/matchmaking thật, anti-cheat, store/monetization, account ngoài guest
- 5v5/ARAL/blitz; 275 skin; hero ngoài danh sách operator chọn
- Repack client (chỉ khi guest_setup đường chính bế tắc)

## References

- `AGENTS.md` — mission + guardrails (binding)
- `GOAL.md` — master goal M1-M3 lịch sử (giữ nguyên, tham chiếu chéo)
- `Docs/Plan/solo-sandbox.md` + `solo-sandbox-acceptance-status.md` — acceptance record hiện tại
- `Docs/Plan/solo-sandbox-attack-actions.md` §"Operator correction" — root cause 1037
- `Docs/Plan/solo-sandbox-wave-turret-acceptance.md` §"2026-09-08: user Skye test reopens continuous minion movement" — root cause 1016
- `Docs/Plan/solo-sandbox-abilities.md` — kit implementation + gaps từng hero
- `Docs/Teardown/vainglory-community-ecosystem-tricks.md` — 8 tricks + bảng correction (Trick 8 chỉ dùng với server mình)
- `Docs/Teardown/vainglory-mechanics-matrix.md` §17–18 — kit data extraction method
- `server/abilities.py` (`create_hero_kit`, `RANK_CURVES`), `server/skye_wire.py`, `server/projectile_wire.py`, `server/wave.py` (`Director`)

## Agent Instructions

### Execution

1. Đọc file này + `AGENTS.md` trước khi làm; lấy slice ĐẦU TIÊN chưa tick
   trong Execution Plan theo thứ tự
2. Protocol slice: measure → build → test → live; không skip bước nào
3. Tick checkbox / claim hoàn thành CHỈ khi có evidence thật (command
   output / live trace / screenshot path ghi vào doc)
4. Gặp `[cần xác nhận]` / `[Open]`: measure hoặc hỏi operator, không tự bịa
5. Ước lượng "buổi" ~3-4h; hiệu chỉnh sau mỗi slice bằng velocity thực

### Luật chạy A→Z (goal runner)

- **LÀM LIÊN TỤC**: xong slice → chọn NGAY slice kế trong CÙNG phiên. Chỉ dừng
  khi (a) hết slice, hoặc (b) blocker thật (thiếu emulator/corpus, câu hỏi
  chỉ operator trả lời). Khi dừng: báo trạng thái + việc kế cụ thể
- Bước "live" cần LDPlayer + stack chạy. Máy chưa sẵn sàng: KHÔNG tick live,
  ghi `[còn live verify]`, chuyển việc khác làm được (Slice C/D measure+build)
- KHÔNG commit trừ khi operator nói commit
- Sau mỗi slice: 1 dòng hiệu chỉnh ước lượng còn lại

### Anti-bias Instructions

**Chống Scope Shrink:** KHÔNG redefine "done" thành subset dễ hơn (vd: đóng
gate bằng offline test thay live). Temporary rough edges chấp nhận được —
nhưng objective gốc phải đạt đủ.

**Chống Uncertainty Stop:** evidence không chắc = chưa đạt → làm tiếp/measure
thêm; chỉ dừng khi evidence PROVES completion hoặc blocker thật.

**Chống Memory Trust:** KHÔNG assume đã làm X vì nhớ turn trước; inspect
worktree/file/log thật trước khi claim; state hiện tại là authoritative.
Offline check xanh ≠ client nhìn thấy đúng — gate 2/3/5 từng bị claim xong
sai bởi đúng lỗi này.
