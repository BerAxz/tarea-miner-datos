# Verificación de la implementación

La rama de trabajo es `feature/ghaw-parquet-dataset`. Las verificaciones locales
se ejecutaron con Python 3.14; el workflow de CI incluye Python 3.10 y 3.14.
No se afirma que CI haya pasado hasta ejecutarlo en GitHub.

## Pruebas automatizadas

```bash
python -m pytest
git diff --check
```

Se verifican detección de pares en el mismo directorio, conservación de columnas
y duplicados del CSV, reanudación de checkpoints, GraphQL parcial/errores, división
de lotes con errores 502, recorrido de subdirectorios por SHA, PK/FK y tipos
Parquet, YAML anidado/listas/tipos, `on`, BOM/CRLF, YAML inválido y malicioso,
tablas vacías, caché verificada y reparación de corrupción, CLI original,
códigos de salida y selección exclusiva de archivos al publicar.

## Prueba real de extracción

El primer repositorio coincidente encontrado en el CSV original fue
`azure/azure-sdk-for-java`. Se probó la extracción de ese repositorio con la CLI:

| Medida | Primera extracción | Repetición con caché |
| --- | ---: | ---: |
| Repositorios | 1 | 1 |
| Markdown | 2 | 2 |
| Descargas de blobs | 2 | 0 |
| Hits de caché | 0 | 2 |
| Errores | 0 | 0 |
| Duración informada | 3,446 s | 2,474 s |

El primer dataset contiene 124 nodos YAML. Ambas ejecuciones generaron los
cuatro Parquet y su dataset card. Es una prueba de integración con GitHub,
no el dataset final de los 473.619 candidatos.

## Mediciones de detección

El CSV `data/results.csv.gz` contiene 473.619 filas y referencias distintas.
Una consulta real de 100 repositorios con expansión anticipada de subdirectorios
tardó 21,35 s; la consulta liviana de esos 100 tardó 6,81 s y costó un punto
GraphQL. Esta comparación no es un benchmark controlado: las consultas fueron
sucesivas y GitHub puede aprovechar cachés. Se eliminaron las expansiones
innecesarias de la implementación final. Un ensayo de 500 repositorios devolvió
502; se mantuvo el máximo de 100 y se añadió división automática ante errores
de tamaño/tiempo. No se extrapolan estos tiempos a todo el dataset.

La cuota REST observada fue de 5.000 consultas por hora. GraphQL reduce
solicitudes mediante lotes; no elimina los límites del servicio. El checkpoint
permite auditar `repository`, `matched`, `status` y `checked_at` por candidato.

Los límites de GitHub están documentados en
[REST](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
y [GraphQL](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api).
