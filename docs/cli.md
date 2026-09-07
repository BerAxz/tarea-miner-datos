# Uso completo de Miner

## Instalación y configuración

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,publish]'
cp .env.example .env
```

Completar `GITHUB_TOKEN` en `.env` con un token que permita consultar los
repositorios. Para publicar, configurar también `HF_TOKEN` con permisos de
escritura sobre el dataset destino (o autenticarse con `hf auth login`). Nunca
subir `.env`. `publish` es una dependencia opcional; la extracción solo requiere
`pip install -e '.[dev]'`.

## 1. Detectar repositorios (Tarea 2)

La entrada es CSV o CSV comprimido `.csv.gz`. Se reconoce `name`, `full_name`,
`repository`, `repo`, URLs GitHub, y otras variantes del modelo; también columnas
separadas `owner`/`repo`. El CSV de salida conserva columnas, orden y filas
duplicadas del original para los repositorios que contienen un par válido.

```bash
miner data/results.csv.gz --output data/repositorios_ghaw.csv --workers 4
# Equivalente con subcomando explícito:
miner detect data/results.csv.gz -o data/repositorios_ghaw.csv --workers 4 --batch-size 100
```

GraphQL agrupa hasta 100 repositorios por consulta y lee solo el árbol de
workflows. Consulta subdirectorios por su SHA solo cuando todavía no encuentra
un par válido, agrupando también esas consultas.
Se conservan las coincidencias por ruta, por lo que `a/x.md` y `b/x.lock.yml`
no forman un par. No se usa búsqueda indexada ni filtros por fecha/lenguaje
que puedan excluir candidatos. Los repositorios privados/inaccesibles o
eliminados quedan como `unavailable` en el checkpoint; no son coincidencias
ni prueban ausencia de GH-AW. Los errores de autenticación, transporte o
respuestas incompletas detienen la ejecución sin fabricar resultados negativos.
Al terminar se genera también `<salida>.report.json` con los conteos y la lista
de repositorios inaccesibles para auditar la cobertura del CSV resultante.

La detección lee 5.000 filas a la vez y conserva checkpoints SQLite después de
cada lote. Si se interrumpe, ejecutar exactamente el mismo comando reanuda las
consultas pendientes y reconstruye el CSV. El archivo final se reemplaza solo
cuando se completa el recorrido; ante errores se conserva la salida anterior.

El checkpoint predeterminado es `.miner-cache/detection.sqlite`. Reutilizarlo
significa aceptar resultados de sus fechas `checked_at`, incluidos los
repositorios inaccesibles. Para un escaneo actualizado, indicar un checkpoint
nuevo (no borrar la caché de blobs):

```bash
miner detect data/results.csv.gz -o data/repositorios_ghaw.csv \
  --checkpoint .miner-cache/detection-nueva.sqlite
```

Para datasets pequeños o tokens sin acceso a GraphQL se mantiene el recorrido
REST, concurrente pero sujeto a una consulta por directorio más metadatos:

```bash
miner detect repositorios.csv -o repositorios_ghaw.csv --api rest --workers 4
```

## 2. Extraer el dataset (Tarea 3)

Usar como entrada el CSV **resultante de la detección**, no los candidatos:

```bash
miner extract data/repositorios_ghaw.csv --output data/dataset --workers 8
```

La salida debe ser un directorio nuevo. Se generan `repositories.parquet`,
`workflows.parquet`, `bodies.parquet`, `frontmatter_nodes.parquet`, `README.md`
y `run.json`. Las tablas se escriben incrementalmente por repositorio con
Zstandard y esquemas explícitos. El directorio se hace visible al terminar.

La extracción usa conexiones independientes por hilo, fija el commit de cada
repositorio y descarga solo `.md`. Los blobs se almacenan en `.miner-cache/`,
indexados y verificados con su SHA de Git. Para repetir la extracción sin
redescargar contenido que no cambió, conservar esa caché y elegir otra salida:

```bash
miner extract data/repositorios_ghaw.csv -o data/dataset-v2 \
  --cache-dir .miner-cache --workers 8
```

El resumen muestra duración, descargas e hits de caché. No se prometen tiempos
fijos: dependen de red, número de archivos y cuotas. GitHub puede exigir espera
por límites primarios/secundarios. Un número mayor de workers no aumenta la cuota.
Las lecturas REST usan los reintentos de PyGithub; GraphQL respeta Retry-After y
el reset de cuota HTTP, reintenta fallos transitorios hasta cinco veces y
conserva lo completado si la API no permite seguir.
Los límites secundarios pausan conjuntamente los workers y reducen a la mitad
la concurrencia de consultas; los lotes que exceden recursos/tiempo se dividen.

Códigos de salida: `0` extracción completa sin errores; `1` error fatal de
entrada/configuración/ejecución; `2` dataset generado con errores parciales.
Revisar status/error de repositorios y workflows y run.json antes de publicar.
No se pierde el body por YAML inválido. Un repo sin Markdown genera su fila de
repositorio pero ninguna fila de archivo. Una entrada solo con encabezados
genera tablas vacías tipadas. La publicación rechaza datasets sin Markdown.

## 3. Consultar y publicar

```bash
python -c 'import pandas as pd; print(pd.read_parquet("data/dataset/workflows.parquet")[["path", "status", "has_lock"]])'
miner publish data/dataset --repo-id TU_USUARIO/miner-ghaw
```

`publish` crea el repositorio de tipo dataset si no existe y sube exclusivamente
los cuatro Parquet, README.md y run.json en un commit. Por defecto la creación
es pública; `--private` crea un dataset privado. Un repositorio existente
conserva su visibilidad. Para la entrega se necesita un dataset público.
Volver a publicar al mismo destino actualiza esos archivos; el historial de
Hugging Face conserva las versiones anteriores.

El comando imprime `https://huggingface.co/datasets/TU_USUARIO/miner-ghaw`.
Cada tabla aparece como configuración independiente del visor para evitar
mezclar esquemas incompatibles. Véase la
[configuración oficial de datasets](https://huggingface.co/docs/hub/datasets-manual-configuration).

## Ejemplo completo

Con el entorno preparado y los tokens configurados:

```bash
miner detect data/results.csv.gz -o data/repositorios_ghaw.csv --workers 4
miner extract data/repositorios_ghaw.csv -o data/dataset --workers 8
python -m pytest
miner publish data/dataset --repo-id TU_USUARIO/miner-ghaw
```

Si extract retorna 2, revisar primero el dataset parcial. Para entregar,
adjuntar el enlace del repositorio GitHub actualizado y el del dataset
publicado. El CSV filtrado es además la salida requerida por la Tarea 2.

La CLI también funciona como `python -m miner`. Consultar `miner --help`,
`miner detect --help`, `miner extract --help` y `miner publish --help`.
