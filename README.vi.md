# Project Halcyon

> **Authoritative, Deterministic, Self-Hosted Game Server for Vainglory (4.13.4, build 147219)**  
> Được xây dựng từ nghiên cứu kỹ thuật đảo ngược (clean-room reverse engineering) và tái hiện giao thức độc lập.

🌐 **Ngôn ngữ**: [English](README.md) | [Tiếng Việt](README.vi.md)

**Rà soát trạng thái ngày 13/09/2026:** máy chủ thử nghiệm đã có bằng chứng
gameplay với một client và kiểm thử mô phỏng tự động. Nghiệm thu gameplay tổng
thể vẫn **MỞ**. Xem [tiến độ và giới hạn hiện tại](Docs/Plan/current-status.md)
và [hồ sơ scenario](Docs/Plan/solo-sandbox-scenarios.md) để phân biệt quan sát
trực tiếp, điều kiện kiểm thử và các bước xác minh còn thiếu.

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
  - Cung cấp danh mục chọn tướng và trang phục qua `canUseAllHeroes` và `getSkinManifest`. Chọn được tướng không đồng nghĩa đã có bộ kỹ năng: hiện có factory riêng cho mười tướng, với các cơ chế còn thiếu được ghi rõ theo từng bộ kỹ năng.
  - Quản trị máy trạng thái FSM: `menus` $\rightarrow$ `joinLobby` $\rightarrow$ gán `playing` kèm IP/Port Gateway $\rightarrow$ `exitLobby`.

### T2: Gateway & Match Transport (Định tuyến & Bảo mật gói tin)
- **Cơ chế**: TCP framing `[u16 Big-Endian Length][Payload]`.
- **Mã hóa**: Blowfish ECB với khóa động được suy ra từ thông tin trận đấu.
- **Tính năng**: Handshake Route-Request (`00 06 00`), điều phối nhịp tim Heartbeat Relay, ghép nhiều client vào chung 1 phòng đấu, tự động dọn dẹp phòng chết khi người chơi ngắt kết nối.

### T3: Authoritative Simulation (Engine trò chơi)
- **Locomotion (Di chuyển)**: Hệ thống Dual-Contract kết hợp tìm đường cục bộ của Client (`c2s 1012`) và luồng hiệu chỉnh/xác thực vị trí từ Server (`s2c 1070`), kích hoạt hoạt ảnh bước chân mượt mà qua FSM Animation State (`1067 MOVING 0x0F` / `IDLE 0x00`).
- **Combat & Structure**: Giảm sát thương theo $D = \frac{W}{1 + A/100}$, chọn mục tiêu và tăng sát thương của trụ, phá Vain Crystal để kết thúc trận. Độ chính xác so với gameplay gốc vẫn cần đối chiếu độc lập.
- **Wave Director**: Lính ra đều đặn chu kỳ 25s, nhận diện đường đi (Waypoints), tấn công lính đối phương, cấu máu trụ.
- **Economy**: Vàng thụ động theo thời gian (Trickle gold), thưởng vàng/kinh nghiệm khi kết liễu lính (last-hit) và hạ gục tướng, mua đồ trong cửa hàng (`1081`/`1082`).

---

## 3. Lộ trình phát triển & Tiến độ (Roadmap)

Dự án theo dõi từng hành vi đã cài đặt và bằng chứng nghiệm thu, không gán
phần trăm hoàn thành tổng thể. Các tầng gameplay dưới đây khác với T1/T2/T3
trong sơ đồ kiến trúc.

### Tầng 1: Solo Sandbox / Phòng tập cá nhân
> *Mục tiêu: Một người chơi vào trận làm được mọi thứ trơn tru như game thật.*

**Nghiệm thu vẫn MỞ.** Những quan sát client có phạm vi giới hạn trước đây
đã bao phủ di chuyển, đánh thường, một số dạng kỹ năng, cửa hàng, mục tiêu
rừng, biến về, chết/hồi sinh và màn hình Victory. Một số sử dụng chuẩn bị QA
được khai báo; chúng chưa xác nhận một trận thông thường đã được nghiệm thu
đầy đủ. Xem [hồ sơ bảy cổng nghiệm thu](Docs/Plan/solo-sandbox-acceptance-status.md).

Tiến độ được ghi nhận đến hết ngày 12/09:

| Hạng mục | Bằng chứng và giới hạn |
|---|---|
| Đánh thường của Skye | Hình ảnh đạn đã được xem xét trực tiếp sau báo lỗi ngày 08/09; các tướng khác vẫn còn khoảng trống về độ chính xác. |
| Skye A/B/C | Driver với điều kiện chuẩn bị khai báo ghi nhận hai lần thực hiện đạt cho mỗi chiêu: A hai lần trong một trận, B và C mỗi chiêu trên hai trận mới. Chưa chạy hợp đồng compare-pair; hình ảnh của các lần này chưa được xem xét. |
| Sửa chiêu C của Skye | Đối chiếu dữ liệu sở hữu hỗ trợ phát kích hoạt vùng trước sát thương và dùng ngưỡng chọn cụm nhỏ hơn hai đơn vị. Kiểm thử tập trung và scenario headless production đạt; nghiệm thu client mới cho hai sửa đổi này còn thiếu. |
| Lính và trụ | Đã quan sát lính tiến lại và giao chiến. Ba cửa sổ hữu hạn chưa chứng minh lính sống sót tiếp tục tiến hay gây sát thương trụ. Fixture headless chủ động loại bỏ một đợt lính sau giao chiến; PASS của nó không xác nhận đẩy đường tự nhiên trên client. |
| Công cụ scenario | Sáu scenario headless tích hợp production đã khớp chính xác sự kiện/trạng thái giữa hai tiến trình với seed khác nhau trên một source pin được ghi nhận. Đây là tính lặp lại nội bộ, chưa phải đối chiếu gameplay gốc độc lập. |

