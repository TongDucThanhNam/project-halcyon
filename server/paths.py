"""Locate private, Git-ignored data independently of the checkout location.

Default layout: ``<project>/Local/vainglory`` for original clients,
``<project>/Local/research/<name>`` for owned research corpora, and
``<project>/Local/runtime/halcyon_stack`` for runtime configuration/data.
Existing legacy locations remain usable when no corresponding local directory
exists. Set ``HALCYON_LOCAL_ROOT`` to choose a different private data root;
an explicit root never silently falls back to a legacy directory. Set
``HALCYON_STACK_DIR`` to override only the runtime directory.

All public helpers return absolute pathlib Paths without creating directories.
Relative environment overrides are resolved against the project, not the
process working directory. QA output should keep its existing external paths.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LEGACY_VAINGLORY_ROOT = Path("D:/Downloads/vg")


def project_root() -> Path:
    """Return the checkout containing this module, independently of cwd."""
    return _PROJECT_ROOT


def _absolute(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_root() / path


def local_root() -> Path:
    """Return HALCYON_LOCAL_ROOT, or the checkout's Git-ignored Local folder."""
    return _absolute(os.environ.get("HALCYON_LOCAL_ROOT") or "Local")


def _select(local: Path, legacy: Path) -> Path:
    if os.environ.get("HALCYON_LOCAL_ROOT") or local.is_dir():
        return local
    if legacy.is_dir():
        return legacy.absolute()
    return local


def _legacy_temp() -> Path:
    return Path(os.environ.get("TEMP") or tempfile.gettempdir())


def pc_data_dir() -> Path:
    """Return the owned PC 4.13 store Data directory (not an Android OBB)."""
    relative = Path("pc/Vainglory 4.13/Vainglory/Data")
    return _select(local_root() / "vainglory" / relative,
                   _LEGACY_VAINGLORY_ROOT / relative)


def research_dir(name: str) -> Path:
    """Return one research corpus directory, e.g. vg_max or vg_phaseB.

    Append files/subdirectories to the returned Path; name must be a single
    directory component so it cannot escape the selected research root.
    """
    if not name or name in (".", "..") or any(c in name for c in "/\\:"):
        raise ValueError("research directory name must be one path component")
    return _select(local_root() / "research" / name, _legacy_temp() / name)


def runtime_corpus_dir() -> Path:
    """Return runtime templates, separately from the original Phase B archive.

    Reconstructed minimal records belong in ``Local/research/runtime-corpus``;
    they are not a complete independent reference capture. Prefer that directory
    when present or when HALCYON_LOCAL_ROOT explicitly selects its parent.
    Otherwise retain the original ``vg_phaseB/vgr_live`` source for existing
    installations. Corpus validation tests should use research_dir directly.
    """
    local = local_root() / "research/runtime-corpus"
    if os.environ.get("HALCYON_LOCAL_ROOT") or local.is_dir():
        return local
    return research_dir("vg_phaseB") / "vgr_live"


def stack_dir() -> Path:
    """Return HALCYON_STACK_DIR or the selected halcyon_stack runtime folder."""
    override = os.environ.get("HALCYON_STACK_DIR")
    if override:
        return _absolute(override)
    return _select(local_root() / "runtime" / "halcyon_stack",
                   _legacy_temp() / "halcyon_stack")
