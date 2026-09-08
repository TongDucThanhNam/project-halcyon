# Community Ecosystem Tricks & Leads (VGNA, HackedGlory, VGReborn)

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
