# Prompt: T3 slice 2 — họng 1087: spawn 1 minion wave (+ 1010/1070 cho minion)

> Prompt tự chứa, dán vào session mới. Bản thân prompt này đã mang đủ
> ngữ cảnh kỹ thuật; các leaf docs được trỏ tới chỉ để đối chiếu byte
> khi cần, đừng đọc tràn lan.

---

## Bối cảnh (đã chạy được, đừng làm lại)

Project Halcyon (đọc `AGENTS.md` trước — binding rules ở đó). T3 slice 1
đã đóng (`Docs/Plan/next-steps.md` §14, commit d6f8fb6): world layer LIVE,
client Vainglory 4.13.4 (LDPlayer) ở lại match ≥60s sau tape, movement
c2s 1012 → s2c 1070 hoạt động. Kết quả quan trọng của slice 1 — **đừng
lặp lại nhầm**:

- **1010 đã đo xong 2 biến thể** trong `server/roster.py`
  (`build_entity_full_update`): 126 B no-HP và 122 B **HP@+36/maxHP@+40**
  (5.651 frame match-5; minion maxHP 450-class; tail đã đo:
  `+96..103 = 03 0f 03 03 03 03 03 03`, `+119..121 = 01 ff 01`, [Open]).
  Counters dùng chung do caller sở hữu: `world_tick` u32 (+8) và
  `seq_1010` u8 (+116), +1 mỗi lần phát.
- **Hero KHÔNG BAO GIỜ nhận 1010** (0/6.645 frame corpus) — live đã chứng
  minh client EOF match socket 1s sau hero-1010. Hero-1010 hiện default-OFF
  sau cờ `HALCYON_HERO_1010=1`; đừng bật lại, đừng phát 1087/1010 cho
  eids 1500/1515–1519.
- World layer: tape corpus 0..12.5s sau 1137 echo (`server/world_tape.py`,
  file tape ngoài repo ở `$TEMP/halcyon_stack/world_tape.bin`), sau đó
  live layer: 1116 ping 1Hz + movement + (hero-1010 nếu bật cờ).
  `HALCYON_NO_TAPE=1` bỏ tape; `match_server._run_world` là vòng world;
  state machine PICK → LOCKED → FINAL → WORLD đã ổn định.
- Suite hiện hành: **76/76** xanh với
  `python -B -W error::ResourceWarning -m unittest discover -s server/test -t .`

## Việc 0 (15 phút, làm trước khi vào họng): script hoá guest routing

Reboot emulator xóa sạch routing (đã xác minh live): hosts bind-mount,
2 rule iptables, CA overlay, `adb reverse`. "Unable to connect" chiều nay
là do đó. Viết **một lệnh duy nhất** (vd `python -m server.platform.guest_setup`,
chạy trên host, gọi adb + adb shell su) re-apply toàn bộ theo mobile leaf
`Docs/Teardown/vainglory-mobile-local-stack.md` mục roll-forward:
bind `/data/local/tmp/halcyon-hosts-20260905` → `/system/etc/hosts`,
bind `/data/local/tmp/halcyon-cacerts-20260905` → `/system/etc/security/cacerts`,
2 rule iptables/ip6tables (uid 10060 local-only + redirect 80→8080, 443→8443),
`adb reverse` 4 port (8080, 8443, 7102, 2114). Idempotent (mount đã tồn tại
thì báo rồi bỏ qua, đừng fail). Verify: sau khi chạy, `ping rpc.kindred-live.net`
trên emulator trả 127.0.0.1.

## Nhiệm vụ chính: họng 1087 — server tự spawn 1 minion wave

Mục tiêu: sau khi tape kết thúc, server **tự sinh 1087 cho 1 wave minion**
(theo layout đo được), rồi mỗi minion có **1010 122-B (có HP)** và — nếu
corpus cho thấy minion stream 1070 — movement stream cho chúng. Toàn bộ
determinism theo (input intents, tick): không random, không wall-clock.

Trình tự bắt buộc (measure → build → test → live):

1. **Measure trước** (tool ngoài repo `$TEMP/vg_max/`; corpus key
   `wire.MatchCipher("b9f511e0-…")`; có sẵn `world_after_1137.py`,
   `decode_world_frames.py`, `measure_1010*.py`, `vgr5frames.pkl` —
   169.963 frame match-5 đã parse):
   - Layout 1087: tape window match-1 có ~241 allocation, **blob 40 B**,
     eid mới tuần tự từ `0x7d6`; steady stream sau đó vẫn 1087/1086.
     Cần pin: ý nghĩa từng offset của blob 40 B (type code ở đâu,
     position/timer có trong blob không), blob nào thuộc wave nào.
   - **Timing wave**: wave đầu xuất hiện ở giây thứ mấy sau 1137; interval
     giữa các wave (mechanics leaf nói 60s — kiểm chứng bằng byte);
     số minion/wave (12–14?); eid range mỗi wave (match-1: minion
     292..372 trong window; match-5: minion 6xxx–8xxx ở 1054 attribution).
   - **Template 1010/1070 cho minion**: minion nhận 1010 122-B (HP) —
     lấy 1 sample minion từ match-5, pin giá trị +24/+32 (facing khi mới
     spawn), +12/+16/+20 (đúng z ground 0.00707?), pacing 1010/1070 của
     1 eid minion khi đang đi. Minion có 1070 riêng không hay chỉ 1010?
   - Ghi layout kết luận vào wire §15.8 (mục "1087" mới) kèm bằng chứng
     offset; cập nhật mechanics nếu timing đo được khác 60s.
