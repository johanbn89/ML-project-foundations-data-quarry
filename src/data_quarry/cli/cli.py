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

app = typer.Typer(add_completion=False, no_args_is_help=True)

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


def _config_filepath() -> Path:
    """
    Per-user, per-machine config path.

    We store machine-specific filesystem locations outside the repo because they are
    not portable across machines/environments. Docker/CI should set env vars explicitly.

    Eg. On Windows this resolves to:
      C:\\Users\\<user>\\AppData\\Roaming\\data-quarry\\config.toml

    Remark:
    In containerized environments (e.g. Docker), environment variables should be set explicitly.
    User-specific configuration directories are ephemeral in containers
    and do not persist across image rebuilds or container restarts unless explicitly mounted.
    Therefore, the recommended approach is to define the paths deterministically at build
    or runtime e.g.:
    ENV DATA_REPO_ROOT=/opt/data-repo
    ENV DATA_ROOT=/opt/data-repo/data
    """
    return Path(user_config_dir(CONFIG_APP_NAME)) / CONFIG_FILE_NAME


def _write_config(cfg: DQConfig) -> Path:
    path = _config_filepath()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tomli_w.dumps(asdict(cfg)).encode("utf-8"))
    return path


def _repo_root_from_cwd() -> Path:
    """Require running from repo root (where `.dvc/` exists)."""
    repo_root = Path.cwd().resolve()
    if not (repo_root / ".dvc").is_dir():
        raise typer.BadParameter(
            "Expected to be run from the repo root (where `.dvc/` exists). "
            "Please `cd` to the repository root and rerun."
        )
    return repo_root


def _env_map(cfg: DQConfig) -> dict[str, str]:
    # Keep explicit mapping: env vars are an external interface, not 1:1 with config fields.
    return {
        ENV_REPO_ROOT: cfg.repo_root,
        ENV_DATA_ROOT: cfg.data_root,
    }


def _persist_env_windows(envs: dict[str, str]) -> None:
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


@app.command()
def setup(
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
    repo_root = repo.resolve() if repo else _repo_root_from_cwd()

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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
