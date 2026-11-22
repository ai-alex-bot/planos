"""Command line interface: `planos inspect` and `planos convert`."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from planos import __version__
from planos.config import Config, load_config

app = typer.Typer(
    name="planos",
    help="Convierte planos DXF de tipologías en modelos 3D (space.json + GLB).",
    no_args_is_help=True,
    add_completion=False,
)

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8")
        except (ValueError, OSError):  # pragma: no cover
            pass

console = Console()
SEVERITY_STYLE = {"error": "bold red", "warning": "yellow", "info": "dim"}


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


def _load_cfg(config: Path | None) -> Config:
    try:
        return load_config(config)
    except ValidationError as exc:
        console.print(f"[bold red]Config inválida ({config}):[/]\n{exc}")
        raise typer.Exit(2) from exc
    except (OSError, ValueError) as exc:
        console.print(f"[bold red]No se pudo leer la config ({config}):[/] {exc}")
        raise typer.Exit(2) from exc


def _check_dxf(path: Path) -> None:
    if not path.exists():
        console.print(f"[bold red]No existe el archivo:[/] {path}")
        raise typer.Exit(2)
    if path.suffix.lower() == ".dwg":
        console.print("[bold red]Es un DWG.[/] Conviértelo a DXF con ODA File Converter (ver README).")
        raise typer.Exit(2)


@app.command()
def inspect(
    dxf: Path = typer.Argument(..., help="Archivo DXF."),
    config: Path | None = typer.Option(None, "--config", "-c", help="YAML de mapeo (opcional)."),
    max_texts: int = typer.Option(60, help="Máximo de textos a listar (0 = todos)."),
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON."),
) -> None:
    """Lista capas, bloques, textos, unidades y unidades de vivienda detectadas."""
    from planos.dxf.inspect import inspect_dxf

    _check_dxf(dxf)
    cfg = _load_cfg(config)
    rep = inspect_dxf(dxf, cfg)
    if as_json:
        typer.echo(rep.model_dump_json(indent=2))
        return

    console.rule(f"[bold]{dxf.name}")
    console.print(
        f"DXF {rep.dxf_version} · $INSUNITS={rep.insunits} · unidades: [bold]{rep.units}[/] "
        f"(origen: {rep.units_origin}, ×{rep.scale_to_m:g} → m)"
        + (f" · region: {list(rep.region)}" if rep.region else "")
    )

    t = Table(title="Capas", show_lines=False)
    t.add_column("Capa")
    t.add_column("Categoría")
    t.add_column("Origen", style="dim")
    t.add_column("Entidades", justify="right")
    t.add_column("Por tipo")
    for row in rep.layers:
        cat = row.category or "[yellow]—[/]"
        t.add_row(row.name, cat, row.source, str(row.total), ", ".join(f"{k} {v}" for k, v in row.counts.items()))
    console.print(t)
    if rep.empty_layers:
        console.print(f"[dim]Capas vacías: {', '.join(rep.empty_layers)}[/]")

    if rep.blocks:
        b = Table(title="Bloques usados (INSERT en el modelo)")
        b.add_column("Bloque")
        b.add_column("Usos", justify="right")
        b.add_column("Capas")
        b.add_column("Vano")
        b.add_column("Tamaño local (unid. dibujo)")
        b.add_column("Escalas X")
        for row in rep.blocks:
            size = f"{row.local_size[0]:g} × {row.local_size[1]:g}" if row.local_size else "—"
            b.add_row(row.name, str(row.count), ", ".join(row.layers), row.kind or "—", size,
                      ", ".join(f"{x:g}" for x in row.xscales[:6]))
        console.print(b)

    texts = rep.texts if max_texts == 0 else rep.texts[:max_texts]
    tx = Table(title=f"Textos ({len(rep.texts)})")
    tx.add_column("Texto")
    tx.add_column("Capa")
    tx.add_column("Categoría")
    tx.add_column("Posición (m)", justify="right")
    for row in texts:
        tx.add_row(row.text, row.layer, row.category or "—", f"{row.position_m[0]:.2f}, {row.position_m[1]:.2f}")
    console.print(tx)
    if len(texts) < len(rep.texts):
        console.print(f"[dim]… {len(rep.texts) - len(texts)} textos más (usa --max-texts 0)[/]")

    c = Table(title="Grupos de muros (unidades)")
    c.add_column("#", justify="right")
    c.add_column("bbox (unid. dibujo) → usar en 'region'")
    c.add_column("Tamaño (m)", justify="right")
    for i, row in enumerate(rep.clusters, 1):
        c.add_row(str(i), "[" + ", ".join(f"{v:.6g}" for v in row.bbox_drawing) + "]", f"{row.size_m:.2f}")
    console.print(c)

    if rep.issues:
        console.print("[bold]Avisos[/]")
        for issue in rep.issues:
            console.print(f"  [{SEVERITY_STYLE[issue.severity]}]{issue.severity.upper()}[/] {issue.code}: {issue.message}")


if __name__ == "__main__":  # pragma: no cover
    app()
