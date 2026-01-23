from __future__ import annotations

import typer

from data_quarry.cli.commands import setup_app
from data_quarry.cli.commands.set_dvc_remote import dvc_app

app = typer.Typer(add_completion=False, no_args_is_help=True)

# Mount subcommands
app.add_typer(setup_app, name="setup")
app.add_typer(dvc_app, name="set-dvc-remote")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
