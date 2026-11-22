"""Command line interface: `planos inspect` and `planos convert`."""

from __future__ import annotations

import typer

from planos import __version__

app = typer.Typer(
    name="planos",
    help="Convierte planos DXF de tipologías en modelos 3D (space.json + GLB).",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"planos {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Muestra la versión."
    ),
) -> None:
    """planos: pipeline DXF → space.json → GLB."""


if __name__ == "__main__":  # pragma: no cover
    app()
