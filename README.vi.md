# Project Halcyon

**Lưu trữ cục bộ (11/10/2026):** repo tại `D:\project-halcyon`; dữ liệu riêng,
runtime và kết quả kiểm thử đặt trong `Local/` được Git bỏ qua (lần chạy mới:
`Local/evidence/`). Xem [hướng dẫn di chuyển](Docs/Setup/windows-local-development.md).

> **Authoritative, Deterministic, Self-Hosted Game Server for Vainglory (4.13.4, build 147219)**  
> Được xây dựng từ nghiên cứu kỹ thuật đảo ngược (clean-room reverse engineering) và tái hiện giao thức độc lập.

🌐 **Ngôn ngữ**: [English](README.md) | [Tiếng Việt](README.vi.md)

**Rà soát trạng thái ngày 23/10/2026 (lưu trữ ngày 08/11/2026):** máy chủ
authoritative thử nghiệm đã xác minh phiên 6 participant qua giao thức wire,
trận đấu tự nhiên hoàn chỉnh tới lúc nổ Vain Crystal (`M3`), replay tất định
chính xác từng byte từ input journal (`M4`), 1 client CE thật + 5 participant
giao thức (`M5 step C`), và kết nối điện thoại Android vật lý nguyên bản qua
WireGuard + TLS chứng chỉ công khai. Nghiệm thu PvP toàn diện vẫn **MỞ**. Xem
[tiến độ và giới hạn hiện tại](Docs/Plan/current-status.md) và
[hồ sơ scenario](Docs/Plan/solo-sandbox-scenarios.md).

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
   HTTPS/TLS (8443)             TCP Gateway (7100+)            TCP Heartbeat (2112)
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

- **Các cột mốc đã hoàn thành & xác minh (đến ngày 23/10/2026)**:
  - **Milestone 2 (`M2`)**: 6 participant giao thức wire (Skye/Catherine/Adagio vs Ringo/Gwen/Amael) vượt qua draft/readiness và thực thi nâng chiêu, tung chiêu native, di chuyển, đánh thường, mua trang bị, Biến về (Recall) và kết nối lại giữ nguyên định danh.
  - **Milestone 3 (`M3`)**: Trận đấu 6 participant tự nhiên đến lúc phá hủy Vain Crystal (`1106 → 1072 → 1009`), replay khớp từng byte giữa hai tiến trình độc lập (6.813 bản ghi, 328 checkpoint, 145.052 sự kiện).
  - **Milestone 4 (`M4`)**: Nhật ký đầu vào theo thứ tự áp dụng (`server/input_journal.py`) và cơ chế replay production khớp tuyệt đối (`Tools/run_scenarios.py --mode replay --journal <path>`).
  - **Milestone 5 Step C (`4ac`)**: 1 client Android CE thật cùng 5 participant giao thức vượt qua cả 8 điều kiện live (giao tranh hai chiều trước và sau khi kết nối lại).
  - **Milestone 7 Preparation (`M7 prep`)**: Giới hạn bộ nhớ lịch sử lính chết và EID đã xóa; tách tiến trình host (`Tools/protocol_host.py`); chạy soak 30 phút 6 participant và replay khớp từng byte (38.391 thao tác, 1.027.103 sự kiện).
  - **Kết nối Điện thoại Android Vật lý Nguyên bản (WireGuard + Public TLS)**: Điện thoại Redmi Note 11 chưa root chạy bản CE 4.13.4 gốc qua WireGuard chính thức + chứng chỉ TLS Let's Encrypt tên miền riêng (`server/platform/phone_vpn.py`); phiên live 538 giây được ghi lại và replay khớp tuyệt đối.
- **Việc cần làm tiếp khi quay lại phát triển**:
  1. **Khôi phục kết nối lại (cold-process reconnect) trên điện thoại Android thật**: Khi đóng và mở lại app, client kết nối lại vào trận sau 7,8s và nhận catchup nhưng đóng socket trước khi gửi opcode/readiness (cần chẩn đoán bước bắt tay load/ready trước khi bắn world dump).
  2. **Nghiệm thu 2 client CE hiển thị thật (`M5` full gate)**: Phiên giao tranh trực tiếp giữa 2 máy thật/giả lập với đòn đánh và máu đồng bộ trên cả hai màn hình.
  3. **Xử lý phần dư M7 soak & hoàn thiện bộ kỹ năng**: Tìm nguyên nhân mức tăng +0,069 ms/phút của checkpoint và +0,17 MiB/phút của RSS; mở rộng các bộ kỹ năng tướng còn lại và sương mù/bụi cỏ.

---

## 4. Khôi phục từ đầu & Thiết lập Cục bộ (Cold-Start Restore Guide)

