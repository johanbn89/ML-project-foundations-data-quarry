# data_quarry/cli.py
from __future__ import annotations

import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import typer
from platformdirs import user_config_dir
import tomli_w

# Delete before commit
# This is the entrypoint for the app defined in pyproject.toml
# data-repo-setup = "data_repo_setup.cli:app"
app = typer.Typer(add_completion=False, no_args_is_help=True)

CONFIG_APP_NAME = "data-quarry" 
CONFIG_FILE_NAME = "config.toml"

# Environment variable names
ENV_REPO_ROOT = "DATA_REPO_ROOT"
ENV_DATA_ROOT = "DATA_ROOT"

# frozen to make it immutable
@dataclass(frozen=True) 
class DQConfig:
    repo_root: str
    data_root: str

    @staticmethod
    def from_repo_root(repo_root: Path) -> "DQConfig":
        repo_root = repo_root.resolve()
        data_root = (repo_root / "data").resolve()
        
        # Delete before commit
        # This is possible due to, 
        # from __future__ import annotations
        return DQConfig(repo_root=str(repo_root), data_root=str(data_root))


def _config_filepath() -> Path:
    """
    Return the per-user, per-machine config path for data-quarry.
     
    Eg. On Windows this resolves to:
      C:\\Users\\<user>\\AppData\\Roaming\\data-quarry\\config.toml

    Why this lives in the OS user config directory (and NOT in the repo):
    - The values stored here (e.g. repo_root, data_root) are machine-specific
      filesystem locations and therefore not portable across machines.
    - The same data repo may exist at different paths on different systems
      (local dev, CI, containers, HPC, etc.).
    - Storing this in the repo would either require committing machine-local
      paths or relying on .gitignore, both of which are error-prone.
    - Using the OS-standard user config directory follows established
      conventions used by tools like git, dvc, kubectl, and pip.

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

    # Delete before commit
    # cfg(obj) -> asdict(cfg) -> dict -> tomli_w.dumps -> parse to toml and write to file
    path.write_bytes(tomli_w.dumps(asdict(cfg)).encode("utf-8"))
    return path


def _repo_root_from_cwd() -> Path:
    """
    Enforce to be run from the repo root (where .dvc/ exists).
    Raises typer.BadParameter if not found.
    """
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


def _persist_env(envs: dict[str, str]) -> None:
    """
    TODO:   This should also handle linux / macOS 
            by appending to ~/.bashrc or ~/.zshrc.

    Persist env vars for the current USER via setx.
    This affects new terminals; it cannot modify already-running shells.
    """
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
        help="Path to the data repo root. If omitted, inferred from current directory (finds .dvc/)",
    )
) -> None:
    if sys.platform != "win32":
        raise typer.BadParameter("Windows only for now (uses setx).")
    
    # Delete before commit
    # repo_root given from CLI arg or inferred from CWD
    repo_root = repo.resolve() if repo else _repo_root_from_cwd()

    # Delete before commit
    # Create DQConfig obj from repo_root and save it .toml file in user config dir
    cfg = DQConfig.from_repo_root(repo_root)
    cfg_path = _write_config(cfg)

    # Delete before commit
    # Some part of config becomes env vars
    envs = _env_map(cfg)
    _persist_env(envs)

    typer.echo(f"Config written: {cfg_path}")
    typer.echo(f"Repo root:      {cfg.repo_root}")
    typer.echo(f"Data root:      {cfg.data_root}")
    typer.echo("")
    typer.echo("Environment variables persisted for USER:")
    for k in envs.keys():
        typer.echo(f"  {k}")
    typer.echo("")
    typer.echo("NOTE: Restart your terminal (CMD / PowerShell) for changes to take effect.")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
