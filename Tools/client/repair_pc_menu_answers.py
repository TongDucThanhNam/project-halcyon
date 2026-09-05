"""Repair the locally scripted PC 4.13 menu replies; no network access.

Run with --apply to update the external answers.json atomically, keeping a
backup. The optional diagnostic skin is synthetic, hidden and unobtainable;
it tests the client's nonempty catalogue requirement, not gameplay parity.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import tempfile


MANIFEST_METHODS = (
    "getSkinManifest", "getBuffManifest", "getSeasonRewardsManifest",
)


def diagnostic_skin_manifest() -> dict:
    return {
        "themes": [{"themeKey": "halcyon_probe", "heroKey": "Catherine"}],
        "skins": [{
            "skinKey": "halcyon_probe", "heroKey": "Catherine",
            "themeKey": "halcyon_probe", "visible": False, "obtainable": False,
        }],
    }


def repair_answers(answers: dict, *, diagnostic_skins: bool = False) -> dict:
    """Preserve unrelated replies, including session configuration and tokens."""
    if not isinstance(answers, dict):
        raise ValueError("answers.json must contain an object")
    result = copy.deepcopy(answers)
    for method in MANIFEST_METHODS:
        reply = result.get(method)
        if not isinstance(reply, dict) or reply.get("code") != 0:
            raise ValueError(f"{method} must be a scripted code:0 reply")
        value = reply.get("returnValue")
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise ValueError(f"{method}.returnValue must encode a JSON object")
        if method == "getSkinManifest":
            if diagnostic_skins:
                value = diagnostic_skin_manifest()
            elif not all(isinstance(value.get(key), list) and value[key]
                         for key in ("themes", "skins")):
                raise ValueError(
                    "getSkinManifest needs nonempty themes and skins arrays; "
                    "supply catalogue metadata or use --diagnostic-skins")
        reply["returnValue"] = json.dumps(value, separators=(",", ":"))

    friends = result.get("friendListAll")
    if not isinstance(friends, dict) or friends.get("code") != 0:
        raise ValueError("friendListAll must be a scripted code:0 reply")
    value = friends.get("returnValue")
    if not isinstance(value, dict):
        raise ValueError("friendListAll.returnValue must be an object")
    # Retain real lists, if supplied. A `friends` wrapper is not the PC schema.
    for key in ("pending", "confirmed"):
        value.setdefault(key, [])
        if not isinstance(value[key], list):
            raise ValueError(f"friendListAll.returnValue.{key} must be an array")
    value.setdefault("numOffline", 0)
    return result


def write_answers(path: Path, original: bytes, repaired: dict) -> Path:
    """Backup first; never expose half-written JSON to the running server."""
    if path.read_bytes() != original:
        raise ValueError("answers.json changed during repair; reread it before applying")
    backup_fd, backup_name = tempfile.mkstemp(
        prefix=path.name + ".before-menu-", suffix=".bak", dir=path.parent)
    with os.fdopen(backup_fd, "wb") as stream:
        stream.write(original)
    new_fd, new_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(new_fd, "w", encoding="utf-8") as stream:
            json.dump(repaired, stream, indent=1)
            stream.write("\n")
        os.replace(new_name, path)
    finally:
        Path(new_name).unlink(missing_ok=True)
    return Path(backup_name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("answers", type=Path)
    parser.add_argument("--diagnostic-skins", action="store_true",
                        help="replace skin metadata with one hidden synthetic entry")
    parser.add_argument("--apply", action="store_true",
                        help="write changes; otherwise report changed RPC names only")
    args = parser.parse_args()
    original = args.answers.read_bytes()
    current = json.loads(original)
    repaired = repair_answers(current, diagnostic_skins=args.diagnostic_skins)
    changed = [key for key in repaired if repaired[key] != current.get(key)]
    print("Changed RPCs:", ", ".join(changed) or "none")
    if args.apply and changed:
        print("Backup:", write_answers(args.answers, original, repaired))
    elif changed:
        print("Dry run; use --apply to write these changes.")


if __name__ == "__main__":
    main()
