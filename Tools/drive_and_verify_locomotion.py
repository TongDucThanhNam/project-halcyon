"""Drive emulator into match and capture locomotion frames."""
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
    print("1. Tapping PLAY (820, 470)...")
    tap(820, 470)
    time.sleep(1.5)

    print("2. Tapping SOLO BOT (880, 420)...")
    tap(880, 420)
    time.sleep(1.5)

    print("3. Tapping 3V3 (740, 300)...")
    tap(740, 300)
    time.sleep(1.5)

    print("4. Tapping VERY EASY (745, 185)...")
    tap(745, 185)
    time.sleep(2.5)

    print("5. Checking Hero Select...")
    img = screencap()
    # Check green LOCK IN button at (480, 490)
    r, g, b = img.getpixel((480, 490))
    print(f"   Pixel at (480, 490): R={r}, G={g}, B={b}")
    img.save(os.path.join(OUT_DIR, "step1_hero_select.png"))

    print("6. Tapping LOCK IN (480, 490)...")
    tap(480, 490)
    print("   Hero locked in! Waiting 8s for lock timer...")
    time.sleep(8.0)

    # Now monitor for loading screen completion
    print("7. Monitoring for 3D world entry...")
    t0 = time.time()
    world_entered = False
    for attempt in range(40):
        time.sleep(1.0)
        img = screencap()
        # In loading screen, (480, 270) has the VS logo (cyan/blue or bright)
        # and (50, 20) is black.
        # When 3D world loads:
        # Either "Choose a Build" is showing (top text "Choose a Build", "Prepare For Battle..."),
        # or the 3D ground is visible.
        # Let's check pixel at (885, 395) - the SELECT button!
        # In loading screen, (885, 395) is inside Gamma Bot Baptiste's card (red/purple coat).
        # In "Choose a Build", (885, 395) is the SELECT button (dark box with white border).
        # Also check (100, 100): in loading screen (100, 100) is black (background outside portrait).
        # In "Choose a Build", (100, 100) is the semi-transparent black overlay over the 3D map.
        # What definitely changes is the VS logo at (480, 270):
        # In loading screen: (480, 270) is the VS logo.
        # In "Choose a Build": (480, 270) is the 3D stone floor / base platform visible through the dialog!
        # And the "SELECT" text at (885, 390) has white pixels:
        select_px = [img.getpixel((885, y)) for y in range(380, 410)]
        has_select_btn = any(p[0] > 200 and p[1] > 200 and p[2] > 200 for p in select_px)
        
        # Also check HUD clock / top bar in 3D world
        top_px = [img.getpixel((x, 15)) for x in range(450, 510, 5)]
        has_hud = any(p[0] > 180 and p[1] > 180 and p[2] > 180 for p in top_px)

        if has_select_btn:
            print(f"   Detected 'Choose a Build' overlay with SELECT button at +{time.time()-t0:.1f}s!")
            world_entered = True
            img.save(os.path.join(OUT_DIR, "step2_build_overlay.png"))
            break
        elif has_hud and attempt > 5:
            print(f"   Detected 3D world HUD at +{time.time()-t0:.1f}s!")
            world_entered = True
            img.save(os.path.join(OUT_DIR, "step2_world_hud.png"))
            break
        else:
            print(f"   [+{time.time()-t0:.1f}s] Loading... (has_select={has_select_btn}, has_hud={has_hud})")

    if not world_entered:
        print("   Timeout waiting for world detection! Capturing debug screencap...")
        img = screencap()
        img.save(os.path.join(OUT_DIR, "debug_timeout.png"))

    print("8. Dismissing build overlay (tapping 885, 395)...")
    tap(885, 395)
    time.sleep(0.3)
    tap(885, 395)
    time.sleep(0.5)

    print("9. Capturing initial stationary frame...")
    f_idle0 = screencap()
    f_idle0.save(os.path.join(OUT_DIR, "00_stationary_before_move.png"))

    print("10. Ordering hero move across lane: tap (600, 300)...")
    tap(600, 300)

    print("11. Capturing burst of rapid transit frames...")
    transit_frames = []
    for i in range(10):
        t_start = time.time()
        f = screencap()
        p = os.path.join(OUT_DIR, f"transit_{i:02d}.png")
        f.save(p)
        transit_frames.append(p)
        dt = time.time() - t_start
        print(f"    Captured frame {i}: {p} (latency {dt*1000:.1f}ms)")
        if dt < 0.15:
            time.sleep(0.15 - dt)

    print("12. Waiting 3.5s for hero arrival at destination...")
    time.sleep(3.5)

    print("13. Capturing arrival idle frames...")
    for i in range(3):
        f = screencap()
        p = os.path.join(OUT_DIR, f"arrival_idle_{i:02d}.png")
        f.save(p)
        print(f"    Captured arrival idle frame {i}: {p}")
        time.sleep(0.25)

    print("DONE! All verification frames recorded successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
