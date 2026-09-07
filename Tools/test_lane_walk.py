import io
import os
import subprocess
import time
from PIL import Image

SERIAL = "emulator-5554"
OUT_DIR = os.path.join(os.environ.get("TEMP", "."), "halcyon_stack", "lane_walk_proof")
os.makedirs(OUT_DIR, exist_ok=True)

def tap(x, y):
    subprocess.run(["adb", "-s", SERIAL, "shell", "input", "tap", str(x), str(y)], check=True)

def screencap():
    res = subprocess.run(["adb", "-s", SERIAL, "exec-out", "screencap", "-p"], capture_output=True, check=True)
    return Image.open(io.BytesIO(res.stdout)).convert("RGB")

print("1. Capturing pre-move frame...")
f0 = screencap()
f0.save(os.path.join(OUT_DIR, "00_before_lane_walk.png"))

print("2. Tapping move order on minimap lane turret (100, 60)...")
tap(100, 60)

print("3. Capturing 10 transit frames across 3 seconds...")
for i in range(10):
    t0 = time.time()
    img = screencap()
    p = os.path.join(OUT_DIR, f"walk_{i:02d}.png")
    img.save(p)
    dt = time.time() - t0
    print(f"   Frame {i}: {p} ({dt*1000:.1f}ms)")
    if dt < 0.25:
        time.sleep(0.25 - dt)

print("Done! Check frames in", OUT_DIR)
