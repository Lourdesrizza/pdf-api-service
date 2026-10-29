# Integración real aislada

Este harness reproduce la integración API → Extractor real → Documents real → MongoDB 7 y la ruta por una instancia Traefik exclusiva de pruebas. Se mantiene bajo `integration/real-stack/`, separado del Compose independiente de la API. No modifica ni añade servicios al Compose de desarrollo, no conecta `pdf-network`, no publica puertos y no utiliza Redis.

## Checkouts y versiones probadas

Las rutas son parámetros de `run.ps1`; los repositorios hermanos deben ser clones independientes, limpios y con estos remotos/commits:

| Servicio | Remoto | Commit probado |
|---|---|---|
| API | `https://github.com/Lourdesrizza/pdf-api-service.git` | Base `b8cf3026c6b75982dc116b1bb4ec2f8dee8114bb`; la prueba usó el árbol de trabajo local con cambios sin commit. Para reproducir exactamente el comportamiento, usar la entrega API que contiene esos cambios documentados. |
| Extractor | `https://github.com/MaitePuente/pdf-extractor-service.git` | `5f0de842ee1bcdcd23ce1383427f6b757d8882fa` |
| Documents | `https://github.com/angelina-magallanes/pdf-document-service.git` | `8e1214d0ec82df3806c096840e3dea12defe69d5` |

La corrida registrada usó MongoDB `7.0.45` y Traefik `3.6.25`. El script verifica los remotos, los commits hermanos y que Extractor/Documents estén limpios; registra el HEAD y estado de la API sin descartar cambios locales. No se copia código de los repositorios hermanos: Compose toma sus rutas directamente para construir las imágenes.

## Requisitos

- Windows PowerShell, Git, Docker Engine/Desktop con Docker Compose v2, Python disponible como `python` y espacio para construir imágenes.
- Los tres repositorios anteriores accesibles. El API path puede ser el checkout actual; no se hace `git checkout`, reset ni limpieza.
- El usuario debe tener permiso para construir/ejecutar contenedores. La configuración no requiere red externa, puertos del host, credenciales ni acceso al Docker socket desde Traefik.

## Ejecución

Desde la raíz del checkout de API, completar las rutas de los clones independientes:

```powershell
.\integration\real-stack\run.ps1 `
  -ApiRepoPath (Resolve-Path .).Path `
  -ExtractorRepoPath 'C:\dev\pdf-proyecto\pdf-extractor-service-review' `
  -DocumentsRepoPath 'C:\dev\pdf-proyecto\pdf-document-service-review' `
  -RunIntegration -SkipLoad
```

Cada ejecución obtiene un directorio único dentro de `integration/real-stack/run/`, ignorado por Git. `-SkipLoad` omite la carga breve cuando solo se necesita verificar integración. El script genera dos PDFs sintéticos de una página; comprueba que Compose tenga únicamente `api`, `extractor`, `documents`, `mongodb`, `traefik` y `client`, una red interna y una réplica de cada servicio. Construye imágenes etiquetadas con el ID de corrida, levanta el stack y ejecuta:

1. Health/readiness y primer/segundo POST del PDF principal; valida status, fuente, ID/checksum y el contador de extracción.
2. Dos envíos concurrentes del segundo PDF y unicidad del checksum en Mongo.
3. Persistencia del registro después de reiniciar Documents.
4. Carga breve de deduplicación (1 worker, 5 segundos), salvo que se pase `-SkipLoad`.
5. Readiness y error de proceso al detener cada dependencia.
6. Health/readiness/proceso existente a través de Traefik file-provider desde el cliente interno.

Extractor corre con caché desactivada, métricas activadas y una réplica. Traefik usa una configuración de archivo exclusiva, API/dashboard desactivado y labels de Traefik desactivados. El cliente llega a `http://api:8000`; la ruta proxy se prueba contra `api.test` dentro de la misma red. La red solo es interna a este proyecto. El `finally` ejecuta `docker compose down` para los contenedores y la red de esa corrida; las imágenes y los archivos de evidencia bajo `run/` se conservan.

