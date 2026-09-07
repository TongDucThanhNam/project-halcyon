"""Drive N LDPlayer emulators into the Halcyon solo-bots queue.

The 07:1x live runs proved the blind tap chain works but popups eat taps
(Google Play Games sign-in sheet, Play Store hijacks by LDPlayer ads, app
restarts). This driver verifies the screen state via pixel samples before
each tap stage and dismisses known popups, so the queue is deterministic.

Screen states recognized (960x540):
  menu          — red PLAY button block at (795,470)
  playgames     — Google Play Games white sheet (bright pixels around (480,320))
  playstore     — Google Play Store foreground (white top bar at (480,45))
  ingame/world  — neither of the above (draft/hud/world) — caller decides

Usage:
  python Tools/drive_queue.py --serials emulator-5554,emulator-5556 --to-lock
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
import time

from PIL import Image


def sh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True)


def screem(serial: str) -> Image.Image:
    out = sh(["adb", "-s", serial, "exec-out", "screencap", "-p"]).stdout
    return Image.open(io.BytesIO(out)).convert("RGB")


def px(img: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    return img.getpixel((x, y))


def classify(img: Image.Image) -> str:
    # (795,470) sits on the white PLAY glyph — sample the red block beside it
    r, g, b = px(img, 740, 455)
    if r > 90 and g < 70 and b < 80:
        return "menu"                       # red PLAY block
    r2, g2, b2 = px(img, 480, 45)
    if r2 > 230 and g2 > 230 and b2 > 230:
        return "playstore"                  # white store top bar
    r3, g3, b3 = px(img, 480, 320)
    if r3 > 225 and g3 > 225 and b3 > 225:
        return "playgames"                  # white sign-in sheet
    r4, g4, b4 = px(img, 480, 260)
    if 45 < r4 < 95 and 45 < g4 < 95 and 45 < b4 < 95:
        return "signin_fail"                # grey alert with teal OK
    return "ingame"


def tap(serial: str, x: int, y: int) -> None:
    sh(["adb", "-s", serial, "shell", "input", "tap", str(x), str(y)])


def foreground(serial: str) -> None:
    sh(["adb", "-s", serial, "shell", "am", "force-stop", "com.android.vending"])
    sh(["adb", "-s", serial, "shell", "input", "keyevent", "4"])
    time.sleep(1)
    sh(["adb", "-s", serial, "shell", "monkey", "-p", "com.superevilmegacorp.game",
        "-c", "android.intent.category.LAUNCHER", "1"],)
    time.sleep(6)


def to_menu(serial: str, timeout: float = 90.0) -> str:
    """Dismiss popups until the red PLAY button shows."""
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            img = screem(serial)
        except Exception:
            time.sleep(2)
            continue
        state = classify(img)
        if state != last:
            print(f"  [{serial}] state={state}", flush=True)
            last = state
        if state == "menu":
            return "menu"
        if state == "playgames":
            tap(serial, 208, 247)           # Cancel
        elif state == "signin_fail":
            tap(serial, 275, 298)           # OK
        elif state == "playstore":
            foreground(serial)
            continue                        # foreground already waits
        time.sleep(2)
    return f"timeout({last})"


QUEUE_TAPS = [
    (795, 470),    # PLAY opens the mode dialog
    (840, 195),    # 3V3 right-column sliver → pages/centers 3V3
    (712, 290),    # centered 3V3 → bot difficulty sheet
    (712, 185),    # VERY EASY
    (480, 490),    # hero select → (opens skin panel / lock area)
    (480, 78),     # Default Skin card
    (480, 490),    # LOCK IN
]


def dismiss_popups(serial: str, img: Image.Image) -> bool:
    """True when a popup was dismissed (caller re-classifies)."""
    state = classify(img)
    if state == "playgames":
        tap(serial, 208, 247)
        return True
    if state == "signin_fail":
        tap(serial, 275, 298)
        return True
    return False


def queue_to_lock(serial: str) -> None:
    for x, y in QUEUE_TAPS:
        # wait for the game to settle and dismiss any popup that raced in
        for _ in range(20):
            time.sleep(1.5)
            try:
                img = screem(serial)
            except Exception:
                continue
            if dismiss_popups(serial, img):
                continue
            if classify(img) != "menu" or (x, y) == QUEUE_TAPS[0][:2]:
                break
        tap(serial, x, y)
        print(f"  [{serial}] tapped ({x},{y})", flush=True)
    print(f"  [{serial}] queue taps done")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serials", default="emulator-5554,emulator-5556")
    ap.add_argument("--to-lock", action="store_true",
                    help="drive the full queue after reaching the menu")
    args = ap.parse_args()
    serials = [s.strip() for s in args.serials.split(",") if s.strip()]

    for s in serials:
        print(f"[{s}] foreground+menu: {to_menu(s)}")

    if args.to_lock:
        for s in serials:
            queue_to_lock(s)
        print("queue taps sent on all serials")
    return 0


if __name__ == "__main__":
    sys.exit(main())
