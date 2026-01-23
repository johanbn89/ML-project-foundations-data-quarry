from __future__ import annotations

import typer

from data_quarry.cli.commands.setup_app import setup_app

app = typer.Typer(add_completion=False, no_args_is_help=True)

# Mount subcommands
app.add_typer(setup_app, name="setup")

# Later:
# from data_quarry.cli.commands.set_dvc_remote import dvc_app
# app.add_typer(dvc_app, name="set-dvc-remote")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