### Tầng 2: PvE / Chơi với Bot
> *Mục tiêu: Đánh với Bot có tư duy cơ bản.*

- Nền tảng đã cài đặt: chọn tướng, chia slot, đi đường, chọn mục tiêu và đánh thường.
- Còn mở: chiến thuật, phối hợp kỹ năng, né chiêu, rút lui và phối hợp đi rừng. Chưa nghiệm thu một trận bot hoàn chỉnh.

### Tầng 3: PvP Online / Đa người chơi
> *Mục tiêu: Đấu nhóm bạn qua mạng LAN / Online.*

- Đã cài đặt và có kiểm thử tự động: định tuyến vào cùng trận, đồng bộ draft và xử lý phiên/kết nối lại.
- Mốc nghiệm thu còn mở: phiên giao chiến tái lập được với **hai client game thật**, có đòn đánh và thay đổi máu nhất quán trên cả hai màn hình.
- Còn mở: sương mù/núp bụi đầy đủ, độ chính xác của bộ kỹ năng và kết nối lại, độ ổn định dài hạn. Lỗi client crash sau khoảng 30 phút đứng yên vẫn đang được điều tra.

---

## 4. Thiết lập và kiểm chứng cục bộ

### Yêu cầu tiên quyết

- **Quy trình live đã ghi nhận**: Windows, LDPlayer 9 có quyền root, ADB và client Android CE 4.13.4 sở hữu hợp lệ (build 147219). Helper `live_up` dùng công cụ tiến trình Windows; đây chưa phải hướng dẫn Linux hoặc client PC đã kiểm chứng.
- **Python**: 3.11+ và PyCryptodome cho công cụ giao thức/chứng chỉ; Pillow cho driver client có hình ảnh và các bài kiểm thử. Inspector native tùy chọn cần thêm Capstone.
- **Dữ liệu sở hữu ngoài repository**: bản ghi navigation A001, corpus spawn rừng/Skye và `world_tape.bin` khớp production. Payload capture và tài sản client không nằm trong Git. Clone mới riêng lẻ không đủ để tái lập toàn bộ môi trường test/live.
- **Platform cục bộ**: chứng chỉ/khóa, cấu hình answers, định tuyến và CA trust trên giả lập. [Hồ sơ thiết lập mobile](Docs/Teardown/vainglory-mobile-local-stack.md) mô tả quy trình; kết quả chỉ vào menu ngày 05/09 trong tài liệu đó là lịch sử.

Chạy lệnh từ thư mục gốc repository. Đặt đường dẫn dữ liệu ngoài Git của
bạn trong PowerShell trước khi chạy test hoặc khởi động server:

```powershell
$env:HALCYON_NAVMESH = '<đường dẫn tuyệt đối tới bản ghi navigation A001 sở hữu>'
$env:HALCYON_SPAWN_CORPUS = '<thư mục tuyệt đối chứa bản ghi spawn sở hữu, gồm Kraken>'
$env:HALCYON_SKYE_VOLLEY_CORPUS = '<thư mục tuyệt đối chứa volley chunk 32 và 36 của Skye>'
```

Stack live đọc cấu hình, chứng chỉ và world tape tại
`$env:TEMP/halcyon_stack`; giữ các file này ngoài checkout.
[Hồ sơ scenario](Docs/Plan/solo-sandbox-scenarios.md) mô tả corpus cần thiết
và [công cụ dựng lại world tape](Tools/build_world_tape.py). Thiếu corpus là
lỗi thiết lập, chưa phải bằng chứng gameplay bị hồi quy.

### 1. Chạy toàn bộ Test Suite (Đảm bảo hồi quy an toàn)

```powershell
python -B -W error::ResourceWarning -m unittest discover -s server/test -t .
```
Số test lịch sử chỉ áp dụng cho source và môi trường được ghi nhận; xem
[trạng thái hiện tại](Docs/Plan/current-status.md). Source đang được đánh giá
phải chạy sạch. Chạy riêng các scenario kiểm tra tính lặp lại:

```powershell
python Tools/run_scenarios.py --mode headless --scenario all
```

Đầu ra nằm ngoài Git. Khi chưa có fixture tham chiếu độc lập, kết quả tham
chiếu vẫn là `UNAVAILABLE` dù kiểm tra lặp lại nội bộ đạt.

### 2. Khởi động Máy chủ Host

Khi đã chuẩn bị dữ liệu bên ngoài và giả lập, khởi chạy platform, gateway,
relay và thiết lập định tuyến guest. Helper dừng stack cũ trước khi chạy lại:
```powershell
python -m server.platform.live_up
```
Để thông báo địa chỉ LAN, với định tuyến và CA trust được cấu hình riêng cho
từng thiết bị:
```powershell
python -m server.platform.live_up --match-host <IP_LAN_CỦA_BẠN>
```

### 3. Kết nối & Trải nghiệm trên Client

1. Mở Vainglory trên giả lập hoặc điện thoại đã cấu hình DNS/Hosts trỏ về máy chủ.
2. Theo luồng solo đã ghi nhận: **PLAY → SOLO BOTS → 3V3 → VERY EASY**.
3. Chọn tướng có bộ kỹ năng đã cài đặt, ví dụ Skye, khóa chọn và vào trận. Chọn được tướng không đồng nghĩa bộ kỹ năng đã được hỗ trợ.

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
├── Tools/                     # Inspector RE, driver scenario và công cụ tái lập
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
