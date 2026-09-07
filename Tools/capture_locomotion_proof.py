import io
import os
import subprocess
import time
from PIL import Image

SERIAL = "emulator-5554"
OUT_DIR = os.path.join(os.environ.get("TEMP", "."), "halcyon_stack", "locomotion_proof")
os.makedirs(OUT_DIR, exist_ok=True)

def tap(x, y):
    subprocess.run(["adb", "-s", SERIAL, "shell", "input", "tap", str(x), str(y)], check=True)

def screencap():
    res = subprocess.run(["adb", "-s", SERIAL, "exec-out", "screencap", "-p"], capture_output=True, check=True)
    return Image.open(io.BytesIO(res.stdout)).convert("RGB")

print("1. Capturing idle frame before move...")
idle_before = screencap()
idle_before.save(os.path.join(OUT_DIR, "00_idle_before.png"))

print("2. Tapping move order at (700, 350)...")
tap(700, 350)

print("3. Capturing 12 burst transit frames (~120ms intervals)...")
for i in range(12):
    t0 = time.time()
    img = screencap()
    path = os.path.join(OUT_DIR, f"transit_{i:02d}.png")
    img.save(path)
    dt = time.time() - t0
    print(f"   Saved transit_{i:02d}.png ({dt*1000:.1f}ms)")
    if dt < 0.12:
        time.sleep(0.12 - dt)

print("4. Waiting for hero to stop (3.0s)...")
time.sleep(3.0)

print("5. Capturing idle frame after arrival...")
idle_after = screencap()
idle_after.save(os.path.join(OUT_DIR, "01_idle_after.png"))
print("Done! All proof frames saved to", OUT_DIR)
