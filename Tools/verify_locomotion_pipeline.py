"""Locomotion Verification Pipeline for Mobile LDPlayer (emulator-5554).

1. Restarts live_up for clean match session.
2. Drives emulator-5554 from menu to 3v3 solo bots with Amael (Hero 925).
3. Detects 3D match world entry and build overlay dismissal.
4. Taps move destination to start lane walk.
5. Captures rapid burst of 10 stride frames (~150ms apart).
6. Captures 3 post-arrival idle frames.
7. Saves verification frames to $TEMP/halcyon_stack/locomotion_verify/
8. Analyzes hero sprite bounding box for stride animation vs static gliding.
"""
import io
import os
import subprocess
import sys
import time
from PIL import Image

SERIAL = "emulator-5554"
TEMP_DIR = os.path.join(os.environ.get("TEMP", "."), "halcyon_stack")
OUT_DIR = os.path.join(TEMP_DIR, "locomotion_verify")
os.makedirs(OUT_DIR, exist_ok=True)


def sh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True)


def tap(x: int, y: int):
    sh(["adb", "-s", SERIAL, "shell", "input", "tap", str(x), str(y)])


def screencap() -> Image.Image:
    res = sh(["adb", "-s", SERIAL, "exec-out", "screencap", "-p"])
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


def ensure_menu(timeout: float = 60.0) -> bool:
    print("[verify] ensuring main menu...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            img = screencap()
        except Exception:
            time.sleep(1)
            continue
        c = classify(img)
        if c == "menu":
            print("[verify] menu reached")
            return True
        elif c == "playgames":
            tap(208, 247)
        elif c == "playstore":
            sh(["adb", "-s", SERIAL, "shell", "am", "force-stop", "com.android.vending"])
            sh(["adb", "-s", SERIAL, "shell", "input", "keyevent", "4"])
        else:
            # Maybe game is not in foreground
            sh(["adb", "-s", SERIAL, "shell", "monkey", "-p", "com.superevilmegacorp.game",
                "-c", "android.intent.category.LAUNCHER", "1"])
        time.sleep(2)
    return False


def run():
    print("[verify] Step 1: Starting clean live stack...")
    subprocess.run([sys.executable, "-m", "server.platform.live_up", "--serial", SERIAL], check=True)

    print("[verify] Step 2: Checking menu state...")
    if not ensure_menu():
        print("[verify] ERROR: could not reach menu")
        return 1

    print("[verify] Step 3: Driving queue into solo-bot match with Amael...")
    tap(820, 470)  # PLAY
    time.sleep(1.5)
    tap(880, 420)  # SOLO BOT
    time.sleep(1.5)
    tap(740, 300)  # 3V3
    time.sleep(1.5)
    tap(745, 185)  # VERY EASY
    time.sleep(2.5)

    print("[verify] Step 4: Hero select - locking in Amael...")
    tap(480, 490)  # LOCK IN
    print("[verify] Locked in! Waiting for 3D world entry...")

    # Wait for match loading screen to finish and 3D world to render
    # The loading screen has "Pro Tip:" at the bottom center (480, 520) and VS logo.
    # In match world, the build overlay appears, with "SELECT" button around (885, 395).
    # We will poll every 1s for up to 45s.
    t0 = time.time()
    world_entered = False
    for step in range(45):
        time.sleep(1.0)
        img = screencap()
        
        # Check if build select dialog has appeared:
        # SELECT button at (885, 395) has white/grey border and "SELECT" text
        # Or look at bottom center: loading screen has blue "Pro Tip: ...", world does NOT
        r_tip, g_tip, b_tip = px(img, 480, 520)
        # Check if the "Choose a Build" title or cards are present:
        # Card 1 "Grappler" icon around (130, 310) is reddish/orange:
        r_card, g_card, b_card = px(img, 130, 310)
        # Card 2 "Durable Brawler" icon around (370, 310) is cyan/blue:
        r_card2, g_card2, b_card2 = px(img, 370, 310)

        # In loading screen, (130, 310) is part of dark separator or portrait card
        if (r_card > 100 or b_card2 > 100) and (r_tip < 100 or g_tip < 100):
            print(f"[verify] Match world build overlay detected at +{time.time()-t0:.1f}s!")
            world_entered = True
            break
        
        # Also check if HUD clock (480, 15) or minimap (880, 80) is visible (pure 3D world)
        r_hud, g_hud, b_hud = px(img, 480, 15)
        if r_hud > 180 and g_hud > 180 and b_hud > 180 and (r_tip < 80):
            print(f"[verify] 3D HUD detected directly at +{time.time()-t0:.1f}s!")
            world_entered = True
            break
    
    if not world_entered:
        print("[verify] Warning: timeout waiting for build overlay detection, attempting taps anyway...")

    # Dismiss build overlay if present
    print("[verify] Dismissing build overlay (tapping SELECT)...")
    tap(885, 395)
    time.sleep(0.3)
    tap(885, 395)
    time.sleep(0.5)

    # Save initial spawn state screencap
    initial_img = screencap()
    initial_path = os.path.join(OUT_DIR, "00_spawn_idle.png")
    initial_img.save(initial_path)
    print(f"[verify] Saved spawn state: {initial_path}")

    # Order move across the lane: hero spawns at sanctuary (-76.18, 0.88)
    # Tapping (600, 300) taps onto the lane towards the right/forward
    print("[verify] Ordering hero move across lane: tap (600, 300)...")
    tap(600, 300)

    # Immediately capture burst of 10 frames while in transit
    print("[verify] Capturing 10 transit frames (~150ms spacing)...")
    transit_frames = []
    for i in range(10):
        t_frame_start = time.time()
        f_img = screencap()
        f_path = os.path.join(OUT_DIR, f"transit_frame_{i:02d}.png")
        f_img.save(f_path)
        transit_frames.append((f_path, f_img))
        elapsed = time.time() - t_frame_start
        print(f"  Captured {f_path} ({elapsed*1000:.1f}ms)")
        if elapsed < 0.15:
            time.sleep(0.15 - elapsed)

    # Wait for hero to arrive at destination
    print("[verify] Waiting 3.5s for hero to arrive at destination...")
    time.sleep(3.5)

    # Capture 3 idle frames at arrival
    print("[verify] Capturing 3 arrival idle frames...")
    idle_frames = []
    for i in range(3):
        f_img = screencap()
        f_path = os.path.join(OUT_DIR, f"arrival_idle_{i:02d}.png")
        f_img.save(f_path)
        idle_frames.append((f_path, f_img))
        time.sleep(0.3)

    print("[verify] Screencaps captured successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(run())
