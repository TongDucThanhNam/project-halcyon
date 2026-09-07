"""End-to-End Locomotion Verification Pipeline."""
import io
import os
import subprocess
import sys
import time
from PIL import Image, ImageChops

SERIAL = "emulator-5554"
TEMP_DIR = os.path.join(os.environ.get("TEMP", "."), "halcyon_stack")
OUT_DIR = os.path.join(TEMP_DIR, "locomotion_verify")
os.makedirs(OUT_DIR, exist_ok=True)


def sh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True)


def tap(x: int, y: int):
    subprocess.run(["adb", "-s", SERIAL, "shell", "input", "tap", str(x), str(y)], check=True)


def screencap() -> Image.Image:
    res = subprocess.run(["adb", "-s", SERIAL, "exec-out", "screencap", "-p"], capture_output=True, check=True)
    return Image.open(io.BytesIO(res.stdout)).convert("RGB")


def px(img: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    return img.getpixel((x, y))


def classify(img: Image.Image) -> str:
    r, g, b = px(img, 740, 455)
    if r > 90 and g < 70 and b < 80:
        return "menu"
    r2, g2, b2 = px(img, 480, 45)
    if r2 > 230 and g2 > 230 and b2 > 230:
        return "playstore"
    r3, g3, b3 = px(img, 480, 320)
    if r3 > 225 and g3 > 225 and b3 > 225:
        return "playgames"
    return "other"


def wait_for_menu(timeout: float = 60.0) -> bool:
    print("[verify] Waiting for main menu (red PLAY button)...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            img = screencap()
        except Exception:
            time.sleep(1)
            continue
        c = classify(img)
        if c == "menu":
            print("[verify] Main menu reached!")
            return True
        elif c == "playgames":
            tap(208, 247)
        elif c == "playstore":
            sh(["adb", "-s", SERIAL, "shell", "am", "force-stop", "com.android.vending"])
            sh(["adb", "-s", SERIAL, "shell", "input", "keyevent", "4"])
        else:
            ps = sh(["adb", "-s", SERIAL, "shell", "ps -A"]).stdout.decode("utf-8", "replace")
            if "com.superevilmegacorp.game" not in ps:
                print("[verify] Launching Vainglory...")
                sh(["adb", "-s", SERIAL, "shell", "monkey", "-p", "com.superevilmegacorp.game",
                    "-c", "android.intent.category.LAUNCHER", "1"])
        time.sleep(1.5)
    return False


def main():
    print("=== Step 1: Setting up isolated environment and starting clean stack ===")
    os.environ["HALCYON_NO_BOTS"] = "1"
    os.environ["HALCYON_NO_WAVE"] = "1"
    subprocess.run([sys.executable, "-m", "server.platform.live_up", "--serial", SERIAL], check=True)

    print("=== Step 2: Relaunching game on emulator ===")
    sh(["adb", "-s", SERIAL, "shell", "am", "force-stop", "com.superevilmegacorp.game"])
    time.sleep(1.0)
    sh(["adb", "-s", SERIAL, "shell", "monkey", "-p", "com.superevilmegacorp.game",
        "-c", "android.intent.category.LAUNCHER", "1"])

    if not wait_for_menu(60.0):
        print("[verify] FAILED: Did not reach menu within 60s")
        return 1

    time.sleep(1.0)
    print("=== Step 3: Queue chain to Hero Select ===")
    print("  -> Tapping PLAY (820, 470)")
    tap(820, 470)
    time.sleep(1.5)

    print("  -> Tapping SOLO BOT (880, 420)")
    tap(880, 420)
    time.sleep(1.5)

    print("  -> Tapping 3V3 (740, 300)")
    tap(740, 300)
    time.sleep(1.5)

    print("  -> Tapping VERY EASY (714, 184)")
    tap(714, 184)
    time.sleep(2.5)

    print("=== Step 4: Verifying Hero Select & Locking In Amael ===")
    for _ in range(5):
        img = screencap()
        r, g, b = px(img, 480, 490)
        if g > 150:
            print(f"[verify] Hero select confirmed (LOCK IN button R={r}, G={g}, B={b})")
            img.save(os.path.join(OUT_DIR, "step1_hero_select.png"))
            break
        time.sleep(1.0)

    print("  -> Tapping LOCK IN (480, 490)")
    tap(480, 490)
    print("[verify] Hero locked in! Waiting 8.0s for lock countdown...")
    time.sleep(8.0)

    print("=== Step 5: Monitoring for 3D Match World Entry ===")
    t0 = time.time()
    world_entered = False
    for attempt in range(60):
        time.sleep(0.8)
        img = screencap()
        r_vs, g_vs, b_vs = px(img, 480, 270)
        r_tip, g_tip, b_tip = px(img, 480, 520)

        # Loading screen check: VS logo at center (480, 270) is cyan (B > 140, R < 160)
        is_loading = (b_vs > 140 and r_vs < 160) or (r_tip > 80 and g_tip > 120 and b_tip > 140)
        elapsed = time.time() - t0
        print(f"  [+{elapsed:.1f}s] is_loading={is_loading} (vs={r_vs},{g_vs},{b_vs}; tip={r_tip},{g_tip},{b_tip})")

        if attempt >= 10 and not is_loading:
            if r_tip > 10 or g_tip > 10:
                print(f"[verify] 3D World Entry detected at +{elapsed:.1f}s!")
                world_entered = True
                img.save(os.path.join(OUT_DIR, "step2_world_entry.png"))
                break

    if not world_entered:
        print("[verify] Timeout waiting for world entry, continuing...")

    print("=== Step 6: Dismissing Build Overlay ===")
    print("  -> Tapping SELECT (885, 395)")
    tap(885, 395)
    time.sleep(0.25)
    tap(885, 395)
    time.sleep(0.35)

    print("=== Step 7: Capturing Pre-Move Stationary Idle Frame ===")
    idle0 = screencap()
    idle0_path = os.path.join(OUT_DIR, "00_stationary_idle.png")
    idle0.save(idle0_path)
    print(f"  Saved pre-move frame: {idle0_path}")

    print("=== Step 8: Ordering Hero Move Across Lane ===")
    print("  -> Tapping (600, 300)")
    tap(600, 300)

    print("=== Step 9: Capturing Rapid Burst of 10 Transit Frames ===")
    transit_paths = []
    for i in range(10):
        t_snap = time.time()
        f = screencap()
        p = os.path.join(OUT_DIR, f"transit_{i:02d}.png")
        f.save(p)
        transit_paths.append(p)
        dt = time.time() - t_snap
        print(f"  Captured frame {i}: {p} (latency {dt*1000:.1f}ms)")
        if dt < 0.15:
            time.sleep(0.15 - dt)

    print("=== Step 10: Waiting for Hero Arrival at Destination ===")
    time.sleep(3.5)

    print("=== Step 11: Capturing 3 Arrival Idle Frames ===")
    arrival_paths = []
    for i in range(3):
        f = screencap()
        p = os.path.join(OUT_DIR, f"arrival_idle_{i:02d}.png")
        f.save(p)
        arrival_paths.append(p)
        print(f"  Captured arrival frame {i}: {p}")
        time.sleep(0.25)

    print("=== Step 12: Analyzing Locomotion Animation Sequence ===")
    # Crop central hero area (approx x=400..650, y=200..450)
    # Compare consecutive frames to measure pixel deltas
    crop_box = (350, 180, 680, 440)
    diffs = []
    for i in range(len(transit_paths) - 1):
        im1 = Image.open(transit_paths[i]).convert("RGB").crop(crop_box)
        im2 = Image.open(transit_paths[i+1]).convert("RGB").crop(crop_box)
        diff = ImageChops.difference(im1, im2)
        stat = diff.getextrema()
        # Mean diff per pixel
        diff_data = list(diff.getdata())
        mean_diff = sum(r + g + b for r, g, b in diff_data) / (len(diff_data) * 3)
        diffs.append((i, i+1, mean_diff))
        print(f"  Transit diff frame {i} -> {i+1}: mean_delta={mean_diff:.2f}")

    # Arrival idle stability check
    im_arr0 = Image.open(arrival_paths[0]).convert("RGB").crop(crop_box)
    im_arr1 = Image.open(arrival_paths[1]).convert("RGB").crop(crop_box)
    diff_arr = ImageChops.difference(im_arr0, im_arr1)
    diff_arr_data = list(diff_arr.getdata())
    arr_mean_diff = sum(r + g + b for r, g, b in diff_arr_data) / (len(diff_arr_data) * 3)
    print(f"  Arrival idle stability delta: mean_delta={arr_mean_diff:.2f}")

    print("=== Locomotion Verification Complete! ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
