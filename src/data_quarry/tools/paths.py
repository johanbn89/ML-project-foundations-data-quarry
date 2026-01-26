from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterable, Sequence, TypeAlias

DatasetFiles: TypeAlias = dict[str, list[Path]]


class DataQuarryError(RuntimeError):
    """Raised when data-quarry operations fail."""


DVC_SUBDIR_NAME = "dvc"


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

    Example:
      files = get_file_paths(dataset="dataset2", ref="dataset2-v3", components=["raw", "target"])
    """
    repo_root = Path(_require_env("DATA_REPO_ROOT")).resolve()
    data_root = Path(_require_env("DATA_ROOT")).resolve()

    dataset_dir = data_root / dataset
    if not dataset_dir.is_dir():
        raise DataQuarryError(f"Dataset not found: {dataset_dir}")

    # Move repo to the requested ref
    _run(repo_root, ["git", "checkout", ref])

    # Pull only the dataset's DVC output folder
    dvc_dir = dataset_dir / DVC_SUBDIR_NAME
    dvc_rel = dvc_dir.relative_to(repo_root).as_posix()
    _run(repo_root, ["dvc", "pull", dvc_rel])
    print(f"Pulled DVC data for dataset '{dataset}' at ref '{ref}'.")
    print(f"Dataset DVC folder: {dvc_dir}")
    print(f"Dataset components: {components}")
    return _collect_files(dvc_dir, components)


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


def _collect_files(dvc_dataset_dir: Path, components: Sequence[str]) -> DatasetFiles:
    """
    Collect files for named dataset components inside the dataset DVC folder.
    """
    result: DatasetFiles = {}

    if not components:
        raise DataQuarryError("components must be non-empty (e.g. ['raw', 'target']).")

    for component in components:
        component_dir = dvc_dataset_dir / component
        if not component_dir.is_dir():
            raise DataQuarryError(f"Dataset component not found: {component_dir}")

        result[component] = sorted(p for p in component_dir.rglob("*") if p.is_file())

    return result
