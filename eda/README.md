# EDA de GitHub Agentic Workflow Histories

Este directorio contiene los notebooks de análisis exploratorio de datos (EDA):

1. `01_descripcion_y_calidad.ipynb`: origen, estructura, relaciones, calidad y tratamiento.
2. `02_exploracion_y_hallazgos.ipynb`: distribución de archivos, frontmatter, body, relaciones y hallazgos.

## Dataset

Se utiliza temporalmente [GHAW-H — GitHub Agentic Workflow Histories](https://huggingface.co/datasets/pavtch/GHAW-H), publicado bajo CC BY 4.0 para los metadatos de la release y sujeto además a las licencias de los repositorios de origen. La documentación de la fuente está disponible en el [repositorio acompañante](https://github.com/pavt/GHAW-H).

GHAW-H tiene cinco tablas Parquet relacionadas:

| Tabla | Unidad de fila | Clave principal | Relación principal |
| --- | --- | --- | --- |
| `repository` | Repositorio observado | `repository_id` | `source_markdown_file_snapshot.repository_id` |
| `source_markdown_file_history` | Historial de un archivo Markdown lógico | `source_markdown_file_history_id` | `source_markdown_file_version.source_markdown_file_history_id` |
| `source_markdown_file_snapshot` | Snapshot inmutable de un Markdown | `source_markdown_file_snapshot_id` | `source_markdown_file_version.source_markdown_file_snapshot_id` |
| `source_markdown_file_version` | Versión ordenada de un snapshot | `source_markdown_file_version_id` | `lock_file_snapshot.source_markdown_file_version_id` |
| `lock_file_snapshot` | Snapshot del `.lock.yml` asociado | `lock_file_snapshot_id` | Una fila por versión Markdown en esta release |

La fuente declara 262 repositorios, 604 historiales de archivos y 2.820 snapshots/versiones. En el EDA, un archivo Markdown lógico se identifica por la combinación `(repository_id, path)`; por eso no se confunde el número de archivos únicos con el número de snapshots históricos.

## Preparar los datos

Desde la raíz del repositorio, crear `eda/data/raw/` y descargar las cinco tablas:

```bash
mkdir -p eda/data/raw eda/data/processed
curl -L https://huggingface.co/datasets/pavtch/GHAW-H/resolve/main/data/repository.parquet -o eda/data/raw/repository.parquet
curl -L https://huggingface.co/datasets/pavtch/GHAW-H/resolve/main/data/source_markdown_file_history.parquet -o eda/data/raw/source_markdown_file_history.parquet
curl -L https://huggingface.co/datasets/pavtch/GHAW-H/resolve/main/data/source_markdown_file_snapshot.parquet -o eda/data/raw/source_markdown_file_snapshot.parquet
curl -L https://huggingface.co/datasets/pavtch/GHAW-H/resolve/main/data/source_markdown_file_version.parquet -o eda/data/raw/source_markdown_file_version.parquet
curl -L https://huggingface.co/datasets/pavtch/GHAW-H/resolve/main/data/lock_file_snapshot.parquet -o eda/data/raw/lock_file_snapshot.parquet
```

Los Parquet originales se conservan en `eda/data/raw/` y no se modifican. Por su tamaño y por las condiciones de distribución del contenido de repositorios externos, no se versionan en Git. El primer notebook genera las tablas derivadas reproducibles en `eda/data/processed/`.

## Instalar dependencias

El proyecto registra las dependencias en `pyproject.toml`. Con `uv`:

```bash
uv sync
```

Con un entorno virtual creado con `venv`:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m pip install jupyterlab ipykernel pandas pyarrow matplotlib seaborn
```

En Windows, activar el entorno con `.venv\Scripts\activate` antes de ejecutar los comandos equivalentes.

## Kernel y ejecución

Registrar el kernel del entorno virtual y abrir JupyterLab desde la raíz del repositorio:

```bash
uv run python -m ipykernel install --user --name miner-ghaw --display-name "Python (miner-ghaw)"
uv run jupyter lab
```

Si el entorno fue activado con `venv`, reemplazar `uv run python` por `python` y `uv run jupyter lab` por `jupyter lab`.

En JupyterLab, seleccionar el kernel **Python (miner-ghaw)** en ambos notebooks. Ejecutarlos en este orden:

1. `01_descripcion_y_calidad.ipynb`. Lee las tablas originales, reporta la calidad y guarda `markdown_analysis.parquet`, `frontmatter_fields.parquet` y `frontmatter_attribute_values.parquet` en `eda/data/processed/`.
2. `02_exploracion_y_hallazgos.ipynb`. Carga esas tablas desde disco y vuelve a cargar `repository.parquet` y las tablas relacionales necesarias; no depende de variables que hayan quedado en memoria del primer notebook.

Ambos notebooks también pueden ejecutarse sin abrir la interfaz:

```bash
uv run jupyter nbconvert --to notebook --execute --inplace eda/01_descripcion_y_calidad.ipynb
uv run jupyter nbconvert --to notebook --execute --inplace eda/02_exploracion_y_hallazgos.ipynb
```

La ruta de datos se detecta tanto si JupyterLab se inicia desde la raíz del repositorio como desde `eda/`. Las salidas de tablas y gráficos se conservan dentro de los notebooks ejecutados.

## Adaptación al dataset propio de Miner

GHAW-H se usa como dataset temporal para avanzar con la tarea y contiene historia explícita de archivos. Cuando esté disponible el dataset propio de la Tarea 3, se deben reemplazar los archivos de `eda/data/raw/` y adaptar la celda de carga, los nombres de claves y las relaciones al esquema propio (`repositories`, `workflows`, `bodies` y `frontmatter_nodes`). La lógica de calidad, las métricas del body y las preguntas exploratorias se conserva, ajustando las columnas disponibles.
