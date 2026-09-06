# Prompt: T3 slice 1 — 1010 full-update simulation cho hero local

> Prompt tự chứa, dán vào session mới. Bản thân prompt này đã mang đủ
> ngữ cảnh kỹ thuật; các leaf docs được trỏ tới chỉ để đối chiếu byte
> khi cần, đừng đọc tràn lan.

---

## Bối cảnh (đã chạy được, đừng làm lại)

Project Halcyon (đọc `AGENTS.md` trước — binding rules ở đó) đã qua các
mốc: T2 gateway/match closed; post-lock world init serving live; **world
layer LIVE** — client Vainglory 4.13.4 (LDPlayer) vào match, map render,
hero eid 1500 di chuyển theo lệnh server (c2s 1012 → s2c 1070 @0.2s).
Trạng thái hiện hành: `Docs/Plan/next-steps.md` §13 (mới nhất), wire leaf
`Docs/Teardown/vainglory-protocol-wire.md` §15.8 block "World layer live".

World entity layer hiện đang **replay tape corpus** (s2c 0..12.5s sau 1137
echo, file ngoài repo ở `$TEMP/halcyon_stack/world_tape.bin`, loader:
`server/world_tape.py`). Nhạc nền sau tape: 1116 ping 1Hz + movement layer.
Đó là cầu tạm — **T3 là thay tape bằng simulation thật, từng họng một**.

## Nhiệm vụ của session này: họng 1010 (ENTITY_FULL_UPDATE) cho hero local

Mục tiêu: sau khi tape kết thúc, server **tự sinh 1010 cho hero eid 1500**
từ state movement đã có (position/velocity trong `SnapshotStream`), đúng
layout corpus, determinstic theo tick — không copy payload tape.

Trình tự bắt buộc (measure → build → test → live):

1. **Measure trước**: decode 27 frame 1010 của corpus (tool ngoài repo
   `$TEMP/vg_max/` — `world_after_1137.py`, `decode_world_frames.py`;
   corpus key: `wire.MatchCipher("b9f511e0-…")` UUID string, stream c2s/s2c
   nằm ở `$TEMP/vg_max/`). Kiến thức hiện có, chưa đầy đủ:
   `[u32 eid][const c10b41da][u32 global tick][f32 x][f32 0.00707][f32 y]…`
   — cần pin: độ dài payload, ý nghĩa các field sau y, tick pacing (~5s?),
   field 0.00707 (hệ số gì), và 1010 có theo entity nào ngoài hero không.
   Ghi layout kết luận vào wire §15.8 kèm bằng chứng offset.
2. **Builder** trong `server/roster.py` (hoặc module sim mới
   `server/sim/` nếu tách rõ): `build_entity_full_update(...)`. Tick nguồn
   là **global tick counter dùng chung** — lưu ý 1086 mang u16 counter
   monotonic riêng, giữ nhất quán với các frame khác phát ra.
3. **Wiring** trong `match_server.py`: sau `tape_done`, vòng world loop
   phát 1010 của hero theo pacing đo được thay vì im lặng; giữ nguyên
   1116 + movement layer. Có flag/env để tắt tape hoàn toàn
   (`HALCYON_NO_TAPE=1`?) nhằm test sim thuần mà không cần xoá file tape.
4. **Tests**: unit — byte-shape 1010 khớp mẫu corpus (pinned hex của 1
   frame, chỉ phần layout đã chứng minh); tick tăng đơn điệu; position
   khớp `hero_x/hero_y` (f32 re-pack compare như test 1070 hiện có).
   e2e — chế độ no-tape: join → lock → dump → không tape, client giả
   (socket test) vẫn nhận 1116 + 1010 + trả 1070 khi gửi 1012.
5. **Live verify**: restart stack (kill PID giữ :7102, chạy
   `python -B -m server.platform.local_stack` background), force-stop +
   relaunch app. **Lưu ý routing sống còn**: `adb reverse` cần đủ 4 port
   (8080, 8443, 7102, 2114) sau mỗi lần adb server restart — thiếu là
   black screen / "Unable to connect" (xem mobile leaf mục
   "Reverse-mapping failures seen live"). Chạy tới match, chờ tape xong,
   quan sát client **không dessert** khi 1010 sim bắt đầu; tap di chuyển,
   so vị trí screen với x/y trong 1010/1070. Random houdini segfault
   (tombstone ở `$TEMP/halcyon_stack/`) KHÔNG phải do bytes của ta —
   kiểm tra `logcat -b events` trước khi kết luận.

## Acceptance

- Client ở lại match sau khi tape hết và 1010 sim chạy ≥ 60s (không
  re-queue, không abort world-sync).
- Movement vẫn hoạt động khi 1010 đang phát (tap → 1012 → 1070 + 1010
  cùng nhất quán vị trí).
- Suite green (`python -B -W error::ResourceWarning -m unittest discover
  -s server/test -t .`), không weaken test nào.
- Wire §15.8 + `next-steps.md` có mục update mới; báo cáo kèm
  `git diff --stat`; **không commit**.

## Ràng buộc khi làm (trích AGENTS.md, vẫn có hiệu lực)

- Không payload/asset proprietar vào repo; corpus/tape/screenshots ở
  `$TEMP` — constant + layout được phép, byte thô không.
- Không phát byte "tự chế" — mọi field chưa giải nghĩa giữ 0 và ghi
  `[Open]`; sim chỉ tính những field đã chứng minh (position, tick).
- Determinism: mọi giá trị sim suy ra từ (input intents, tick) — không
  random, không đọc đồng hồ wall-clock vào state game.
- Read-only với mọi backend không phải của mình.
- Tiếng Việt, thẳng; claim "done" phải kèm bằng chứng chạy thật.

## Sau họng này (session kế, đừng làm sớm)

Họng 1087 (spawn 1 minion wave từ allocation layout đã đo: blob 40B,
new eid tuần tự từ 0x7d6) → họng 1053/1086 (stat deltas theo damage
giả lập trên dummy). Mỗi họng giữ nguyên trình tự measure → build →
test → live.
