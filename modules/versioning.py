"""
Build version management for BRINC app.
"""

import datetime
import subprocess
from pathlib import Path

try:
    import streamlit as st
except Exception:
    st = None

_MONSTER_NAMES = ["prom", "behe", "quasi", "drac"]
_REPO_ROOT = Path(__file__).resolve().parent.parent
_BUILD_META_PATH = _REPO_ROOT / ".build_meta"
_APP_PATH = _REPO_ROOT / "app.py"
_VERSION_ANCHOR_COMMIT = "6156fc0"


def _read_build_meta():
    """Read stored build timestamp and revision from .build_meta."""
    try:
        _raw_meta = _BUILD_META_PATH.read_text(encoding="utf-8").strip()
        if _raw_meta:
            _parts = _raw_meta.split("|", 1)
            if len(_parts) == 2:
                return float(_parts[0]), max(1, int(_parts[1]))
    except (ValueError, OSError):
        pass
    return 0.0, 1


def _write_build_meta(mtime, revision):
    """Persist the latest app.py timestamp and revision."""
    try:
        _BUILD_META_PATH.write_text(f"{float(mtime)}|{int(revision)}", encoding="utf-8")
    except OSError:
        pass


def _read_anchor_revision():
    """Read the revision stored when versioning was introduced."""
    try:
        _raw_meta = subprocess.check_output(
            ["git", "show", f"{_VERSION_ANCHOR_COMMIT}:.build_meta"],
            cwd=_REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
        _parts = _raw_meta.split("|", 1)
        if len(_parts) == 2:
            return max(1, int(_parts[1]))
    except Exception:
        pass
    return 1


def _git_revision():
    """Return a stable revision derived from git history when available."""
    try:
        _count = subprocess.check_output(
            ["git", "rev-list", "--count", f"{_VERSION_ANCHOR_COMMIT}..HEAD"],
            cwd=_REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
        if _count:
            return _read_anchor_revision() + max(0, int(_count))
    except Exception:
        pass
    return None


def _sync_build_meta():
    """
    Advance the revision when app.py has been saved since the last recorded build.

    This gives a monotonic revision number that increases by 1 whenever app.py
    changes, instead of only reflecting a read-only timestamp.
    """
    _app_mtime = float(_APP_PATH.stat().st_mtime)
    _stored_mtime, _stored_revision = _read_build_meta()
    _git_revision_value = _git_revision()

    if _git_revision_value is not None:
        _revision = max(_stored_revision, _git_revision_value)
        if abs(_app_mtime - _stored_mtime) > 1e-9 or _revision != _stored_revision:
            _write_build_meta(_app_mtime, _revision)
        return _app_mtime, _revision

    if _stored_mtime <= 0:
        _write_build_meta(_app_mtime, 1)
        return _app_mtime, 1

    # Preserve the highest revision even if app.py is restored with an older mtime.
    if _app_mtime < (_stored_mtime - 1e-9):
        _write_build_meta(_app_mtime, _stored_revision)
        return _app_mtime, _stored_revision

    if _app_mtime > (_stored_mtime + 1e-9):
        _stored_revision += 1
        _write_build_meta(_app_mtime, _stored_revision)
        return _app_mtime, _stored_revision

    return _stored_mtime, _stored_revision


def _count_app_lines():
    """Count app.py lines for build metadata logging."""
    try:
        return sum(1 for _ in _APP_PATH.open("r", encoding="utf-8"))
    except OSError:
        return 0


def _compute_build_info():
    """Compute the version string and related build metadata."""
    _mtime, _revision = _sync_build_meta()
    _dt = datetime.datetime.fromtimestamp(_mtime)
    _monster_idx = min(max(_revision - 1, 0) // 50, len(_MONSTER_NAMES) - 1)
    _monster_name = _MONSTER_NAMES[_monster_idx]
    return {
        "version": f"{_dt:%y}{chr(ord('A') + _dt.month - 1)}{_dt:%d}-{_monster_name}-{_dt:%H%M}.{_revision}",
        "revision": _revision,
        "build_datetime": _dt.strftime("%Y-%m-%d %H:%M:%S"),
        "build_timestamp": _mtime,
        "line_count": _count_app_lines(),
    }


_BUILD_INFO = _compute_build_info()
__version__ = _BUILD_INFO["version"]
__build_revision__ = _BUILD_INFO["revision"]
__build_datetime__ = _BUILD_INFO["build_datetime"]
__build_line_count__ = _BUILD_INFO["line_count"]


def get_build_info():
    """Return a copy of the current build metadata."""
    return dict(_BUILD_INFO)


def _render_version_badge(position="top-right"):
    """Render version badge in top-right or bottom-right corner."""
    if st is None:
        return
    _placement = "top: 12px; right: 160px;" if position == "top-right" else "bottom: 12px; right: 16px;"
    st.markdown(
        f"""
        <div style="position:fixed; {_placement} z-index:9999; font-family:'IBM Plex Mono',monospace; font-size:0.62rem; letter-spacing:0.08em; color:rgba(160,175,190,0.72); background:rgba(7,10,18,0.72); border:1px solid rgba(120,140,160,0.18); border-radius:999px; padding:4px 10px; backdrop-filter: blur(6px); pointer-events:none;">
            v {__version__}
        </div>
        """,
        unsafe_allow_html=True,
    )

