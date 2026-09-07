import io
import os
import subprocess
import sys
import time
from PIL import Image

SERIAL = "emulator-5554"
OUT_DIR = os.path.join(os.environ.get("TEMP", "."), "halcyon_stack", "locomotion_verify")
os.makedirs(OUT_DIR, exist_ok=True)


def tap(x: int, y: int):
    subprocess.run(["adb", "-s", SERIAL, "shell", "input", "tap", str(x), str(y)], check=True)


def screencap() -> Image.Image:
    res = subprocess.run(["adb", "-s", SERIAL, "exec-out", "screencap", "-p"], capture_output=True, check=True)
    return Image.open(io.BytesIO(res.stdout)).convert("RGB")


def main():
    print("[locomotion] 1. Tapping LOCK IN (480, 490)...")
    tap(480, 490)
    print("[locomotion] 2. Waiting 8.0s for lock countdown...")
    time.sleep(8.0)

    print("[locomotion] 3. Monitoring loading screen -> 3D world transition...")
    t0 = time.time()
    world_entered = False

    for attempt in range(60):
        time.sleep(0.8)
        img = screencap()
        
        # In loading screen, center (480, 270) has the 'VS' logo:
        # The VS letters are cyan/blue: B is dominant (e.g. B > 180, R < 150).
        # Also bottom center (480, 520) has 'Pro Tip: ...'
        r_vs, g_vs, b_vs = img.getpixel((480, 270))
        r_tip, g_tip, b_tip = img.getpixel((480, 520))

        # Check if we are still on the loading screen:
        is_loading = (b_vs > 140 and r_vs < 160) or (r_tip > 80 and g_tip > 120 and b_tip > 140)

        elapsed = time.time() - t0
        print(f"   [+{elapsed:.1f}s] is_loading={is_loading} (vs={r_vs},{g_vs},{b_vs}; tip={r_tip},{g_tip},{b_tip})")

        # After at least 10s of loading, once is_loading becomes False:
        if attempt >= 10 and not is_loading:
            # Verify screen is not black
            avg_brightness = sum(img.getpixel((x, y))[0] for x, y in [(200, 200), (400, 300), (600, 200), (800, 300)]) / 4
            if avg_brightness > 20:
                print(f"[locomotion] 3D World / Build overlay detected at +{elapsed:.1f}s (brightness={avg_brightness:.1f})!")
                world_entered = True
                img.save(os.path.join(OUT_DIR, "step_world_enter.png"))
                break

    if not world_entered:
        print("[locomotion] Warning: timeout waiting for transition, continuing with taps...")
        img = screencap()
        img.save(os.path.join(OUT_DIR, "timeout_debug.png"))

    print("[locomotion] 4. Dismissing build overlay (tap SELECT at 885, 395)...")
    tap(885, 395)
    time.sleep(0.3)
    tap(885, 395)
    time.sleep(0.4)

    print("[locomotion] 5. Capturing stationary idle frame before move...")
    idle0 = screencap()
    idle0_path = os.path.join(OUT_DIR, "00_stationary_idle.png")
    idle0.save(idle0_path)
    print(f"   Saved {idle0_path}")

    print("[locomotion] 6. Ordering hero move across lane: tap (600, 300)...")
    tap(600, 300)

    print("[locomotion] 7. Capturing rapid burst of 10 transit frames...")
    transit_paths = []
    for i in range(10):
        t_snap = time.time()
        f = screencap()
        p = os.path.join(OUT_DIR, f"transit_{i:02d}.png")
        f.save(p)
        transit_paths.append(p)
        dt = time.time() - t_snap
        print(f"   Frame {i}: {p} (latency {dt*1000:.1f}ms)")
        if dt < 0.15:
            time.sleep(0.15 - dt)

    print("[locomotion] 8. Waiting 3.5s for arrival at destination...")
    time.sleep(3.5)

    print("[locomotion] 9. Capturing 3 arrival idle frames...")
    for i in range(3):
        f = screencap()
        p = os.path.join(OUT_DIR, f"arrival_idle_{i:02d}.png")
        f.save(p)
        print(f"   Arrival idle {i}: {p}")
        time.sleep(0.25)

    print("[locomotion] SUCCESS: Frame capture sequence completed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