Toàn bộ dự án được tách thành 2 phần rõ ràng:
1. **Mã nguồn trên Git (GitHub)**: Toàn bộ code server (`server/`), công cụ RE & kiểm thử (`Tools/`), tài liệu (`Docs/`) và danh mục băm SHA-256 (`Config/local-inputs.json`).
2. **1 File ZIP duy nhất trên Google Drive (`halcyon-local-backup.zip`, ~1,56 GB)**: Dữ liệu riêng (Git-ignored) đã được chắt lọc từ ~41 GB xuống còn **đúng 1 file `.zip` duy nhất** chứa trọn bộ:
   - APK (`vg-4.13.4-147219-base.apk`) & OBB (`main.147219...obb`) Android gốc, cùng `vainglory/lib/arm64-v8a/libGameKindred.so` (cho native ARM64 oracle).
   - Đúng 944 file `Data/` PC 4.13 cần thiết (navmesh + 942 file `INST`/`CFF0` manifest — chỉ 16,4 MB thay vì 3,45 GB texture/âm thanh thừa).
   - Toàn bộ cấu hình `runtime/` (`world_tape.bin`, `answers.json`, chứng chỉ TLS CA, khóa WireGuard `phone-vpn/` & chứng chỉ Let's Encrypt `phone-acme/` cho `rpc.halcyon.tongducthanhnam.id.vn`).
   - Toàn bộ `research/runtime-corpus/` (3 file `.vgr` `.32`, `.36`, `.72`) và kho `research/vg_max/` đã lọc sạch (`.pcap`, `.vgr`, `.pkl`, `.tsv`, `inst_dump/`).
   - Toàn bộ nhật ký đầu vào phiên live (`journal.jsonl`, `inputs-*.jsonl`) và báo cáo nghiệm thu trong `evidence/` (`M3`, `M4`, `M5 4ac`, `M7 soak`, `phone-vpn`) để chạy replay tất định.

### Các bước khôi phục nhanh khi bắt đầu lại trên máy mới / sau khi xóa thư mục

1. **Clone repository về đúng đường dẫn `D:\project-halcyon`** (giữ đường dẫn `D:\project-halcyon` giúp các file replay journal lịch sử khớp ngay đường dẫn tuyệt đối mà không cần sửa):
   ```powershell
   git clone https://github.com/TongDucThanhNam/project-halcyon.git D:\project-halcyon
   Set-Location D:\project-halcyon
   ```

2. **Tải `halcyon-local-backup.zip` từ Google Drive về máy**, sau đó giải nén thẳng vào `D:\project-halcyon\Local`:
   ```powershell
   New-Item -ItemType Directory -Path .\Local -Force | Out-Null
   Expand-Archive -LiteralPath "C:\duong-dan-tai-ve\halcyon-local-backup.zip" -DestinationPath .\Local -Force
   ```

3. **Tạo môi trường ảo Python `.venv` và cài đặt thư viện** (Python 3.11+, đã đo chuẩn trên Python 3.14 x64):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   # Cài thêm gói phục vụ RE, native ARM64 oracle và WireGuard VPN cho điện thoại:
   .\.venv\Scripts\python.exe -m pip install -r requirements-research.txt -r requirements-native.txt -r requirements-phone-vpn.txt
   ```

4. **Kiểm tra toàn bộ dữ liệu đầu vào, chứng chỉ và bộ nạp mô phỏng**:
   ```powershell
   .\.venv\Scripts\python.exe -B Tools/setup_local.py --check --profile headless
   .\.venv\Scripts\python.exe -B Tools/setup_local.py --check --profile client
   ```
   Cả hai lệnh phải báo `RESULT: PASS (0 prerequisite failures)`.

5. **Chạy kiểm thử tự động và kịch bản mô phỏng (không cần bật giả lập)**:
   ```powershell
   # Chạy gói kiểm thử nhanh smoke (~11 giây):
   .\.venv\Scripts\python.exe -B Tools/run_checks.py --suite smoke
   # Chạy toàn bộ 7 kịch bản headless đối chiếu tất định 2 tiến trình:
   .\.venv\Scripts\python.exe -B Tools/run_scenarios.py --mode headless --scenario all
   # Replay lại phiên chơi thực tế trên điện thoại Android vật lý:
   .\.venv\Scripts\python.exe -B Tools/run_scenarios.py --mode replay --journal .\Local\evidence\phone-vpn-journal-1792731479464021600\replay\journal.jsonl
   ```

6. **Chạy với Client Game (LDPlayer 9 hoặc Điện thoại Android thật qua WireGuard)**:
   - Xem **[hướng dẫn thiết lập chi tiết trên Windows](Docs/Setup/windows-local-development.md)** để cấu hình LDPlayer 9 (§5–§9) hoặc kết nối điện thoại Android thật không cần root qua WireGuard + TLS (§6.1).
   - Lệnh khởi chạy nhanh server kèm định tuyến cho LDPlayer (`emulator-5554`):
     ```powershell
     .\.venv\Scripts\python.exe -B -m server.platform.live_up --serial emulator-5554 --bind-host 127.0.0.1 --match-host 127.0.0.1
     ```

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
