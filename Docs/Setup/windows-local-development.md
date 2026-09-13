# Reproduce the Windows development environment

Reviewed **2026-09-13**. This guide covers the original Android CE client,
LDPlayer, local inputs, Python server, local routing, and verification. Run
PowerShell commands from the project root unless a step says otherwise.

Halcyon is an experimental server. Reproducing this environment does not close
gameplay acceptance, PvP acceptance, or independently measured official fidelity.
Read [current status](../Plan/current-status.md) before choosing development work.

## 1. What a new developer needs

There are two parts to the working project:

1. **Git source:** server, inspectors, tests, setup tools, configuration templates
   and documentation. These travel with a clone.
2. **Owned local inputs:** original APK/OBB, PC content store, captures, derived
   runtime records and private configuration. These live physically inside
   `Local/`, which Git ignores. A clone does not contain them.

Do not publish `Local/` or include it in a shared source ZIP. Each developer
needs their own authorized game installation and the documented owned inputs.
The local import does not create rights to redistribute the game or its data.
Keep fresh QA evidence outside the checkout; preserve existing journals.

### Downloads and installations

| Component | Where to obtain it | Version / purpose |
|---|---|---|
| Git for Windows | [Git's Windows installer](https://git-scm.com/install/windows) | Clone and inspect the source. |
| Python, Windows x64 | [Python Windows releases](https://www.python.org/downloads/windows/) | Source requires Python 3.11+. This machine was measured with **3.14.5 x64**; use that version for the closest reproduction. |
| LDPlayer **9** | [Official version selector](https://www.ldplayer.net/versions) | This machine's `dnplayer.exe` reports **9.5.32.0**. Select LDPlayer 9 explicitly; the main site also advertises LDPlayer 14 Beta, which this workflow has not validated. |
| Android SDK Platform-Tools | [Google's standalone Windows package](https://developer.android.com/tools/releases/platform-tools) | Contains `adb.exe`; Android Studio is not required for this workflow. Extract the whole directory, including DLLs. |
| 7-Zip, optional | [Official downloads](https://www.7-zip.org/download.html) | Inspect/extract an owned ZIP/XAPK. |
| Vainglory Android CE | [Publisher's download entry](https://www.vainglorygame.com/) | Require **4.13.4, build 147219**, package `com.superevilmegacorp.game`. APK **and** matching OBB are required. |
| Vainglory PC 4.13 content store | Your owned PC installation/archive | Needed by the current server's navigation default and numerous native-data tests. The Android OBB does not automatically supply the expected PC directory layout. |
| Owned research/runtime inputs | Your preserved research archive; file inventory below | These are project-specific data, not something `pip` or LDPlayer downloads. |

The publisher page links storefronts but does **not** establish that a current
download delivers these exact historical bytes. This review did not verify a
working official PC 4.13 archive download or an exact-build Android mirror.
[APKPure's package page](https://apkpure.com/vainglory/com.superevilmegacorp.game)
is a third-party acquisition lead; its contents could not be verified during
this review. Check version, filenames and hashes before use. A winter-map,
patched, regional, or different-build package is a different test input.

Keep downloaded installers in `Local/downloads/` if desired. Install LDPlayer
normally on Windows; copying its installed directory does not reproduce its
drivers/services. This guide does not relocate the installed emulator, Python,
or Windows SDK services.

### Capacity and measured settings

The imported original game/research inputs occupy approximately **8.52 GB decimal**
before manifests, virtual environments and new evidence. Retaining the external
originals uses additional space. Allow further room for the LDPlayer virtual disk,
OBB installation and video recordings; this is an inventory, not a minimum
hardware specification.

Measured host tools: Python 3.14.5, PyCryptodome 3.23.0, Pillow 12.3.0.
Optional research packages: Capstone 5.0.9, lz4 4.4.5, zstandard 0.25.0,
NumPy 2.5.2, imageio 2.37.4 and imageio-ffmpeg 0.6.0.
They are pinned in [requirements.txt](../../requirements.txt) and
[requirements-research.txt](../../requirements-research.txt).

## 2. Local directory layout and file inventory

```text
project-halcyon/
  Config/
    answers.example.json       # tracked; synthetic identity placeholder
    local-inputs.json          # tracked sizes, SHA-256 and provenance only
  Local/                       # completely ignored by Git
    downloads/                 # optional tool/install archives
    tools/platform-tools/      # optional portable ADB installation
    vainglory/
      vg-4.13.4-147219-base.apk
      main.147219.com.superevilmegacorp.game.obb
      pc/Vainglory 4.13/Vainglory/Data/...
      assets/, obb/, lib/, src/, ...   # preserved original research tree
    research/
      vg_max/                  # original owned research tree
        vgfull.pcap
        vgr/, vgr2/, vgr5/, vgr5b/, inst_dump/, ...
      runtime-corpus/          # three reconstructed records; not a full capture
        ...32.vgr
        ...36.vgr
        ...72.vgr
      vg_phaseB/vgr_live/      # only if you have the COMPLETE original archive
    runtime/halcyon_stack/
      answers.json
      platform_cert.pem
      platform_key.pem
      world_tape.bin
    manifests/import-*.json    # per-file verified import inventory
  .venv/                       # ignored; generated on each machine
```

The checked-in [input inventory](../../Config/local-inputs.json) records exact
filenames, byte sizes, SHA-256 values and evidence origins. It contains no payloads.

| Input | Measured size | Required for |
|---|---:|---|
| Android base APK | 30,497,305 bytes | Installing the rendered client. |
| Matching `main.147219...obb` | 1,394,159,471 bytes | Client expansion assets; the APK alone is insufficient. |
| PC `Data/4B/4BD271EAAC785AEB0C2BCED99515D401` | 24,239 bytes | A001 navigation, including production headless scenarios. |
| `research/vg_max/vgfull.pcap` | 1,357,284 bytes | Rebuilding the measured world tape and captured-protocol comparisons. |
| Runtime `world_tape.bin` | **46,292 bytes** | Current trimmed world initialization bootstrap. |
| Reconstructed chunk `.72.vgr` | 63,757 bytes | Additional Kraken archetype-363 creation record. |
| Reconstructed chunks `.32.vgr` / `.36.vgr` | 65,315 / 75,920 bytes | Skye volley line/cluster records. |
| Remaining `vg_max` VGR/store/cache files | See import manifest | Other neutral/static spawn templates and corpus-based regression tests. Keep the original hierarchy. |
| `answers.json`, certificate, private key | Generated locally or restored together | Platform bootstrap and the CA trusted by your emulator. |

All three reconstructed VGR filenames begin with
`ea4c7fda-4b61-481d-abb7-1c757d24ae58-a683aa80-9811-47c3-bb64-0731a802e889`.
Their provenance is the existing September 12 corr3/corr7 evidence recorded in
[the scenario leaf](../Plan/solo-sandbox-scenarios.md). They are sufficient
anchors for their runtime consumers when combined with the other spawn corpus;
they are not a complete original Phase B capture or independent fidelity oracle.

The original PC tree also contains historical patched executables such as
`VaingloryPatched.exe` and `VaingloryLocal.exe`. Preserving those files does not
make them the target client. Launch the measured Android CE build in this guide.

## 3. Clone and install Python dependencies

Obtain the repository URL from this project's maintainer, then:

```powershell
git clone <PROJECT_REPOSITORY_URL> project-halcyon
Set-Location project-halcyon
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Use the venv without requiring Activate.ps1 or a global policy change:
$env:Path = "$(Join-Path $PWD '.venv\Scripts');$env:Path"
$env:PYTHONDONTWRITEBYTECODE = '1'
python -c "import sys, Crypto, PIL; print(sys.executable); print(Crypto.__version__, PIL.__version__)"
```

Repeat the PATH assignment in each new PowerShell window, or invoke
`.\.venv\Scripts\python.exe` explicitly. For optional native/codec research:

```powershell
python -m pip install -r requirements-research.txt
```

The research pins reproduce the measured Python 3.14 environment; check each
package's supported Python versions if choosing an older interpreter. NumPy
2.5.2 requires Python 3.12 or later. NumPy
is used by the map/memory inspectors; imageio/FFmpeg support the historical
locomotion video comparison. They are not needed to start the core server.
Historical APK unpacking also used `apktool.jar` from the owned tools tree and
a compatible Java installation; this guide's unmodified APK/OBB installation
does not require unpacking or decompiling the client.

The live helper uses Windows process tools. A Linux host or the legacy native
PC client needs a separate validated procedure.

## 4. Bring existing files into the project

Use [the importer](../../Tools/import_local_data.ps1) for directories you own.
Each parameter is optional individually; supply only sources that exist.
For the original operator's layout:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Tools\import_local_data.ps1 `
  -GameSource 'D:\Downloads\vg' `
  -ResearchSource "$env:TEMP\vg_max" `
  -StackSource "$env:TEMP\halcyon_stack" `
  -VolleySource "$env:LOCALAPPDATA\halcyon-evidence\halcyon-ckpt13corr7-volley-anchors-ce646625-20260912\volley-rebuild" `
  -SpawnSource "$env:LOCALAPPDATA\halcyon-evidence\halcyon-ckpt13corr3-kraken-spawn-corpus-06cc680a-20260912\corpus-rebuild"
```

On another machine, substitute your actual archive locations. `-GameSource`
must contain the APK/OBB and `pc/` hierarchy shown above, not another enclosing
`vg/` folder. The importer retains source files, compares source/destination
SHA-256, and refuses to overwrite differing destinations. It skips already
identical files. A journal and final manifest in `Local/manifests/` record the
result, including partial progress on failure. Do not treat a partial import as
complete; rerun after resolving the reported cause. The tool refuses junctions
and symbolic links in import paths.

Stack import copies only `answers.json`, `platform_cert.pem`,
`platform_key.pem`, optional `platform.cer`, and `world_tape.bin`. Existing live
logs, QA journals and videos stay in their evidence locations. A running old
stack continues using its old directory until restarted.

On a fresh machine, you can instead place the inputs at the documented paths
directly. Put the original PC `Data` tree at exactly the path above. Extracting
an XAPK as a ZIP is only applicable when it contains this single base APK and
matching expansion file; split-APK packages require their actual split-install
procedure and are not the measured input here.

Check exclusion before staging source changes:

```powershell
git check-ignore Local/vainglory/vg-4.13.4-147219-base.apk
git check-ignore Local/runtime/halcyon_stack/platform_key.pem
git ls-files Local
```

The first two commands print the paths; the last prints nothing. Do not use
`git add -f` on private data. Back up `Local/` privately with your own permissions
and preserve the manifests. The source repository and documentation can travel
without it, but a source clone alone is not a complete runnable environment.

### Path overrides

[server/paths.py](../../server/paths.py) resolves project-relative paths even when
the checkout is on a different drive. Local directories are preferred; existing
legacy Downloads/TEMP directories remain fallback locations for older setups.

| Variable | Meaning |
|---|---|
| `HALCYON_LOCAL_ROOT` | Explicit local-data root. Disables implicit fallback to the old operator's directories. |
| `HALCYON_STACK_DIR` | Override only runtime config/tape/log location. |
| `HALCYON_NAVMESH` | Override the exact A001 file. |
| `HALCYON_SPAWN_CORPUS` | Windows semicolon-separated directories with creation records; needs all required neutral/static templates, including Kraken. |
| `HALCYON_SKYE_VOLLEY_CORPUS` | Directory with the exact `.32.vgr` and `.36.vgr` anchors. |
| `HALCYON_QA_DIR` | Separate, unique **external** directory for an explicitly prepared live QA run. |

To require the project-local layout for this shell:

```powershell
$env:HALCYON_LOCAL_ROOT = (Resolve-Path .\Local).Path
```

Set it again in another shell if desired. Do not globally repoint Windows
`TEMP` or `TMP` into this checkout. Headless scenario workers carry resolved
input paths into their external source snapshots; game data is not copied into
those snapshots.

If you have the **complete original Phase B archive** instead of the three
reconstructed runtime files, choose that input explicitly:

```powershell
$phaseB = (Resolve-Path .\Local\research\vg_phaseB\vgr_live).Path
$spawn5 = (Resolve-Path .\Local\research\vg_max\vgr5\vgr5).Path
$spawn1 = (Resolve-Path .\Local\research\vg_max\vgr\vgrtmp).Path
$env:HALCYON_SPAWN_CORPUS = "$phaseB;$spawn5;$spawn1"
$env:HALCYON_SKYE_VOLLEY_CORPUS = $phaseB
```

Do not create a partial `vg_phaseB/vgr_live` directory to stand in for that
archive: corpus tests referencing it require their full original fixtures.

## 5. Install and configure LDPlayer 9

1. Install LDPlayer 9 using its normal Windows installer. Keep a note of the
   installed directory and full version. This machine uses
   `D:\LDPlayer\LDPlayer9`.
2. Enable CPU virtualization (VT-x/AMD-V) in firmware if LDPlayer reports it
   disabled. Follow [LDPlayer's VT guide](https://www.ldplayer.net/blog/how-to-enable-vt.html)
   for your hardware; firmware menus vary. Do not change unrelated host security
   settings as an unexplained prerequisite.
3. Create/select a dedicated test instance in LDMultiplayer. This machine uses
   index `0`. Using a separate instance keeps local routing changes isolated.
4. Open the emulator's gear icon → **Other settings** → enable **Root
   permission**. Set **ADB debugging** to **Open local connection**. Save and
   restart the instance. LDPlayer documents the separate root/ADB switches in
   [its settings notes](https://www.ldplayer.net/blog/introduction-to-version-4.0.37-and-3.102-features.html)
   and [ADB guide](https://jp.ldplayer.net/support/ldplayer-adb-command.html).
5. For the built-in scenario driver, choose landscape **960 × 540**, DPI **160**.
   The measured current config uses **2 CPU cores** and **6144 MB RAM**; these
   are recorded settings, not established minimums. Earlier historical captures
   used 1600 × 900 and cannot share hard-coded tap coordinates without a matching
   client profile.

Extract Google's entire `platform-tools` directory into
`Local/tools/platform-tools/` (or your preferred SDK directory), then:

```powershell
$env:Path = "$(Join-Path $PWD 'Local\tools\platform-tools');$env:Path"
adb version
adb devices -l
$serial = 'emulator-5554'  # use the serial actually listed for your instance
adb -s $serial shell id
adb -s $serial shell "su -c id"
adb -s $serial shell wm size
adb -s $serial shell wm density
```

The ordinary shell may report `uid=2000`; `su -c id` must report `uid=0(root)`.
There is no need to run `adb root` or change adbd's security properties. Seeing
`device` in the device list does not prove a responsive shell or root access.

If no serial appears, check the local ADB setting and try
`adb connect 127.0.0.1:5555` for instance 0. Do not assume every instance uses
that port. `emulator-5554` and `127.0.0.1:5555` may represent two transports to
the same instance; choose one explicitly. The installed
`ldconsole.exe list2` also identifies instances.

## 6. Install the original APK and OBB

Keep the game closed until local routing is installed in step 8. The measured
install does not need an APK repack, Magisk, or a replacement native library.

```powershell
$serial = 'emulator-5554'
$apk = (Resolve-Path .\Local\vainglory\vg-4.13.4-147219-base.apk).Path
$obb = (Resolve-Path .\Local\vainglory\main.147219.com.superevilmegacorp.game.obb).Path
Get-FileHash -Algorithm SHA256 -LiteralPath $apk, $obb

adb -s $serial install -r $apk
adb -s $serial shell am force-stop com.superevilmegacorp.game
adb -s $serial shell mkdir -p /sdcard/Android/obb/com.superevilmegacorp.game
adb -s $serial push $obb /sdcard/Android/obb/com.superevilmegacorp.game/main.147219.com.superevilmegacorp.game.obb
adb -s $serial shell dumpsys package com.superevilmegacorp.game | Select-String 'versionName|versionCode|userId'
adb -s $serial shell stat -c %s /sdcard/Android/obb/com.superevilmegacorp.game/main.147219.com.superevilmegacorp.game.obb
```

Require ADB install `Success`, version code `147219`, version name `4.13.4`, and
OBB size `1394159471`. Compare host hashes to `Config/local-inputs.json`.
The destination must be a file directly under the package's OBB directory,
without an extra nested `obb/` or package directory. On permission errors,
push to `/data/local/tmp/` and copy to the same final path using `su -c` in your
owned rooted instance; verify the final size. Do not uninstall an existing game
to bypass a signature error without first preserving the instance/data you need.

## 7. Generate configuration and check all prerequisites

If you restored a matching certificate/key and working answers file, initialization
keeps them. Otherwise it generates a new private CA and a local synthetic session
token using the checked-in CE answer shapes. It refuses a half-present key pair.

```powershell
python -B Tools/setup_local.py --init
python -B Tools/setup_local.py --check --profile headless
python -B Tools/setup_local.py --check --profile client --serial emulator-5554
```

Require `RESULT: PASS`. The headless profile invokes actual production navmesh,
neutral/static spawn and Skye-volley loaders. The client profile additionally
checks APK/OBB identity, the production tape digest, config and certificate/key.
`--serial` reads root, package version, UID and guest OBB size. This checker does
not prove routing, rendering, gameplay, or correctness of every optional capture.

Missing captures cannot be regenerated from an empty clone. The setup checker
reports missing/invalid inputs explicitly; obtain the missing owned archive or
use the relevant [runtime reproduction leaf](../Teardown/vainglory-runtime-reconstruction.md)
for passive observation on your own client. Do not substitute fabricated packets
or silently bypass the loaders. Historical lost archives remain unavailable.

### Rebuild a missing world tape

The shipped builder accepts your existing owned capture, validates against the
production loader digest, and refuses overwrite. It writes outside the checkout:

```powershell
$build = Join-Path $env:LOCALAPPDATA ('halcyon-evidence\tape-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $build | Out-Null
python -B Tools/build_world_tape.py `
  --pcap .\Local\research\vg_max\vgfull.pcap `
  --match-uuid b9f511e0-11cd-4cfa-ad62-dc8612b8d270 `
  --output "$build\world_tape.bin"
if ($LASTEXITCODE -ne 0) { throw 'Tape rebuild failed; preserve candidate/report and inspect them' }

# Install only if the runtime tape is absent. Preserve existing candidates.
$target = Join-Path $PWD 'Local\runtime\halcyon_stack\world_tape.bin'
if (Test-Path -LiteralPath $target) { throw 'Runtime tape exists; compare before replacing it' }
Copy-Item -LiteralPath "$build\world_tape.bin" -Destination $target
python -B Tools/setup_local.py --check
```

Require the builder's production-pin verdict. The trimmed measured tape has
SHA-256 `20c553224e5523ff354536fc4594230ebec76e1ea72755de8c855b8cead1d341`.
The 53,632-byte figure in historical notes describes an earlier untrimmed file;
size alone is not the production validation contract. Do not install
`*.candidate-unvalidated.bin` or pass a custom expected digest to manufacture
a production PASS.

## 8. Start the local stack and install guest routing

Close the game first. For the first run, use a foreground server terminal so
errors remain visible:

```powershell
python -B -u -m server.platform.local_stack --bind-host 127.0.0.1 --match-host 127.0.0.1
```

In a second terminal with the same venv/ADB PATH and data overrides:

```powershell
python -B -m server.platform.guest_setup --serial emulator-5554 `
  --gateway-port 7100 --heartbeat-port 2112 --host-http 9080 --host-https 9443
```

Require `[guest] RESULT: OK`. The script discovers the installed package UID
(do not copy the old value `10060`), checks root, installs hosts/CA overlays,
applies owner-specific local-only IPv4/IPv6 rules, sets ADB reverse mappings and
checks guest DNS. The CA overlay is refreshed when the local CA changes. An
explicit `--uid` is available when the discovered installation intentionally
needs an override.

The guest uses loopback; it is **ADB reverse** that carries traffic to the host:

| Guest request | Host listener / purpose |
|---|---|
| Loopback port 80, redirected to 8080 | ADB reverse to host **9080**, HTTP/bootstrap/notify. |
| Loopback 443 redirected to 8443, or direct 8443 | ADB reverse to host **9443**, TLS JSON-RPC. |
| 7100 | TCP gateway/match stream. |
| 2112 | TCP heartbeat listener in this local implementation. |

The server also opens 8080/8443 and attempts 80/443. Preserve actual startup
logs if another process owns ports. This same-host route does not require a
Windows hosts edit, a Windows root-store CA import, public DNS changes, or a
router port forward. The game UID's nonlocal traffic is rejected; everything
tested here belongs to your own server and instance.

For later restarts, the existing helper stops prior stack processes, starts a
new detached one and reapplies guest routing:

```powershell
python -B -m server.platform.live_up --serial emulator-5554 `
  --bind-host 127.0.0.1 --match-host 127.0.0.1
```

It appends to `Local/runtime/halcyon_stack/live-stdout.txt`. A foreground process
can be stopped with Ctrl+C. For a detached one, stop only the stack PID printed
by the helper; do not kill every Python process. Stop/relaunch the game after
a server restart. An emulator reboot clears mounts; an ADB server restart
clears reverse mappings. Reapply `guest_setup` after either.

## 9. Launch and verify the rendered client

After routing passes:

```powershell
adb -s emulator-5554 shell am force-stop com.superevilmegacorp.game
adb -s emulator-5554 shell am start -n com.superevilmegacorp.game/com.superevilmegacorp.nuogameentry.NuoActivityLauncher
```

Follow **PLAY → SOLO BOTS → 3V3 → VERY EASY**, select an implemented hero such
as Skye, lock in, then choose **Manual Build** when offered. Wait for the world
to render. Selection/menu access is a prerequisite, not completed gameplay
acceptance. Individual hero kits remain incomplete.

Inspect `http_log.txt`, `rpc.jsonl`, `gateway_log.txt`, and the launch output
under the selected runtime directory. Do not erase old logs before retrying.
Record the client/source version, match identity and fresh evidence location.

## 10. Verification and continued development

Create a unique external evidence directory:

```powershell
$run = Join-Path $env:LOCALAPPDATA ('halcyon-evidence\setup-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $run | Out-Null
git status --short
git diff --stat
python -B -W error::ResourceWarning -m unittest discover -s server/test -t . *> "$run\unittest.txt"
$testExit = $LASTEXITCODE
Get-Content -LiteralPath "$run\unittest.txt" -Tail 12
if ($testExit -ne 0) { throw "Tests failed: $run\unittest.txt" }
python -B Tools/run_scenarios.py --mode headless --scenario all --output "$run\headless"
```

Require exit 0, inspect skip reasons, then inspect `headless/summary.json`.
The six scenarios must pass both seeded processes with exact events/states/
checkpoints and `workspace_matches_snapshot: true`. `reference: UNAVAILABLE`
means no independently measured reference fixture was supplied. Passing tests
does not imply rendered acceptance or official parity.

The importer tests are separately reproducible with
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File Tools/test_import_local_data.ps1`.
They use unique external fixtures and retain a result record.

For rendered scenarios, use the shipped path
`Tools/run_scenarios.py --mode client`; start with
[the scenario commands and declared-fixture contract](../Plan/solo-sandbox-scenarios.md#rendered-client-driver-toolsscenario_clientpy).
Set an external `HALCYON_QA_DIR` **before** launching a dedicated QA stack,
enable `HALCYON_TRACE_WIRE=1`, retain the external trace path printed by the
server (`%TEMP%/halcyon_stack/wire-*.jsonl`), choose the matching client profile, and let the script
own the time-sensitive input sequence. QA preparation/forced state is not proof
of ordinary player behavior. Do not introduce another scenario engine or
manually interrupt a short hit→cast sequence with reasoning/tool round trips.

For implementation work, use this routing order:

| Work | Start here |
|---|---|
| Current defects and next acceptance work | [Current status](../Plan/current-status.md), then the linked subsystem leaf. |
| Solo gameplay acceptance | [Solo sandbox](../Plan/solo-sandbox.md). |
| Scenario/harness changes | [Scenario record](../Plan/solo-sandbox-scenarios.md), `Tools/run_scenarios.py`, `Tools/scenario_client.py`. |
| Simulation | Relevant `server/` subsystem and production `SnapshotStream.advance_simulation`. |
| Wire/platform/routing | [Mobile local stack](../Teardown/vainglory-mobile-local-stack.md), then its targeted protocol links. |
| Store/navigation extraction | [Store format](../Teardown/vainglory-store-format.md) and existing `Tools/Teardown/` inspectors. |

Read `AGENTS.md`, keep determinism exact, never weaken checks, and do not commit
unless asked. Report affected files, verification, and unresolved limitations.
The roughly 30-minute idle client crash and complete two-client combat/PvP
acceptance remain open; this setup work does not close them.

## 11. Troubleshooting

| Symptom | Check / recovery |
|---|---|
| `adb` not found | Add the directory containing Google's `adb.exe` and its DLLs to this terminal's PATH. |
| Device is listed but shell hangs | Confirm correct instance. Reboot that instance, then one bounded `adb kill-server`, `adb start-server`, `adb connect 127.0.0.1:5555` recovery for instance 0; reapply routing afterwards. |
| `su` denied / nonroot | Enable LDPlayer root, save, reboot, then verify `su -c id`. |
| Wrong package or OBB error | Verify build 147219, OBB filename/location/size and host hashes. Preserve the instance before resolving a signature mismatch. |
| `external jungle spawn records missing for 363` | Restore the owned Kraken anchor and the other spawn directories; inspect `HALCYON_SPAWN_CORPUS`, then rerun the production setup checker. |
| Skye volley `.32` or `.36` missing | Restore both exact recorded chunks in `research/runtime-corpus`, or set `HALCYON_SKYE_VOLLEY_CORPUS`. |
| Full capture test is skipped | The complete original capture is absent. Three runtime records do not supply it. A skip is not a passing corpus comparison. |
| `Unable to connect` at menu | Check stack TLS listener, CA match, guest hosts, reverses, game UID rules, and `rpc.jsonl`. Use the existing TLS compatibility code; do not randomly lower TLS security levels. |
| World remains black or crashes on entry | Validate the tape digest and spawn loaders before diagnosing gameplay. Preserve Android crash and gateway evidence. |
| Port bind failure | Inspect `Get-NetTCPConnection -State Listen` and the owning PID. Stop only your prior stack; record unrelated conflicts. |
| Missing data after moving to another drive | Set `HALCYON_LOCAL_ROOT` to your new `Local` path and recheck. Do not carry old absolute environment overrides into a new checkout. |
| New CA but TLS still fails | Reapply `guest_setup` with the certificate for the running host. The actual mounted PEM must match; a foreign mount containing an old CA reports `CONFLICT` instead of success. Preserve the mount listing and restore the dedicated test instance's known setup before continuing. |
| Scenario output path rejected | Use a new directory outside the checkout, without a symlink/junction, and leave existing output intact. |

## 12. LAN and multiple clients

Finish the same-machine workflow first. A LAN listener and two selected heroes
do not establish accepted PvP. For a host on `192.168.1.50`, use your actual
private address and the existing launcher:

```powershell
python -B -m server.platform.live_up --bind-host 0.0.0.0 --match-host 192.168.1.50
```

Configure each owned remote instance with its own discovered game UID, that
host address, and **the host's public CA certificate** (never its private key):

```powershell
python -B -m server.platform.guest_setup --serial emulator-5554 `
  --host 192.168.1.50 --cert .\Local\runtime\host-platform-cert.pem `
  --http 9080 --https 9443 --redirect-lan --gateway-port 7100 --heartbeat-port 2112
```

Here guest 80/443 use DNAT to the host ports; unlike same-host mode there are
no ADB reverse mappings. Permit the required TCP ports in the host's Private
network firewall for the friend LAN. Review
`server/platform/setup_firewall.ps1` before applying it as administrator: its
historical rule list is broader and differs from these drift ports. Do not
expose this experimental service to the public Internet as part of setup.

Cloned same-host emulators can share hardware identity. The existing
`live_up --device-serial emulator-5556 --device-host-https 9444` option gives the
second instance a distinct TLS listener identity. Keep one runtime owner per
emulator and read the [mobile routing record](../Teardown/vainglory-mobile-local-stack.md)
before evaluating multiple clients.

## 13. Relocation and validation record

The September 13 import retains the external originals and historical evidence.
Primary game/research/runtime inputs now have documented project-local targets;
installed LDPlayer/SDK/Python and fresh evidence remain in their normal locations.
The import manifest is the authoritative per-file copy/hash record. Check its
`status` is `COMPLETE` before calling that import finished.

Completed import: **75,465 input files, 8,522,759,246 bytes**. The game tree
contains 71,649 files / 7,332,995,562 bytes; research/runtime inputs account for
the remaining 3,816 files / 1,189,763,684 bytes. Sources remain preserved. The
two complete, Git-ignored inventories are:

- `Local/manifests/import-20260913T033050029Z-95d4f586e5574064a0a61cb3f8def756.json`
- `Local/manifests/import-20260913T033050036Z-d8698686bb35420bab09c9c859865c53.json`

An earlier import was interrupted to replace slow PowerShell ancestor checks
with equivalent .NET checks. Its journal remains preserved; the complete game
import re-hashed all 9,469 already copied files and copied the other 62,180.

The current interpreter was recreated in `.venv` from `requirements-research.txt`;
installation and `pip check` passed. A read-only setup check passed with
`HALCYON_LOCAL_ROOT` set to this project's `Local` directory and serial
`emulator-5554`: APK/OBB identity, production simulation loaders, the 1,458-record
world tape, config/key pair, root, installed build and guest OBB size all passed.
This did not reinstall the emulator or perform a fresh rendered gameplay run.

All six production headless scenarios passed exact event/state/checkpoint
comparison across seeds 11 and 7919. Source manifest SHA-256:
`e5a71f214dc5f2671fb8d1e8bf93eceac07df8ce83c28cfd193acf613dc87fd2`;
`workspace_matches_snapshot` was true and independent reference remained
`UNAVAILABLE`. Eight importer fixture groups also passed, including default
destination resolution under Windows PowerShell 5.1, idempotent import,
conflict refusal and reparse/overlap checks.

Evidence root:
`%LOCALAPPDATA%/halcyon-evidence/halcyon-setup-20260913-4f72aa409e0845c0ac050df696303edb/`
contains `setup-check.txt`, `headless-console.txt` and `headless/summary.json`.
Importer fixture evidence is
`%TEMP%/halcyon-import-test-195995de78e944e481015eaa5b95abc4/test-results.json`.

The full suite ran in the freshly created venv with `HALCYON_LOCAL_ROOT` pointing
at the imported project-local inputs:
`python -B -W error::ResourceWarning -m unittest discover -s server/test -t . -v`.
Result: **1,176 tests in 904.996 seconds, OK (27 skipped), exit 0**.
`unittest.txt` and `unittest-exit.txt` are in the evidence root above. Skips
include unavailable complete original Phase B/Catherine/lifecycle capture
fixtures and historical bootstrap comparison tapes; they are not passing
corpus comparisons. No assertion or skip condition was weakened.

All 17 PowerShell example blocks passed parser checks after substituting the
repository URL placeholder, local documentation links resolve, and
`git diff --check` passes. `git ls-files Local` is empty. The existing live
stack was not restarted or presented as new rendered gameplay acceptance.
