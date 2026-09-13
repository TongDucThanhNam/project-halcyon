"""Initialize private configuration or check owned inputs without launching a game.

Run from any working directory. --init creates missing local config/certificates;
the default/--check reads prerequisites and production loaders. --serial adds
read-only ADB package/root/OBB checks. No downloads or guest routing mutations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import paths


def initialize() -> None:
    # Initialization always targets this checkout's Local unless explicitly
    # configured; do not accidentally rewrite an older live TEMP environment.
    os.environ.setdefault("HALCYON_LOCAL_ROOT", str(paths.local_root()))
    directory = paths.stack_dir()
    directory.mkdir(parents=True, exist_ok=True)
    from server.platform import local_stack, mkcert

    cert = directory / "platform_cert.pem"
    key = directory / "platform_key.pem"
    if cert.exists() != key.exists():
        raise ValueError(f"Incomplete certificate/key pair at {directory}; restore the matching pair")
    if not cert.exists():
        mkcert.main()
    else:
        print(f"KEEP certificate/key: {directory}")

    target = directory / "answers.json"
    if not target.exists():
        text = (ROOT / "Config/answers.example.json").read_text(encoding="utf-8")
        token = local_stack._mint_token(local_stack.DEFAULT_PLAYER_UUID)
        text = text.replace("__HALCYON_LOCAL_SESSION_TOKEN__", token)
        json.loads(text)
        with target.open("x", encoding="utf-8") as output:
            output.write(text)
        print(f"CREATED config: {target}")
    else:
        print(f"KEEP config: {target}")


def check(profile: str, serial: str | None) -> int:
    failures = []

    def verify(label, operation):
        try:
            detail = operation()
            print(f"OK {label}: {detail}")
        except Exception as exc:
            failures.append(label)
            print(f"MISSING/INVALID {label}: {exc}")

    def pinned_file(entry):
        path = paths.local_root() / entry["path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != entry["sha256"] or path.stat().st_size != entry["bytes"]:
            raise ValueError(f"{path}: bytes/digest differ from measured input")
        return str(path)

    print(f"Project: {ROOT}\nLocal inputs: {paths.local_root()}\nRuntime: {paths.stack_dir()}")
    manifest = json.loads((ROOT / "Config/local-inputs.json").read_text(encoding="utf-8"))
    # APK/OBB identity is checked here. Simulation paths use production loaders
    # below so explicit corpus/navmesh overrides continue to work.
    if profile == "client":
        for entry in manifest["files"]:
            if entry["role"] == "android-client":
                verify(entry["path"], lambda entry=entry: pinned_file(entry))

    def simulation():
        from server import entity_spawn, navigation, skye_wire
        navigation.load_halcyon_navmesh()
        spawn = entity_spawn.load_spawn_catalog()
        actors = entity_spawn.load_native_actor_catalog()
        volley = skye_wire.native_volley_templates()
        return (f"navmesh loaded; neutral archetypes={sorted(spawn.templates)}; "
                f"actor archetypes={sorted(actors.templates)}; volley={sorted(volley)}")

    verify("production simulation inputs", simulation)
    if profile == "client":
        def tape():
            from server import world_tape
            selected = paths.stack_dir() / "world_tape.bin"
            frames = world_tape.load_tape(str(selected), skip_until_op=1087)
            if not frames:
                raise ValueError(f"missing or empty world tape: {selected}")
            digest = hashlib.sha256()
            for when, body in frames:
                digest.update(world_tape.RECORD_HEAD.pack(when, len(body)))
                digest.update(body)
            if digest.hexdigest() != world_tape._TRUNCATED_BOOTSTRAP_SHA256:
                raise ValueError("world tape does not match the measured bootstrap loader pin")
            return f"{len(frames)} records, production digest {digest.hexdigest()}"

        def platform():
            directory = paths.stack_dir()
            config = json.loads((directory / "answers.json").read_text(encoding="utf-8"))
            for method in ("getPlayerForGuestAccount", "startSessionForPlayer"):
                value = config[method]["returnValue"]
                if not value.get("sessionToken") or "__HALCYON_" in value["sessionToken"]:
                    raise ValueError(f"uninitialized {method} session token")
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(directory / "platform_cert.pem", directory / "platform_key.pem")
            return "answers parse and certificate/key match"

        verify("world tape", tape)
        verify("platform configuration", platform)
        def adb_path():
            executable = shutil.which("adb")
            if not executable:
                raise FileNotFoundError("adb not on PATH")
            return executable
        verify("ADB executable", adb_path)

    if serial:
        def guest():
            from server.platform import guest_setup
            root = guest_setup.su(serial, "id")
            if root.returncode or not re.search(r"\buid=0\b", root.stdout):
                raise ValueError("LDPlayer root is unavailable")
            uid = guest_setup.package_uid(serial)
            package = subprocess.run(["adb", "-s", serial, "shell", "dumpsys", "package",
                                      "com.superevilmegacorp.game"], capture_output=True, text=True,
                                     timeout=20, check=True)
            if not re.search(r"versionCode=147219\b", package.stdout) or "versionName=4.13.4" not in package.stdout:
                raise ValueError("installed package is not CE 4.13.4/build 147219")
            obb = subprocess.run(["adb", "-s", serial, "shell", "stat", "-c", "%s",
                                  "/sdcard/Android/obb/com.superevilmegacorp.game/main.147219.com.superevilmegacorp.game.obb"],
                                 capture_output=True, text=True, timeout=20, check=True)
            if obb.stdout.strip() != "1394159471":
                raise ValueError("installed OBB size differs from the measured input")
            return f"{serial}: root, package 147219, UID {uid}, OBB size verified (routing not checked)"
        verify("emulator", guest)

    print(f"RESULT: {'FAIL' if failures else 'PASS'} ({len(failures)} prerequisite failures)")
    return 1 if failures else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init", action="store_true", help="create missing private config and certificates; preserve existing files")
    parser.add_argument("--check", action="store_true", help="check inputs (also the default when --init is absent)")
    parser.add_argument("--profile", choices=("headless", "client"), default="client")
    parser.add_argument("--serial", help="optionally inspect this already running emulator via ADB")
    args = parser.parse_args(argv)
    try:
        if args.init:
            initialize()
        if args.check or not args.init:
            return check(args.profile, args.serial)
    except Exception as exc:
        print(f"SETUP FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