Si PowerShell o Docker se interrumpen antes del bloque de limpieza, se puede limpiar únicamente la última corrida registrada con:

```powershell
.\integration\real-stack\run.ps1 -CleanupOnly
```

No ejecutar ese comando si el metadata `run/last-run.json` no corresponde a esta prueba. Para borrar después las imágenes temporales, primero revisar los tags `pdf-api-real:*`, `pdf-extractor-real:*` y `pdf-documents-real:*` que generó esta corrida y eliminar solo los que correspondan. El cleanup del script no borra imágenes ni archivos.

## Fixtures y evidencia

`generate_fixtures.py` usa solo la biblioteca estándar y reconstruye los dos cuerpos sintéticos usados en la corrida registrada:

- `proof.pdf`: 608 bytes, SHA-256 `874290b0b155bc89c5ac083226ee5c854d2dee76f15ab0e8133d4845444cdc0f`, una página, texto `ISOLATED PDF API EXTRACTION PROOF`.
- `concurrency.pdf`: 598 bytes, SHA-256 `f6146dcab7423359fd75a6ccea37a5f88aec8b4ac0d3fc24eb858a779f8f7e16`.

El resultado pequeño verificable está versionado en [`results/2026-10-29-summary.json`](results/2026-10-29-summary.json). En esa corrida, health/readiness fueron 200; el primer proceso fue `extracted`, el segundo `existing`, mismo ID/checksum y contador `/extract` `0 → 1 → 1`. La entrada sin firma recibió 400 de validación API sin llamar al Extractor; el cuerpo con firma `%PDF-` pero ilegible llegó al Extractor y volvió como 422 `pdf_rejected`. El JSON resume también concurrencia, persistencia, Traefik aislado, fallos de dependencia y carga breve.

Los PDFs generados son fixtures sintéticos pequeños, no copias de los PDFs de colegas ni del dataset oficial. La carpeta `run/` puede contener logs y evidencia local, no se versiona. No se agregaron imágenes, secretos ni logs voluminosos al repositorio.


## Revalidación posterior a refactorizaciones

El 29/10/2026 se reconstruyó la imagen API desde el árbol local actual con un tag único y se repitió una vez el flujo real. El resumen está en [`results/2026-10-29-post-refactor.json`](results/2026-10-29-post-refactor.json); evidencia detallada, incluyendo inspección de imagen, `ps`, respuestas, persistencia y cleanup, en el directorio ignorado `run/20261029202204-7cdb782a/`. Esta corrida es distinta de `results/2026-10-29-summary.json`, que conserva la verificación histórica.

Health/readiness y proceso respondieron 200. Para el PDF de 608 bytes, checksum `874290b0…444cdc0f`, el primer POST fue `extracted`, el segundo `existing` con el mismo ID/checksum y el contador `/extract` permaneció `0 → 1 → 1`. La firma inválida produjo 400 en la API; el PDF con firma pero malformado llegó al Extractor y produjo 422. Documents conservó el dato al reiniciarse; la ruta por Traefik exclusivo respondió 200 y no incrementó el contador. Los errores con dependencias detenidas fueron readiness 503 y proceso 502. Esta repetición omitió la carga y los benchmarks oficiales.

## Pendientes externos explícitos

- Recibir e integrar el dataset oficial de cuatro PDFs; `tests/stress/pdfs/` no estaba disponible en los checkouts revisados.
- Recibir el PDF de 279 páginas: referencia disponible de 17.749.468 bytes y hash parcial SHA-256 `728c8a…713162`. El README del checkout antecedente lo llama `documento_279_paginas.pdf`, mientras el pedido usa `pdf279hojas.pdf`; confirmar nombre canónico y hash completo antes de verificarlo.
- Probar DNS, TLS y rutas mediante el Traefik compartido en un entorno autorizado. La instancia aislada no representa ese despliegue.
- Ejecutar el benchmark oficial del Extractor (k6/Vegeta) con el dataset oficial en el entorno responsable del Extractor. La carga API registrada mide principalmente deduplicación y no sustituye ese benchmark.

Estos pendientes significan que no se declara terminada la entrega grupal.
