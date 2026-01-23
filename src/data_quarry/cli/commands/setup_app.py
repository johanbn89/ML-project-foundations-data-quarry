# This may feel a bit overkill at first glance.
# We currently derive only two paths from the repo root, and these could
# technically be resolved at runtime when needed.
#
# However, if we want to change the CWD to this repository, we must already
# know where it is located. Centralizing this logic also makes it trivial
# to extend the setup with additional configuration options later
# (e.g. user-defined parameters).
#
# NOTE:
# We intentionally persist both environment variables and a config file here
# as a practice exercise. Environment variables represent a common integration
# surface for training code, shells, and Docker/CI, while the config file
# demonstrates how structured, extensible configuration could be handled
# as the system grows.
#
# In a production setup, one mechanism should be preferred to avoid
# duplication and ensure a single source of truth.
from __future__ import annotations

import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import tomli_w
import typer
from platformdirs import user_config_dir

setup_app = typer.Typer(add_completion=False)

CONFIG_APP_NAME = "data-quarry"
CONFIG_FILE_NAME = "config.toml"

ENV_REPO_ROOT = "DATA_REPO_ROOT"
ENV_DATA_ROOT = "DATA_ROOT"


@dataclass(frozen=True)
class DQConfig:
    repo_root: str
    data_root: str

    @staticmethod
    def from_repo_root(repo_root: Path) -> "DQConfig":
        repo_root = repo_root.resolve()
        data_root = (repo_root / "data").resolve()
        return DQConfig(repo_root=str(repo_root), data_root=str(data_root))


def _config_filepath() -> Path:
    return Path(user_config_dir(CONFIG_APP_NAME)) / CONFIG_FILE_NAME


def _write_config(cfg: DQConfig) -> Path:
    path = _config_filepath()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tomli_w.dumps(asdict(cfg)).encode("utf-8"))
    return path


def _repo_root_from_cwd() -> Path:
    repo_root = Path.cwd().resolve()
    if not (repo_root / ".dvc").is_dir():
        raise typer.BadParameter(
            "Expected to be run from the repo root (where `.dvc/` exists). "
            "Please `cd` to the repository root and rerun."
        )
    return repo_root


def _env_map(cfg: DQConfig) -> dict[str, str]:
    return {
        ENV_REPO_ROOT: cfg.repo_root,
        ENV_DATA_ROOT: cfg.data_root,
    }


def _persist_env_windows(envs: dict[str, str]) -> None:
    if sys.platform != "win32":
        raise typer.BadParameter("Windows only for now (persist uses setx).")

    for k, v in envs.items():
        proc = subprocess.run(["setx", k, v], capture_output=True, text=True)
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip()
            raise typer.BadParameter(f"Failed to persist {k} via setx. {msg}".strip())


@setup_app.callback(invoke_without_command=True)
def setup() -> None:
    """
    Register this data repo checkout on the current machine (Windows only).

    Must be run from the repository root (where `.dvc/` exists).
    """
    repo_root = _repo_root_from_cwd()

    cfg = DQConfig.from_repo_root(repo_root)
    cfg_path = _write_config(cfg)

    envs = _env_map(cfg)
    _persist_env_windows(envs)

    typer.echo(f"Config written: {cfg_path}")
    typer.echo(f"Repo root:      {cfg.repo_root}")
    typer.echo(f"Data root:      {cfg.data_root}")
    typer.echo("")
    typer.echo("Environment variables persisted for USER:")
    for k in envs:
        typer.echo(f"  {k}")
    typer.echo("")
    typer.echo("NOTE: Restart your terminal (CMD / PowerShell) for changes to take effect.")
