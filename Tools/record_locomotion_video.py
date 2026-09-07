import io
import os
import subprocess
import sys
import time
from PIL import Image

SERIAL = "emulator-5554"
ARTIFACT_DIR = r"C:\Users\terasumi\.gemini\antigravity\brain\8ee988e9-ac75-4cdc-b501-6701deccd33f"
OUT_VIDEO = os.path.join(ARTIFACT_DIR, "locomotion_proof.mp4")

def sh(cmd):
    return subprocess.run(cmd, capture_output=True)

def tap(x, y):
    subprocess.run(["adb", "-s", SERIAL, "shell", "input", "tap", str(x), str(y)], check=True)

def screencap():
    res = subprocess.run(["adb", "-s", SERIAL, "exec-out", "screencap", "-p"], capture_output=True, check=True)
    return Image.open(io.BytesIO(res.stdout)).convert("RGB")

def px(img, x, y):
    return img.getpixel((x, y))

def main():
    print("=== Step 1: Clean stack restart ===")
    os.environ["HALCYON_NO_BOTS"] = "1"
    os.environ["HALCYON_NO_WAVE"] = "1"
    subprocess.run([sys.executable, "-m", "server.platform.live_up", "--serial", SERIAL], check=True)

    print("=== Step 2: Ensure main menu ===")
    deadline = time.time() + 30
    menu_ready = False
    while time.time() < deadline:
        img = screencap()
        r, g, b = px(img, 740, 455)
        if r > 90 and g < 70 and b < 80:
            print("   Menu reached!")
            menu_ready = True
            break
        time.sleep(1.5)

    if not menu_ready:
        print("   Relaunching game...")
        sh(["adb", "-s", SERIAL, "shell", "monkey", "-p", "com.superevilmegacorp.game", "-c", "android.intent.category.LAUNCHER", "1"])
        time.sleep(6.0)

    print("=== Step 3: Driving into Match with Amael ===")
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

    print("  -> Tapping LOCK IN (480, 490)")
    tap(480, 490)
    print("   Locked in! Waiting for 3D world entry...")

    # Wait for "Choose a Build" dialog to appear
    t0 = time.time()
    for attempt in range(45):
        time.sleep(1.0)
        img = screencap()
        # In Choose a Build, (130, 300) is Grappler card (red/orange)
        r_card, g_card, b_card = px(img, 130, 300)
        r_tip, g_tip, b_tip = px(img, 480, 520)
        if r_card > 80 and (r_tip > 30 or g_tip > 30):
            print(f"   3D World detected at +{time.time()-t0:.1f}s!")
            break

    print("=== Step 4: Dismissing Build Overlay ===")
    # Tap Grappler card, then tap SELECT button
    tap(130, 300)
    time.sleep(0.4)
    tap(885, 430)
    time.sleep(0.8)

    print("=== Step 5: Starting screenrecord (15 seconds) ===")
    sh(["adb", "-s", SERIAL, "shell", "rm -f /sdcard/locomotion.mp4"])
    rec_proc = subprocess.Popen(["adb", "-s", SERIAL, "shell", "screenrecord", "--time-limit", "15", "/sdcard/locomotion.mp4"])
    time.sleep(1.5)  # Let recording start

    print("=== Step 6: Performing Hero Locomotion Sequence ===")
    print("  -> 1. Stationary idle on platform for 1.5s")
    time.sleep(1.5)

    print("  -> 2. Tapping lane walk destination (700, 450)")
    tap(700, 450)
    time.sleep(3.0)

    print("  -> 3. Tapping further down lane (600, 400)")
    tap(600, 400)
    time.sleep(3.5)

    print("  -> 4. Tapping back to base platform (450, 300)")
    tap(450, 300)
    time.sleep(3.5)

    print("=== Step 7: Waiting for screenrecord to finalize ===")
    rec_proc.wait(timeout=20)
    time.sleep(1.0)

    print("=== Step 8: Pulling video from emulator ===")
    sh(["adb", "-s", SERIAL, "pull", "/sdcard/locomotion.mp4", OUT_VIDEO])
    if os.path.exists(OUT_VIDEO):
        sz = os.path.getsize(OUT_VIDEO)
        print(f"SUCCESS: Recorded locomotion video: {OUT_VIDEO} ({sz:,} bytes)")
        return 0
    else:
        print("ERROR: Video pull failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
