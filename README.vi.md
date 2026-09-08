# Project Halcyon

> **Authoritative, Deterministic, Self-Hosted Game Server for Vainglory (4.13.4, build 147219)**  
> Được xây dựng từ nghiên cứu kỹ thuật đảo ngược (clean-room reverse engineering) và tái hiện giao thức độc lập.

🌐 **Ngôn ngữ**: [English](README.md) | [Tiếng Việt](README.vi.md)

---

## 1. Sứ mệnh (Mission)

**Project Halcyon** hướng tới tái hiện gameplay Vainglory 3v3 trên máy chủ tự lưu trữ cho nhóm bạn. Solo Sandbox hiện đã được kiểm thử với client Android Community Edition nguyên bản (4.13.4, build 147219); PvP đầy đủ và độ chính xác của toàn bộ bộ kỹ năng vẫn là các phần việc riêng.

* **Triết lý cốt lõi**: *"Hiểu không đồng nghĩa với Thực thi"*. Tài liệu Reverse-Engineering cho biết client giao tiếp như thế nào, còn toàn bộ logic máy chủ (authoritative game simulation) phải được lập trình và mô phỏng hoàn toàn từ con số 0.
* **Mục tiêu sản phẩm**: Tính tất định (Determinism), chu kỳ tick cố định (Fixed-tick), độ trễ phản hồi dưới 30ms trên mạng LAN / Private Server.

---

## 2. Kiến trúc hệ thống (System Architecture)

Server được xây dựng phân tầng theo mô hình 3 tầng (T1 – T2 – T3):

```
                        [ Vainglory Client (CE 4.13.4) ]
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
   HTTPS/TLS (8443)             TCP Gateway (7100+)            UDP Relay (2112)
        │                              │                              │
        ▼                              ▼                              ▼
┌──────────────────┐          ┌──────────────────┐          ┌──────────────────┐
│   T1: PLATFORM   │          │   T2: GATEWAY    │          │    HEARTBEAT     │
│  Preauth & Auth  │          │ Blowfish Encrypt │          │ Keepalive Ping   │
│  JSON-RPC / WS   │          │ Multi-Client RT  │          │ Packet Relay     │
└─────────┬────────┘          └────────┬─────────┘          └──────────────────┘
          │ (FSM: joinLobby)           │ (TCP Wire stream)
          └────────────────────────────┼──────────────────────────────┘
                                       ▼
                          ┌──────────────────────────┐
                          │       T3: GAME SIM       │
                          │   Authoritative Server   │
                          │  ──────────────────────  │
                          │  • Locomotion & Navmesh  │
                          │  • Combat & Abilities    │
                          │  • Minion & Turret AI    │
                          │  • Jungle & Objectives   │
                          │  • Economy & Items       │
                          └──────────────────────────┘
```

### T1: Platform RPC (Cửa trước & Quản lý danh mục)
- **Cơ chế**: HTTP/1.1 + TLS 1.2/1.3 trên cổng 8443, WebSocket notification trên 8080/notify.
- **Tính năng**:
  - Tự động sinh JWT định danh người chơi theo phần cứng (Hardware ID) hoặc theo thẻ thiết bị (Device Listener Tag) để hỗ trợ nhiều máy ảo clone chung HWID.
  - Cung cấp danh mục mở khóa **toàn bộ 50+ tướng** (`canUseAllHeroes: true`) và toàn bộ **290 trang phục** (`getSkinManifest`).
  - Quản trị máy trạng thái FSM: `menus` $\rightarrow$ `joinLobby` $\rightarrow$ gán `playing` kèm IP/Port Gateway $\rightarrow$ `exitLobby`.

### T2: Gateway & Match Transport (Định tuyến & Bảo mật gói tin)
- **Cơ chế**: TCP framing `[u16 Big-Endian Length][Payload]`.
- **Mã hóa**: Blowfish ECB giải mã bằng Dynamic Match Key (`00000000-1111-4222-8333-444455556666`).
- **Tính năng**: Handshake Route-Request (`00 06 00`), điều phối nhịp tim Heartbeat Relay, ghép nhiều client vào chung 1 phòng đấu, tự động dọn dẹp phòng chết khi người chơi ngắt kết nối.

