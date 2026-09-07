# Miner

La versión 0.2 agrega detección GraphQL por lotes con checkpoints reanudables,
extracción concurrente de Markdown/YAML a cuatro tablas Parquet relacionadas y
publicación en Hugging Face Datasets. Conserva la invocación original de la CLI.

```bash
miner data/results.csv.gz -o data/repositorios_ghaw.csv --workers 4
miner extract data/repositorios_ghaw.csv -o data/dataset --workers 8
# Instalar soporte opcional y configurar HF_TOKEN antes de publicar:
python -m pip install -e '.[publish]'
miner publish data/dataset --repo-id TU_USUARIO/miner-ghaw
```

Documentación de la nueva versión:

- [Instalación, CLI y ejemplo completo](docs/cli.md).
- [Diagrama entidad-relación y cardinalidades](docs/schema.md).
- [Diccionario de datos](docs/data-dictionary.md).

Las credenciales se configuran en `.env`; nunca se incluyen en el dataset.
La salida de `extract` debe ser un directorio nuevo. Si hay errores de YAML o
descarga, se conserva un dataset parcial y la CLI retorna código 2.

Miner es una aplicación de línea de comandos que filtra un CSV de repositorios de
GitHub y genera otro CSV con aquellos que utilizan GitHub Agentic Workflows
(GH-AW). Un repositorio se considera usuario de GH-AW cuando su directorio
`.github/workflows/` contiene al menos un par de archivos con el mismo nombre
base:

```text
daily-report.md
daily-report.lock.yml
```

Miner consulta el contenido de cada repositorio usando la API de GitHub. El CSV
de salida conserva todas las columnas y filas originales de los repositorios
que cumplen el criterio.

## Requisitos

- Python 3.10 o superior.
- Un token de acceso personal de GitHub con permisos suficientes para leer los
  repositorios que se van a consultar.

## Preparar el entorno

Desde la raíz del proyecto, crea y activa un entorno virtual:

```bash
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate       # Windows PowerShell
```

Instala Miner y sus dependencias:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

La instalación incluye Typer, Pydantic, pandas, PyGithub, python-dotenv y
pytest.

## Configuración

Copia el archivo de ejemplo y completa el token localmente:

```bash
cp .env.example .env
```

Edita `.env`:

```dotenv
GITHUB_TOKEN=tu_token_de_github
```

`.env` está excluido por `.gitignore`; nunca escribas el token en el código ni
lo publiques en Git.

## Uso

El argumento obligatorio es el CSV de entrada. Debe incluir una columna que
identifique el repositorio, preferentemente `name` con formato `owner/repo`
(como el archivo de la Tarea 1). También se reconocen `full_name`,
`repository`, `repo`, `html_url` y URLs de GitHub.

```bash
miner repositorios.csv --output repositorios_ghaw.csv
```

También puede ejecutarse sin instalar el entry point:

```bash
python -m miner repositorios.csv --output repositorios_ghaw.csv
```

`repositorios.csv` es el archivo recibido como entrada y
`repositorios_ghaw.csv` es el archivo generado como salida. Si no se indica
`--output`, se usa `repositorios_ghaw.csv` en el directorio actual.

Para consultar el formato de la ayuda:

```bash
miner --help
```

## Pruebas

Ejecuta las pruebas automatizadas con:

```bash
pytest
```

Las pruebas cubren, entre otros casos, la detección de pares válidos y de
archivos `.md` o `.lock.yml` sin su correspondiente compañero.
