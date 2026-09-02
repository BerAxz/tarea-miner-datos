"""Interfaz de línea de comandos de Miner."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from dotenv import load_dotenv

from .github_client import GitHubRepositoryClient
from .service import Miner

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Identifica repositorios que utilizan GitHub Agentic Workflows.",
)


@app.command()
def main(
    input_csv: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="CSV con los repositorios candidatos.",
    ),
    output: Path = typer.Option(
        Path("repositorios_ghaw.csv"),
        "--output",
        "-o",
        help="CSV donde se guardarán solo los repositorios con GH-AW.",
    ),
) -> None:
    """Lee candidatos, consulta GitHub y genera el CSV filtrado."""

    load_dotenv()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        typer.echo(
            "Error: configura GITHUB_TOKEN en el archivo .env o en el entorno.",
            err=True,
        )
        raise typer.Exit(code=1)

    client = GitHubRepositoryClient(token)
    try:
        summary = Miner(client).run(input_csv, output)
    except Exception as exc:
        typer.echo(f"Error al ejecutar Miner: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        client.close()

    typer.echo(f"Filas procesadas: {summary.input_rows}")
    typer.echo(f"Repositorios consultados: {summary.repositories_consulted}")
    typer.echo(f"Repositorios con GH-AW: {summary.matched_rows}")
    if summary.invalid_rows:
        typer.echo(f"Filas ignoradas por referencia inválida: {summary.invalid_rows}")
    typer.echo(f"Archivo generado: {output}")