### T3: Authoritative Simulation (Engine trò chơi)
- **Locomotion (Di chuyển)**: Hệ thống Dual-Contract kết hợp tìm đường cục bộ của Client (`c2s 1012`) và luồng hiệu chỉnh/xác thực vị trí từ Server (`s2c 1070`), kích hoạt hoạt ảnh bước chân mượt mà qua FSM Animation State (`1067 MOVING 0x0F` / `IDLE 0x00`).
- **Combat & Structure**: Công thức tính sát thương chuẩn xác $D = \frac{W}{1 + A/100}$, cơ chế bắn lính/tướng của Trụ với suy giảm sát thương, nổ Vain Crystal kết thúc trận đấu.
- **Wave Director**: Lính ra đều đặn chu kỳ 25s, nhận diện đường đi (Waypoints), tấn công lính đối phương, cấu máu trụ.
- **Economy**: Vàng thụ động theo thời gian (Trickle gold), thưởng vàng/kinh nghiệm khi kết liễu lính (last-hit) và hạ gục tướng, mua đồ trong cửa hàng (`1081`/`1082`).

---

## 3. Lộ trình phát triển & Tiến độ (Roadmap)

Dự án được đánh giá theo mô hình **Vertical Slice 3 tầng**:

### Tầng 1: Solo Sandbox / Phòng tập cá nhân
> *Mục tiêu: Một người chơi vào trận làm được mọi thứ trơn tru như game thật.*

**Nghiệm thu được mở lại:** thử Skye thực tế cho thấy không nâng được kỹ năng,
thiếu hình ảnh đạn đánh thường và lính di chuyển lỗi. **758 tests xanh** trước
đó không chứng minh các hành vi này hoạt động đúng trên client.
[Hồ sơ nghiệm thu](Docs/Plan/solo-sandbox.md) ghi kết quả hiệu năng cuối cùng
và phân biệt phạm vi đã hoàn thành với các giới hạn về bộ kỹ năng và thời gian
hoạt ảnh nguyên bản còn cần hiệu chỉnh.

- [x] Tìm đường Navmesh, va chạm vách, tốc độ động và dừng khi bị khống chế.
- [ ] Vung/phát/thu đòn, đạn tầm xa và vừa đánh vừa di chuyển: đang sửa hình ảnh đạn.
- [ ] Bốn dạng hitbox, năng lượng/HUD và ngắt chiêu vận sức: Skye thiếu bộ kỹ năng.
- [x] Giới hạn cửa hàng, trang bị kích hoạt và nội tại được yêu cầu.
- [ ] Lính cận chiến/đánh xa/xe pháo, trụ bảo vệ tướng, tăng sát thương và Victory: đang sửa di chuyển lính.
- [x] Bùa rừng, Mỏ Vàng trả vàng toàn đội và Kraken chiếm được đi phá trụ.
- [x] Biến về bốn giây, hồi phục ở bệ đá và vòng đời chết/hồi sinh động.

### Tầng 2: PvE / Chơi với Bot (~40%)
> *Mục tiêu: Đánh với Bot có tư duy cơ bản.*

- [x] Bot tự động phân chia slot, tự chọn tướng và khóa đội hình.
- [x] Bot tự tìm đường ra lane, tìm mục tiêu và đánh thường.
- [ ] Bot AI biết combo chiêu thức (A/B/Ult), biết né chiêu, lùi khi thấp máu và đảo đường đi gank.

### Tầng 3: PvP Online / Đa người chơi (~70%)
> *Mục tiêu: Đấu nhóm bạn qua mạng LAN / Online.*

- [x] Kết nối nhiều thiết bị vào cùng 1 trận đấu (Multi-client routing).
- [x] Cơ chế đồng bộ hóa Draft (Chọn tướng / Chọn skin thời gian thực).
- [x] Khả năng sống sót khi rớt mạng và Reconnect mượt mà giữa trận.
- [ ] **Fog of War (Sương mù & Núp bụi)**: Che giấu gói tin tọa độ của đối phương khi đang núp trong bụi rậm.

---

## 4. Hướng dẫn khởi chạy nhanh (Quick Start)

### Yêu cầu tiên quyết
- **Hệ điều hành**: Windows 10/11 hoặc Linux.
- **Python**: 3.11+ trở lên (ưu tiên pure Python tiêu chuẩn).
- **Client**: Vainglory CE 4.13.4 (Build 147219) trên PC hoặc Giả lập Android (LDPlayer 9).

