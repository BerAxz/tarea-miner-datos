# Diccionario de datos

Cada tabla es un archivo `<tabla>.parquet`, comprimido con Zstandard. Los tipos
indicados son los tipos lógicos Arrow/Parquet; las columnas string son UTF-8.
Los archivos vacíos mantienen los mismos esquemas explícitos. NULL significa
ausencia, no la cadena vacía. `value_json = "null"` representa un nulo YAML.

## repositories

| Columna | Tipo | Nulo | Clave | Significado |
| --- | --- | --- | --- | --- |
| repository_id | string | no | PK | SHA-256 del nombre completo normalizado. |
| full_name | string | no | UNIQUE | `owner/repo` en minúsculas; se deduplican las filas de entrada. |
| html_url | string | no | | URL web del repositorio de entrada. |
| commit_sha | string | sí | | Commit de la rama predeterminada al extraer; NULL si falló la consulta. |
| license_spdx | string | sí | | SPDX declarado por GitHub; NULL si no está disponible, NOASSERTION si GitHub lo devuelve. |
| extracted_at | timestamp[us, UTC] | no | | Inicio de la ejecución de extracción, común a sus filas. |
| status | string | no | | `ok` o `error` para la consulta del repositorio; no resume los errores de cada archivo. |
| error | string | sí | | Descripción de error de consulta, NULL en éxito. |

## workflows

| Columna | Tipo | Nulo | Clave | Significado |
| --- | --- | --- | --- | --- |
| workflow_id | string | no | PK | SHA-256 del nombre del repositorio, NUL y ruta. |
| repository_id | string | no | FK → repositories.repository_id | Repositorio propietario. |
| path | string | no | UNIQUE con repository_id | Ruta POSIX del `.md`. |
| blob_sha | string | no | | SHA de Git del contenido del archivo. |
| source_url | string | no | | URL del archivo fijada al commit extraído. |
| has_lock | boolean | no | | Existe el `.lock.yml` del mismo nombre base y directorio. |
| frontmatter_yaml | string | sí | | YAML original sin delimitadores; NULL si no hay apertura o falla la descarga. En frontmatter sin cierre, todo lo posterior a la apertura. |
| status | string | no | | `ok`, `download_error`, `missing_frontmatter`, `unclosed_frontmatter`, `invalid_yaml`. |
| error | string | sí | | Motivo del error; NULL si status es ok. |

## bodies

| Columna | Tipo | Nulo | Clave | Significado |
| --- | --- | --- | --- | --- |
| workflow_id | string | no | PK y FK → workflows.workflow_id | Archivo fuente; relación uno a uno cuando se descargó. |
| markdown | string | no | | Body exacto después del delimitador de cierre, incluyendo espacios/saltos de línea. Sin apertura/cierre se conserva el archivo completo. |

## frontmatter_nodes

| Columna | Tipo | Nulo | Clave | Significado |
| --- | --- | --- | --- | --- |
| node_id | string | no | PK | workflow_id + `:` + pointer. |
| workflow_id | string | no | FK → workflows.workflow_id | Archivo fuente. |
| parent_node_id | string | sí | FK → frontmatter_nodes.node_id | Padre del mismo archivo; NULL solo en la raíz. |
| pointer | string | no | UNIQUE con workflow_id | JSON Pointer; raíz `""`, ejemplos `/on/schedule/0/cron` y `/engine`. `~` y `/` en claves se escapan como `~0` y `~1`. |
| key | string | sí | | Clave del mapping padre; NULL para raíz o elemento de secuencia. |
| position | int32 | no | | Orden del hijo desde cero; la raíz usa cero. |
| kind | string | no | | `mapping`, `sequence`, `string`, `boolean`, `integer`, `number`, `null`. |
| value_json | string | sí | | Escalar codificado como JSON (ej. `"copilot"`, `true`, `42`, `null`); NULL para mappings/secuencias. |

Se utiliza un SafeLoader sin constructores de objetos Python. Se conservan
`on/off/yes/no` y fechas como strings; solo `true/false` (sin distinguir mayúsculas)
son booleanos. El resto de la resolución escalar sigue PyYAML (incluida su
interpretación de enteros YAML 1.1). Las claves deben ser strings únicos. No se
admiten tipos especiales como binary/set, valores numéricos no finitos ni ciclos.
El límite de 64 niveles/100.000 nodos controla la expansión de aliases.
Se conserva YAML original incluso si no se puede estructurar.

## Archivos auxiliares

`README.md` es la dataset card generada, con una configuración de Hugging Face
por tabla, relaciones y limitaciones. `run.json` registra versión, SHA-256 del
CSV de entrada (bytes del archivo, comprimido si corresponde), workers,
conteos por tabla, duración, hits de caché, descargas exitosas, total de errores
y filas de entrada inválidas. No forman parte del modelo relacional.
