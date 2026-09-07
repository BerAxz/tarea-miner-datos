"""Interfaz de línea de comandos de Miner."""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

import typer
from typer.core import TyperGroup
from dotenv import load_dotenv

from .github_client import GitHubRepositoryClient
from .service import Miner


class LegacyGroup(TyperGroup):
    """Keep `miner input.csv` working alongside the new subcommands."""

    def parse_args(self, ctx, args):
        if args and args[0] not in self.commands and args[0] not in {"--help", "-h"}:
            args = ["detect", *args]
        return super().parse_args(ctx, args)


app = typer.Typer(
    cls=LegacyGroup,
    add_completion=False,
    no_args_is_help=True,
    help="Identifica GH-AW, extrae tablas Parquet y publica el dataset.",
)


class DetectionAPI(str, Enum):
    graphql = "graphql"
    rest = "rest"


@app.command("detect")
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
    workers: int = typer.Option(4, min=1, max=8, help="Consultas concurrentes a GitHub."),
    api: DetectionAPI = typer.Option(DetectionAPI.graphql, help="GraphQL por lotes o REST por repositorio."),
    checkpoint: Path = typer.Option(Path(".miner-cache/detection.sqlite"), help="Checkpoint reanudable de detección GraphQL."),
    batch_size: int = typer.Option(100, min=1, max=100, help="Repositorios por consulta GraphQL."),
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
        if api == DetectionAPI.graphql:
            from .batch_detection import GraphQLDetector, detect_large_csv

            detector = GraphQLDetector(token, client, workers=workers)
            try:
                summary = detect_large_csv(input_csv, output, detector, checkpoint, workers, batch_size,
                                           progress=lambda done, matched: typer.echo(f"Revisados: {done}; GH-AW: {matched}"))
            finally:
                detector.close()
        else:
            summary = Miner(client).run(input_csv, output, workers=workers)
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
    if summary.unavailable_repositories:
        typer.echo(f"Repositorios inaccesibles: {summary.unavailable_repositories}; revisar el reporte JSON.")
    typer.echo(f"Archivo generado: {output}")


@app.command()
def extract(
    input_csv: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output: Path = typer.Option(Path("data/dataset"), "--output", "-o", help="Directorio nuevo para el dataset."),
    workers: int = typer.Option(8, min=1, max=32, help="Repositorios en paralelo."),
    cache_dir: Path = typer.Option(Path(".miner-cache"), help="Caché persistente de blobs SHA."),
) -> None:
    """Extrae Markdown/YAML de los repositorios identificados en la Tarea 2."""
    from .dataset import DatasetMiner

    load_dotenv()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        typer.echo("Error: configura GITHUB_TOKEN en .env o en el entorno.", err=True)
        raise typer.Exit(1)
    client = GitHubRepositoryClient(token)
    try:
        summary = DatasetMiner(client).extract(input_csv, output, workers, cache_dir)
    except Exception as exc:
        typer.echo(f"Error al extraer: {exc}", err=True)
        raise typer.Exit(1) from exc
    finally:
        client.close()
    typer.echo(f"Repositorios: {summary.repositories}; Markdown: {summary.workflows}")
    typer.echo(f"Descargas: {summary.downloads}; caché: {summary.cache_hits}; errores: {summary.errors}")
    typer.echo(f"Tiempo: {summary.elapsed_seconds:.3f} s; dataset: {output}")
    if summary.errors:
        typer.echo("Dataset parcial: revisa status/error y run.json.", err=True)
        raise typer.Exit(2)


@app.command()
def publish(
    dataset_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    repo_id: str = typer.Option(..., "--repo-id", help="Destino usuario/dataset de Hugging Face."),
    private: bool = typer.Option(False, help="Crear un dataset privado."),
) -> None:
    """Publica las tablas Parquet y su dataset card en Hugging Face."""
    from .publication import publish_dataset

    load_dotenv()
    try:
        url = publish_dataset(dataset_dir, repo_id, private=private)
    except Exception as exc:
        typer.echo(f"Error al publicar: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Dataset publicado: {url}")