### 1. Chạy toàn bộ Test Suite (Đảm bảo hồi quy an toàn)
```powershell
python -B -W error::ResourceWarning -m unittest discover -s server/test -t .
```
*(Toàn bộ hơn 220+ bài kiểm thử đơn vị và end-to-end phải xanh 100%).*

### 2. Khởi động Máy chủ Host
Chạy **1 lệnh duy nhất** để dọn sạch tiến trình cũ, khởi chạy Platform RPC, Gateway, Heartbeat Relay và nạp cấu hình:
```powershell
python -m server.platform.live_up
```
Nếu muốn host qua mạng LAN cho điện thoại thật kết nối:
```powershell
python -m server.platform.live_up --match-host <IP_LAN_CỦA_BẠN>
```

### 3. Kết nối & Trải nghiệm trên Client
1. Mở Vainglory trên giả lập hoặc điện thoại đã cấu hình DNS/Hosts trỏ về máy chủ.
2. Tại màn hình chính: Bấm **PLAY $\rightarrow$ SOLO BOTS $\rightarrow$ 3V3 $\rightarrow$ EASY** (hoặc Custom Lobby).
3. Khóa tướng yêu thích, chọn Skin tùy ý và tiến hành trải nghiệm trận đấu!

---

## 5. Cấu trúc thư mục (Repository Layout)

```
project-halcyon/
├── Docs/                      # Tài liệu nghiên cứu & Kế hoạch
│   ├── Teardown/              # Cơ sở tri thức RE (Wire protocol, Navmesh, Codec, Map 3v3)
│   ├── Plan/                  # Kế hoạch từng Milestone và Deliverables
│   └── Research/              # Thiết kế hệ thống mô phỏng tất định (Determinism Spike)
├── server/                    # Mã nguồn máy chủ Authoritative
│   ├── platform/              # T1: TLS HTTPS RPC, Guest JWT Auth, Answers JSON, FSM
│   ├── gateway.py             # T2: Gateway routing, Match key derivation, Relay
│   ├── match_server.py        # T2/T3: Điều phối trận đấu, Quản lý vòng đời Draft & World
│   ├── hero_movement.py       # T3: Mô phỏng di chuyển, Navmesh, FSM animation
│   ├── abilities.py           # T3: Khung kỹ năng tướng, Level up, Cooldown
│   ├── wave.py                # T3: Điều phối đợt lính (Minion Wave Director)
│   ├── structures.py          # T3: Trụ phòng thủ, Nhà chính Vain Crystal
│   ├── economy.py             # T3: Cửa hàng trang bị, Vàng thụ động, Tiền thưởng
│   ├── jungle.py              # T3: Quái rừng, Bùa lợi, Cơ chế Leash
│   ├── bot_ai.py              # T3: Trí tuệ nhân tạo điều khiển Bot
│   └── test/                  # Toàn bộ test suite bảo vệ tính toàn vẹn hệ thống
├── Tools/                     # Công cụ phục vụ nghiên cứu & đo đạc (Read-only)
├── GOAL.md                    # Danh sách mục tiêu chi tiết theo từng Slice
├── README.md                  # Tài liệu hướng dẫn Tiếng Anh
├── README.vi.md               # Tài liệu hướng dẫn Tiếng Việt
└── AGENTS.md                  # Chỉ dẫn bắt buộc cho AI Agents và kỷ luật làm việc
```

---

## 6. Ràng buộc pháp lý & An toàn (Binding Guardrails)

1. **Clean-room & No Proprietary Assets**: Tuyệt đối không lưu trữ texture, model 3D, shader, file `.pcap`, file `.vgr`, file store đã giải mã hoặc executable nguyên bản của SEMC trong repository. Toàn bộ mã nguồn là bản tự cài đặt từ tri thức giao thức.
2. **Phi thương mại & Sử dụng nội bộ**: Dự án phục vụ mục đích nghiên cứu học thuật và giải trí cá nhân cho nhóm bạn thân.
3. **Read-only đối với máy chủ bên ngoài**: Không quét cổng, inject gói tin hoặc can thiệp vào bất kỳ hạ tầng dịch vụ công cộng nào.
4. **Determinism là thước đo sống còn**: Simulation của máy chủ phải tuyệt đối tất định (Deterministic), không sử dụng yếu tố ngẫu nhiên ngoài luồng clock mô phỏng.
