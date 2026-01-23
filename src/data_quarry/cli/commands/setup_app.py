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
from typing import Optional

import tomli_w
import typer
from platformdirs import user_config_dir

setup_app = typer.Typer(add_completion=False, no_args_is_help=True)

CONFIG_APP_NAME = "data-quarry"
CONFIG_FILE_NAME = "config.toml"

# Environment variable names (external contract)
ENV_REPO_ROOT = "DATA_REPO_ROOT"
ENV_DATA_ROOT = "DATA_ROOT"


@dataclass(frozen=True)
class DQConfig:
    """Machine-local configuration for the data repo checkout."""

    repo_root: str
    data_root: str

    @staticmethod
    def from_repo_root(repo_root: Path) -> "DQConfig":
        repo_root = repo_root.resolve()
        data_root = (repo_root / "data").resolve()
        return DQConfig(repo_root=str(repo_root), data_root=str(data_root))


def config_filepath() -> Path:
    """
    Per-user, per-machine config path.

    We store machine-specific filesystem locations outside the repo because they are
    not portable across machines/environments. Docker/CI should set env vars explicitly.
    """
    return Path(user_config_dir(CONFIG_APP_NAME)) / CONFIG_FILE_NAME


def write_config(cfg: DQConfig) -> Path:
    path = config_filepath()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tomli_w.dumps(asdict(cfg)).encode("utf-8"))
    return path


def require_repo_root_from_cwd() -> Path:
    """Require running from repo root (where `.dvc/` exists)."""
    repo_root = Path.cwd().resolve()
    if not (repo_root / ".dvc").is_dir():
        raise typer.BadParameter(
            "Expected to be run from the repo root (where `.dvc/` exists). "
            "Please `cd` to the repository root and rerun."
        )
    return repo_root


def env_map(cfg: DQConfig) -> dict[str, str]:
    # Explicit mapping: env vars are an external interface, not 1:1 with config fields.
    return {
        ENV_REPO_ROOT: cfg.repo_root,
        ENV_DATA_ROOT: cfg.data_root,
    }


def persist_env_windows(envs: dict[str, str]) -> None:
    """
    Persist env vars for the current USER via `setx` (Windows only).
    Note: this affects *new* shells; it cannot modify already-running terminals.
    """
    if sys.platform != "win32":
        raise typer.BadParameter("Windows only for now (persist uses setx).")

    for k, v in envs.items():
        proc = subprocess.run(["setx", k, v], capture_output=True, text=True)
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip()
            raise typer.BadParameter(f"Failed to persist {k} via setx. {msg}".strip())


def format_success_message(cfg_path: Path, cfg: DQConfig, envs: dict[str, str]) -> str:
    lines: list[str] = []
    lines.append(f"Config written: {cfg_path}")
    lines.append(f"Repo root:      {cfg.repo_root}")
    lines.append(f"Data root:      {cfg.data_root}")
    lines.append("")
    lines.append("Environment variables persisted for USER:")
    for k in envs:
        lines.append(f"  {k}")
    lines.append("")
    lines.append("NOTE: Restart your terminal (CMD / PowerShell) for changes to take effect.")
    return "\n".join(lines)


@setup_app.command("register")
def register(
    repo: Optional[Path] = typer.Option(
        None,
        "--repo",
        "-r",
        help="Path to the data repo root. If omitted, current directory must contain `.dvc/`.",
    ),
) -> None:
    """
    Register this data repo checkout on the current machine (Windows only).

    - Writes machine-local config to the OS user config directory
    - Persists DATA_REPO_ROOT and DATA_ROOT for the user via `setx`
    """
    repo_root = repo.resolve() if repo else require_repo_root_from_cwd()

    cfg = DQConfig.from_repo_root(repo_root)
    cfg_path = write_config(cfg)

    envs = env_map(cfg)
    persist_env_windows(envs)

    typer.echo(format_success_message(cfg_path, cfg, envs))
