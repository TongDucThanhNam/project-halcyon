import io
import os
import subprocess
import sys
import time
from PIL import Image

SERIAL = "emulator-5554"
OUT_DIR = os.path.join(os.environ.get("TEMP", "."), "halcyon_stack", "locomotion_verify")
os.makedirs(OUT_DIR, exist_ok=True)

def screencap() -> bytes:
    res = subprocess.run(["adb", "-s", SERIAL, "exec-out", "screencap", "-p"], capture_output=True)
    return res.stdout

def tap(x: int, y: int):
    subprocess.run(["adb", "-s", SERIAL, "shell", "input", "tap", str(x), str(y)])

print("Waiting for 3D world entry...")
deadline = time.time() + 60
in_world = False

while time.time() < deadline:
    raw = screencap()
    if not raw:
        time.sleep(1)
        continue
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    # In loading screen, bottom center has "Pro Tip: ...", background is dark blue/black.
    # When world loads, either "Choose a Build" overlay appears (white text "Choose a Build" at top left),
    # or the 3D map appears.
    # Let's check pixel at (100, 100): in loading screen it's dark (Amael portrait is at 190, 100).
    # Specifically, check top left (50, 50): in loading screen it's very dark (0-20),
    # in "Choose a Build" it has bright text or stones.
    # Also check center (480, 40): in "Choose a Build" it has "Prepare For Battle..." text (bright).
    r_center, g_center, b_center = img.getpixel((480, 35))
    r_tip, g_tip, b_tip = img.getpixel((480, 520)) # "Pro Tip" area
    
    # In loading screen, (480, 35) is dark background (e.g. < 30).
    # In world / Choose a Build, (480, 35) is bright (text: "Prepare For Battle...").
    # Or in 3D world, top is trees / UI.
    if r_center > 100 and g_center > 100 and b_center > 100:
        print("Detected 'Prepare For Battle' / Choose a Build overlay!")
        in_world = True
        break
    
    # Or if top center has HUD clock
    if img.getpixel((480, 15))[0] > 150:
        print("Detected HUD clock / world!")
        in_world = True
        break

    time.sleep(1)

if not in_world:
    print("Did not detect world entry within timeout, taking screen and proceeding anyway...")
    raw = screencap()
    img = Image.open(io.BytesIO(raw))
    img.save(os.path.join(OUT_DIR, "timeout_debug.png"))

print("Dismissing build selection (tap 885, 395)...")
tap(885, 395)
time.sleep(0.5)
tap(885, 395) # tap again in case
time.sleep(0.5)

print("Ordering hero move across the lane (tap 600, 300)...")
tap(600, 300)

print("Capturing burst of rapid screencaps (10 frames, ~150ms apart)...")
frames = []
for i in range(10):
    t0 = time.time()
    raw = screencap()
    fn = os.path.join(OUT_DIR, f"frame_{i:02d}.png")
    with open(fn, "wb") as f:
        f.write(raw)
    dt = time.time() - t0
    print(f"Captured {fn} (took {dt*1000:.1f}ms)")
    if dt < 0.15:
        time.sleep(0.15 - dt)

print("Burst capture complete!")
