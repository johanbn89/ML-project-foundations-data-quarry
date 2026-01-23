import subprocess
from pathlib import Path

import typer

dvc_app = typer.Typer(add_completion=False)


def require_repo_root() -> None:
    if not (Path.cwd() / ".dvc").is_dir():
        raise typer.BadParameter("Expected to be run from the repo root (where `.dvc/` exists).")


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        raise typer.Exit(proc.returncode)


@dvc_app.callback(invoke_without_command=True)
def set_dvc_remote(
    name: str = typer.Option(..., "--name", "-n", help="DVC remote name"),
    url: str = typer.Option(..., "--url", "-u", help="DVC remote URL"),
    commit: bool = typer.Option(True, "--commit", help="Commit changes to git"),
) -> None:
    """
    Configure a DVC remote.
    """
    require_repo_root()

    typer.echo(f"Setting DVC remote '{name}' → {url}")

    run(["dvc", "remote", "add", "-d", name, url])
    run(["git", "add", ".dvc/config"])

    if commit:
        run(["git", "commit", "-m", f"Configure DVC remote '{name}'"])
        typer.echo("Changes committed.")
    else:
        typer.echo("Changes staged.")