2. **Builder** trong `server/roster.py`: `build_entity_spawn_1087(...)`
   (hoặc tên khớp ngữ nghĩa thật của 1087 sau khi measure). Dùng lại
   `build_entity_full_update(..., hp=(cur,max))` cho minion 1010. Wave =
   hàm thuần của `(wave_index, world_tick)`; eid cấp tuần tự từ counter
   mới (bắt đầu `0x7d6` như corpus — giữ counter `next_eid` trong
   match server, không dùng lại eid cũ).
3. **Wiring** trong `match_server.py`: sau `tape_done`, world loop phát
   wave 1 ở timing đo được (không phát sớm hơn), mỗi minion: 1087 →
   1010 122-B → (1070 nếu đo được). Giữ nguyên 1116 + movement + hero
   (hero-1010 vẫn default-OFF). **Có kill switch từ đầu**:
   `HALCYON_NO_WAVE=1` tắt toàn bộ wave (bài học slice 1: live falsify
   phải tắt được bằng env, không phải sửa code).
4. **Tests**: unit — byte-shape 1087 khớp fragment corpus (pinned hex,
   chỉ field đã chứng minh; payload rule: không pin byte thô toàn frame);
   1010 minion khớp template HP; eid tăng tuần tự; wave phát đủ N minion
   đúng tick. e2e — chế độ no-tape: join → lock → dump → không tape →
   wave spawn đủ → client giả nhận 1087/1010 theo đúng thứ tự → trả 1070
   khi có movement. Không weaken test nào.
5. **Live verify**: chạy Việc 0 trước nếu chưa. Sau đó: force-stop +
   relaunch app, vào match. **Quy trình drive đã chuẩn hoá (bám theo
   `next-steps.md` §14 live-ops)**:
   - `settings put global hide_error_dialogs 1` — crash dialog hệ thống
     nuốt `input tap`.
   - Sau `joinLobby` **flip `update` → `playing` thẳng** (bỏ qua
     `matched_partners` — transition accept-screen segfault 3/3 tối nay,
     là houdini class trước khi có kết nối match nào).
   - Táp: PLAY (1310,790) → SOLO BOTS (1360,660) → 3V3 (1180,490) →
     MEDIUM (1180,503) → LOCK IN (800,815); dismiss "Choose a Build"
     bằng Android BACK.
   - Random houdini segfault KHÔNG phải bytes của ta — `logcat -b events`
     (`am_crash`) trước khi kết luận; kiểm cả "crash xảy ra trước hay
     sau khi có route trong `gateway_log.txt`".
   - Acceptance runtime: wave spawn → client ở lại match ≥60s, không
     re-queue, không abort world-sync; movement hero vẫn hoạt động.

## Acceptance

- Script routing (Việc 0) chạy 1 lệnh, idempotent, verify được bằng
  `ping` trong emulator.
- Client ở lại match ≥60s sau khi wave 1 spawn (không re-queue, không
  abort); minion render được quan sát (screenshot lưu `$TEMP`).
- Movement hero vẫn hoạt động khi wave đang chạy.
- Suite green (lệnh ở trên), không weaken test nào.
- Wire §15.8 + `next-steps.md` (§15) có mục update mới; báo cáo kèm
  `git diff --stat`; **không commit**.

## Ràng buộc khi làm (trích AGENTS.md, vẫn có hiệu lực)

- Không payload/asset proprietar vào repo; corpus/tape/screenshots ở
  `$TEMP` — constant + layout được phép, byte thô không.
- Không phát byte "tự chế" — mọi field chưa giải nghĩa giữ 0 và ghi
  `[Open]`; sim chỉ tính những field đã chứng minh.
- Determinism: mọi giá trị sim suy ra từ (input intents, tick) — không
  random, không đọc đồng hồ wall-clock vào state game.
- Read-only với mọi backend không phải của mình.
- Tiếng Việt, thẳng; claim "done" phải kèm bằng chứng chạy thật.

## Sau họng này (session kế, đừng làm sớm)

Họng 1053/1086 (stat deltas theo damage giả lập trên dummy — minion ta
spawn là mục tiêu tự nhiên) → 1054 combat delta. Bộ HP/maxHP của minion
trong 1010 122-B là anchor để kiểm chứng delta trừ đúng. Mỗi họng giữ
nguyên trình tự measure → build → test → live.
