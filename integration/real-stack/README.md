# Integración real aislada

Este harness reproduce la integración API → Extractor real → Documents real → MongoDB 7 y la ruta por una instancia Traefik exclusiva de pruebas. Se mantiene bajo `integration/real-stack/`, separado del Compose independiente de la API. No modifica ni añade servicios al Compose de desarrollo, no conecta `pdf-network`, no publica puertos y no utiliza Redis.

## Checkouts y versiones probadas

Las rutas son parámetros de `run.ps1`; los repositorios hermanos deben ser clones independientes, limpios y con estos remotos/commits:

| Servicio | Remoto | Commit probado |
|---|---|---|
| API | `https://github.com/Lourdesrizza/pdf-api-service.git` | `3d3308e51ae6337ba25be7a82bb55e0fe859a849` (HEAD observado en la corrida del PDF grande). `app/` coincide con la versión funcional ya revalidada; el árbol local tenía cambios solo en el harness de esta prueba, registrados en el resumen. |
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

## Aceptación del PDF original de 279 páginas

El 30/10/2026, antes de levantar el stack, se verificó el archivo recibido por tamaño (**17.749.468 bytes**), páginas (**279**, con `pdfinfo`) y SHA-256 (`728c8a522ce24bf0ba3851cd109cdc0e55b200e3cd9d55b8343b39c005713162`). El resumen pequeño con versiones, IDs de imágenes, tiempos y contadores está en [`results/2026-10-30-pdf279-summary.json`](results/2026-10-30-pdf279-summary.json); la evidencia detallada está en `run/20261030132044-146e04a7/` (carpeta ignorada).

Con límites y timeouts sin cambios, el primer POST binario respondió 200 `extracted`, ID `6ae499efc2231a43fd559f4d`, checksum correcto y 279 páginas. El contenido tuvo 427.008 caracteres, incluyó los encabezados de la primera y última página y su SHA-256 fue `c636e1997422a5a99c45dc6ff9f2d2228f062d1e432b2948b373aa4328c1cdbc`. El segundo POST idéntico respondió 200 `existing`, mismo ID/checksum y mismo hash de contenido. Multipart respondió 200 `existing` con los mismos datos. El contador HTTP `POST /extract` para esos tres envíos fue `0 → 1 → 1 → 1`; los tiempos fueron 8.475,110 ms, 191,637 ms y 2.113,046 ms respectivamente.

Después de reiniciar Documents, el registro siguió disponible con el mismo ID, checksum, número de páginas y hash de contenido; el contador permaneció `4 → 4`. Los incrementos posteriores al flujo del PDF grande fueron de verificaciones independientes: el rechazo de firma inválida dio 400 y no incrementó (1 → 1); el PDF malformado dio 422 y sí llamó al Extractor (1 → 2); la consulta existente por Traefik no incrementó (2 → 2); las dos peticiones concurrentes de cobertura (no una prueba de carga) llevaron el contador de 2 a 4. Readiness, ruta por Traefik exclusivo y persistencia respondieron 200. MongoDB informó `7.0.45`. Se omitió la carga (`-SkipLoad`); no se ejecutaron benchmarks.

Para repetir con el archivo original fuera del repositorio, pasar su ruta local con `-PdfPath`; el harness vuelve a verificar tamaño/hash/páginas, copia temporalmente el PDF a su carpeta ignorada y borra esa copia al limpiar. Requiere `pdfinfo` (Poppler) en `PATH`:

```powershell
.\integration\real-stack\run.ps1 `
  -ApiRepoPath (Resolve-Path .).Path `
  -ExtractorRepoPath 'C:\dev\pdf-proyecto\pdf-extractor-service-review' `
  -DocumentsRepoPath 'C:\dev\pdf-proyecto\pdf-document-service-review' `
  -PdfPath 'C:\Users\lulir\Downloads\pdf279hojas.pdf' `
  -RunIntegration -SkipLoad
