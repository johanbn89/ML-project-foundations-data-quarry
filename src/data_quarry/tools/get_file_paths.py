"""
Want a function that
in its own subprocess(so that the cwd change does not affect the main process).
Input:
    - commit-or-tag
    - data-set-name (to find the data repo path)
Actions:
    - cd env(DATA_REPO_ROOT)
    - git checkout commit-or-tag
    - dvc pull
    - derive paths from data-set-name and env(DATA_ROOT)
Output:
    - list of file paths (str) to the data files for the given data-set-name
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterable, Sequence, TypeAlias

DatasetFiles: TypeAlias = dict[str, list[Path]]


class DataQuarryError(RuntimeError):
    """Raised when data-quarry operations fail."""


def get_file_paths(
    *,
    ref: str,
    dataset: str,
    components: Sequence[str],
) -> DatasetFiles:
    """
    Return file paths for a dataset at a given git ref.

    This function executes repository operations (git checkout, dvc pull) via subprocess calls
    so the caller's working directory is unaffected. Note that the repo working tree itself
    *will* change to the requested ref.

    Requirements:
    - DATA_REPO_ROOT must be set
    - DATA_ROOT must be set
    """

    repo_root_str = _require_env("DATA_REPO_ROOT")
    data_root_str = _require_env("DATA_ROOT")

    repo_root = Path(repo_root_str).resolve()
    data_root = Path(data_root_str).resolve()

    dataset_dir = data_root / dataset
    if not dataset_dir.is_dir():
        raise DataQuarryError(f"Dataset not found: {dataset_dir}")

    _run(repo_root, ["git", "checkout", ref])
    _run(repo_root, ["dvc", "pull"])

    return _collect_files(dataset_dir, components)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise DataQuarryError(f"Required environment variable not set: {name}")
    return value


def _run(cwd: Path, cmd: Iterable[str]) -> None:
    proc = subprocess.run(
        list(cmd),
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        raise DataQuarryError(f"Command failed: {' '.join(cmd)}\n{msg}")


def _collect_files(dataset_dir: Path, components: Sequence[str]) -> DatasetFiles:
    """
    Collect files for named dataset components.

    Example structure:
      dataset/
        raw/
        target/
        metadata/
    Example call:
      _collect_files(dataset_dir, ['raw', 'target'])
    """
    result: DatasetFiles = {}

    if not components:
        raise DataQuarryError("components must be non-empty (e.g. ['raw', 'target']).")

    for component in components:
        component_dir = dataset_dir / component
        if not component_dir.is_dir():
            raise DataQuarryError(f"Dataset component not found: {component_dir}")

        result[component] = sorted(p for p in component_dir.rglob("*") if p.is_file())

    return result
