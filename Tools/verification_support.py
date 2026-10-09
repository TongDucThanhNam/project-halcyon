"""Shared output and owned-input boundaries; no game execution or downloads."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
RUNTIME_SWITCHES = (
    "HALCYON_NATIVE_STEERING_LIBRARY", "HALCYON_OWNER_WALK_ANCHORS",
    "HALCYON_PUBLISH_PURSUIT_INTENT", "HALCYON_NATIVE_SKYE_CONTROL",
    "HALCYON_PUBLISH_SKYE_SPEED", "HALCYON_TRACE_MOVEMENT", "HALCYON_SAME_HERO",
)


class OutputPathError(ValueError):
    """An evidence destination would overwrite data or cross its boundary."""


def reject_link_traversal(path: Path) -> None:
    for parent in (path, *path.parents):
        if parent.exists() or parent.is_symlink():
            attributes = parent.lstat()
            if parent.is_symlink() or getattr(attributes, "st_file_attributes", 0) & REPARSE_ATTRIBUTE:
                raise OutputPathError(f"output path must not traverse a symlink or junction: {parent}")


def output_directory(explicit=None, *, root=ROOT, prefix="halcyon-check-",
                     allow_existing_empty=True) -> Path:
    """Create unique external evidence; never overwrite a prior nonempty run."""
    repository = Path(root).resolve()
    base = (Path(os.path.abspath(explicit)) if explicit
            else Path(tempfile.mkdtemp(prefix=prefix)))
    reject_link_traversal(base)
    resolved = base.resolve()
    if resolved == repository or repository in resolved.parents:
        raise OutputPathError(f"output directory must stay outside the repository: {resolved}")
    if resolved.exists():
        if not resolved.is_dir():
            raise OutputPathError(f"output path is not a directory: {resolved}")
        if any(resolved.iterdir()):
            raise OutputPathError(f"refusing to write into non-empty directory: {resolved}")
        if not allow_existing_empty:
            raise OutputPathError(f"output directory already exists: {resolved}")
    else:
        resolved.mkdir(parents=True)
    return resolved


def owned_input_environment() -> dict[str, str]:
    """Resolve original-checkout inputs BEFORE launching an external source pin."""
    from server import entity_spawn, paths

    result = {
        "HALCYON_LOCAL_ROOT": str(paths.local_root().resolve()),
        "HALCYON_STACK_DIR": str(paths.stack_dir().resolve()),
        "HALCYON_SPAWN_CORPUS": os.pathsep.join(
            str(Path(path).resolve()) for path in entity_spawn._source_paths()),
        "HALCYON_SKYE_VOLLEY_CORPUS": str(Path(
            os.environ.get("HALCYON_SKYE_VOLLEY_CORPUS") or paths.runtime_corpus_dir()).resolve()),
    }
    if os.environ.get("HALCYON_NATIVE_STEERING_LIBRARY"):
        result["HALCYON_NATIVE_STEERING_LIBRARY"] = str(
            Path(os.environ["HALCYON_NATIVE_STEERING_LIBRARY"]).resolve())
    return result


def runtime_switches() -> dict[str, str | None]:
    """Record explicit experimental configuration, never credentials or tokens."""
    return {name: os.environ.get(name) for name in RUNTIME_SWITCHES}