```

El PDF grande no se agregó a Git. Esta aceptación no sustituye al dataset oficial de cuatro PDFs ni al benchmark oficial del Extractor.
Los IDs de las tres imágenes construidas se registraron en el resumen y sus tags únicos de corrida se retiraron al limpiar; las imágenes preexistentes de MongoDB y Traefik se conservaron.

## Revisión estática de la infraestructura compartida

Lectura del checkout disponible de `pdf-infrastructure` en `ff9223ad4640edfd3b2b3fd9b9b8549ecd097615` (29/10/2026); no se ejecutó ni modificó ese despliegue. Su `docker-compose.integration.yml` construye la API desde `../pdf-api-service/Dockerfile`, usando los aliases `extractor:8000` y `documents:8000`, coherentes con esta API. El puerto interno es 8000 y `pdf-network` es externa. Para incorporar la versión API registrada actualmente, el checkout usado como contexto debe estar limpio y en `3d3308e51ae6337ba25be7a82bb55e0fe859a849` antes de reconstruir únicamente `api`.

La ruta declarada es `api.universidad.localhost` en el entrypoint `web` (HTTP puerto 80); ese Compose no configura TLS y el hostname `.localhost` es local a la máquina. El healthcheck de Docker y el healthcheck activo de Traefik consultan `/health`, que en esta API es liveness; no consultan `/ready`, que valida Extractor y Documents. La configuración inyecta `REDIS_URL` a la API aunque el código de API no la usa. El límite configurado para API en infraestructura es 1 CPU / 1 GiB, frente a 1 CPU / 512 MiB en el Compose independiente de esta API; Jeremías debe confirmar el límite acordado.

El Compose compartido no fija `METRICS_ENABLED` para Extractor. Su valor predeterminado es `false`, así que no se publica `/metrics` en las réplicas actuales. Para verificar el contador de extracción en todas las réplicas, Jeremías debe habilitarlo en el servicio y configurar el scrape de cada réplica; la instancia Traefik aislada del harness no verifica ese scrape.

### Procedimiento propuesto para actualizar solo la API

Usar un checkout de despliegue limpio con el layout de repositorios hermanos que espera el Compose. No cambiar ni limpiar el checkout de API de la autora. Confirmar además que el nombre de proyecto Compose, los archivos `-f` y las variables sean los mismos del stack compartido; una invocación con otro proyecto podría crear volúmenes con otro prefijo. La siguiente operación no ejecuta `down` ni reconstruye Mongo, Redis, Extractor o Documents:

```powershell
# Desde el checkout de pdf-infrastructure. API debe ser un clon de despliegue limpio en ../pdf-api-service.
$api = (Resolve-Path ..\pdf-api-service).Path
$expected = '3d3308e51ae6337ba25be7a82bb55e0fe859a849'
$apiStatus = git -C $api status --porcelain
if ($LASTEXITCODE -ne 0) { throw 'No se pudo comprobar el estado del clon de API.' }
if ($apiStatus) {
  throw 'El clon de despliegue de API tiene cambios; no se descartan ni se reemplazan.'
}
git -C $api fetch origin main
if ($LASTEXITCODE -ne 0) { throw 'No se pudo actualizar la referencia de API.' }
git -C $api checkout --detach $expected
if ($LASTEXITCODE -ne 0 -or (git -C $api rev-parse HEAD).Trim() -ne $expected) {
  throw 'No se pudo fijar el contexto de API en el commit publicado esperado.'
}

# Reemplazar por el nombre de proyecto que usa el stack ya desplegado.
$compose = @('-p', 'NOMBRE_PROYECTO_EXISTENTE', '-f', 'docker-compose.integration.yml')
$container = docker compose @compose ps -q api
if (-not $container) { throw 'No se encontró el contenedor API del proyecto indicado.' }
$oldImageId = docker inspect --format '{{.Image}}' $container
$oldImageRef = docker inspect --format '{{.Config.Image}}' $container
$rollbackTag = 'pdf-api-service:rollback-' + (Get-Date -Format 'yyyyMMddHHmmss')
docker image tag $oldImageId $rollbackTag

docker compose @compose build api
if ($LASTEXITCODE -ne 0) { throw 'Falló la construcción de la API.' }
$builtImageId = docker image inspect $oldImageRef --format '{{.Id}}'
docker compose @compose up -d --no-deps --force-recreate api
if ($LASTEXITCODE -ne 0) { throw 'Falló la actualización del servicio API.' }
$container = docker compose @compose ps -q api
if (-not $container) { throw 'No se encontró el contenedor API actualizado.' }
$runningImageId = docker inspect --format '{{.Image}}' $container
if ($runningImageId -ne $builtImageId) { throw 'El contenedor no usa la imagen recién construida.' }
docker inspect --format 'container={{.Id}} image={{.Config.Image}} image_id={{.Image}}' $container
```

Guardar el ID anterior, el tag de rollback, el ID de la imagen nueva y el `HEAD` comprobado. Para revertir solo la API, restaurar el tag Compose guardado y recrear el servicio sin build:

```powershell
docker image tag $rollbackTag $oldImageRef
docker compose @compose up -d --no-deps --no-build --force-recreate api
```

Antes de enviar un PDF por la URL compartida, Jeremías debe confirmar una base Mongo de integración dedicada y descartable. Sin ella, limitar la verificación a `/health` y `/ready`; no persistir documentos de prueba en la base compartida. La prueba autorizada para ese entorno dedicado debe enviar el mismo PDF dos veces, revisar `extracted` y luego `existing`, recuperar el documento persistido y sumar `pdf_http_requests_total{method="POST",route="/extract"}` en todas las réplicas antes y después.

## Pendientes externos explícitos

- Recibir e integrar el dataset oficial de cuatro PDFs; `tests/stress/pdfs/` no estaba disponible en los checkouts revisados. El PDF original de 279 páginas ya se aceptó en la corrida del 30/10/2026; no sustituye ese dataset.
- Probar DNS, TLS y rutas mediante el Traefik compartido en un entorno autorizado. La instancia aislada no representa ese despliegue.
- Ejecutar el benchmark oficial del Extractor (k6/Vegeta) con el dataset oficial en el entorno responsable del Extractor. La carga API registrada mide principalmente deduplicación y no sustituye ese benchmark.

Estos pendientes significan que no se declara terminada la entrega grupal.
