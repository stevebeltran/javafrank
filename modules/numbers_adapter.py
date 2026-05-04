"""
Helpers for reading Apple Numbers .numbers files.

The app keeps its main Streamlit environment stable and uses an isolated
temporary install of numbers-parser only when a .numbers file is uploaded.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import subprocess
import textwrap
import time
import shutil
from pathlib import Path

import pandas as pd


_NUMBERS_PARSER_VERSION = "4.18.3"
_HELPER_DIR = Path(tempfile.gettempdir()) / "frankenstein_numbers_parser"


def _ensure_numbers_parser_helper() -> Path:
    """
    Install numbers-parser into an isolated temp target if needed.

    The helper lives outside the app's normal site-packages so the main
    Streamlit environment does not inherit the dependency's protobuf stack.
    """
    marker = _HELPER_DIR / f"numbers-parser-{_NUMBERS_PARSER_VERSION}.ok"
    if marker.exists():
        return _HELPER_DIR

    _HELPER_DIR.mkdir(parents=True, exist_ok=True)
    lock_dir = _HELPER_DIR / ".install.lock"
    got_lock = False
    try:
        try:
            lock_dir.mkdir()
            got_lock = True
        except FileExistsError:
            for _ in range(120):
                if marker.exists():
                    return _HELPER_DIR
                time.sleep(0.25)
            if marker.exists():
                return _HELPER_DIR
            lock_dir.mkdir(exist_ok=True)
            got_lock = True

        if marker.exists():
            return _HELPER_DIR

        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--ignore-installed",
            "--target",
            str(_HELPER_DIR),
            f"numbers-parser=={_NUMBERS_PARSER_VERSION}",
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        marker.write_text("ok", encoding="utf-8")
        return _HELPER_DIR
    finally:
        if got_lock:
            shutil.rmtree(lock_dir, ignore_errors=True)


def _best_table_to_csv_script() -> str:
    return textwrap.dedent(
        """
        import csv
        import io
        import pathlib
        import sys

        helper_dir = pathlib.Path(sys.argv[2])
        numbers_path = pathlib.Path(sys.argv[1])
        sys.path.insert(0, str(helper_dir))

        import pandas as pd
        from numbers_parser import Document


        def table_score(table):
            header = [getattr(cell, "value", cell) for cell in next(table.iter_rows())]
            header_norm = [str(h).strip().lower() for h in header if h is not None]
            hints = ["latitude", "longitude", "lat", "lon", "priority", "location", "date", "time", "address"]
            score = sum(10 for h in header_norm if any(k == h or k in h for k in hints))
            score += sum(1 for h in header_norm if h and not str(h).startswith("column"))
            score += min(table.num_rows, 200)
            return score


        doc = Document(str(numbers_path))
        if not doc.sheets:
            raise SystemExit("No sheets found in Numbers document.")

        best_table = None
        best_score = -10**9
        for sheet in doc.sheets:
            for table in sheet.tables:
                try:
                    score = table_score(table)
                except Exception:
                    continue
                if score > best_score:
                    best_score = score
                    best_table = table

        if best_table is None:
            raise SystemExit("No readable table found in Numbers document.")

        rows = []
        for row in best_table.iter_rows():
            rows.append([getattr(cell, "value", cell) for cell in row])

        if not rows:
            raise SystemExit("Numbers table was empty.")

        df = pd.DataFrame(rows[1:], columns=rows[0])
        df.to_csv(sys.stdout, index=False, lineterminator="\\n")
        """
    ).strip()


def load_numbers_dataframe(raw_bytes: bytes, filename: str = "upload.numbers") -> pd.DataFrame:
    """
    Load a Numbers file into a DataFrame using an isolated helper process.

    Returns a DataFrame with header names from the Numbers table and the best
    table selected by a lightweight heuristic.
    """
    helper_dir = _ensure_numbers_parser_helper()

    with tempfile.TemporaryDirectory(prefix="frankenstein_numbers_") as tmpdir:
        numbers_path = Path(tmpdir) / Path(filename).name
        numbers_path.write_bytes(raw_bytes)
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                _best_table_to_csv_script(),
                str(numbers_path),
                str(helper_dir),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    csv_text = proc.stdout.strip()
    if not csv_text:
        return pd.DataFrame()
    return pd.read_csv(io.StringIO(csv_text), low_memory=False)
