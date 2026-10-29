# Auditoría del estado actual de pdf-api-service


## Estado actualizado — integración real completada (29/10/2026)

Esta sección prevalece sobre las verificaciones y pendientes anteriores. Las secciones históricas fechadas el 28/10 y la auditoría inicial quedan conservadas como trazabilidad, no como estado vigente. Los resultados externos de esa corrida están resumidos y versionados en integration/real-stack/results/2026-10-29-summary.json; el harness reproducible y las rutas de clones parametrizadas están en integration/real-stack/README.md. La verificación inicial descrita aquí es histórica; la revalidación posterior a las refactorizaciones se registra en la sección siguiente.

| Requisito | Responsable | Evidencia de esta ejecución | Estado / pendiente |
|---|---|---|---|
| API `/process`, firma/tamaño, checksum, respuesta y deduplicación | API | Dos envíos directos al API real: primer envío `extracted`, repetido `existing`, mismo ID/checksum; extractor HTTP POST `/extract` 0→1→1 | Cumplido para el fixture de integración de 608 bytes/1 página |
| Conversión PDF y benchmark oficial | Extractor | Clon independiente `pdf-extractor-service-review`, commit `5f0de842ee1bcdcd23ce1383427f6b757d8882fa`, caché off, métricas on, réplica única | Integración funcional probada. Benchmark oficial de Extractor no ejecutado desde este trabajo; corresponde a su servicio y conjunto oficial |
| Persistencia y contrato de checksum | Documents + MongoDB | Clon independiente `pdf-document-service-review`, commit `8e1214d0ec82df3806c096840e3dea12defe69d5`; Mongo `7.0.45`; dos documentos, IDs/contenido/checksum, índice `uq_documents_checksum` único | Cumplido; reiniciar Documents mantuvo los datos y el PDF principal volvió como `existing` sin aumentar extracción |
| Carrera de duplicados | API + Documents | Dos envíos simultáneos de un segundo PDF válido: ambos 200, mismo ID/checksum y fuentes `extracted`/`existing`; Mongo guardó un único registro para ese checksum | Cumplido; no se exigió una sola extracción en la carrera |
| Proxy de prueba | Infra de prueba | Traefik `v3.6.25`, proveedor file, regla `Host(api.test)`, red interna, cliente interno; health/readiness/proceso respondieron 200; logs de acceso guardados | Ruta aislada probada. No acredita DNS, TLS ni Traefik compartido; no se usó socket Docker ni `pdf-network` |
| Errores de PDF | API + Extractor | `not a PDF` → API 400 `invalid_pdf`, contador extractor sin cambio. `%PDF-1.4` mal formado → API 422 `pdf_rejected`, contador de `/extract` aumentó una vez | Distinción verificada en los servicios reales, sin cambiar el contrato de esos estados |
| Correlación y Retry-After | API | X-Request-ID válido se valida, se devuelve y se reenvía; el log real del Extractor mostró `integration-primary-proof` y `integration-extractor-rejection`. Pruebas comprueban Retry-After válido 1..86400, fallback `1`, sin reintentos automáticos | Implementado y probado |
| Readiness y dependencia caída | API | Detener Extractor y después Documents dentro del proyecto aislado: `/ready` 503 con la dependencia precisa; `/process` 502 JSON sanitizado en ambos casos | Cumplido |
| Carga simple de API | API | 1 worker, 5 segundos, PDF repetido: 29 requests, 0 errores, 5.79 requests/s, p50 18.3 ms, p95 73.6 ms; 29 `existing`, 0 `extracted` | Cumplido como comprobación breve de deduplicación; no mide extracción de PDFs nuevos |
| PDFs oficiales | Equipo / responsable del dataset | No se encontró `tests/stress/pdfs/` en el clon del Extractor ni en los tests de la API; en el checkout antecedente solo está un README de referencia. El archivo de 279 páginas solicitado no aparece en Downloads ni en `C:\dev\pdf-proyecto` | Pendiente de que entreguen los 4 PDFs oficiales. Falta `pdf279hojas.pdf` (esperado: 279 páginas, 17.749.468 bytes, SHA-256 `728c8a…713162`). El README del checkout antecedente nombra `documento_279_paginas.pdf`; confirmar cuál es el nombre canónico. No se generaron ni sustituyeron PDFs |

### Entorno y resultado reproducible de esta corrida

- Proyecto: `C:\dev\pdf-proyecto\api-real-documents-20261029164147-5fa2d721`; Compose autónomo fuera de los repositorios, red interna `api-real-documents-20261029164147-5fa2d721_isolated`, sin conexión a `pdf-network`, sin Redis, sin puertos publicados y sin volumen externo. Mongo usó el filesystem efímero de su contenedor dedicado.
- API: checkout local con los cambios conservados de usuario, HEAD `b8cf3026c6b75982dc116b1bb4ec2f8dee8114bb`. No se hizo commit ni push.
- Extractor y Documents se leyeron/ejecutaron desde los clones independientes y commits de la matriz; los dos repositorios de revisión permanecen limpios y sin cambios. Infra compartida no se arrancó ni modificó.
- Traefik exclusivo de prueba: proveedor file; labels `traefik.enable=false`; API dashboard desactivado; sin Docker socket. Cliente interno, porque la publicación dinámica de puerto no era necesaria.
- Evidencia (Compose, configs, PDFs pequeños de prueba, salidas, logs de servicios/proxy, inspección Mongo, resultados de carga y limpieza) en la carpeta de proyecto indicada. La prueba anterior API + Extractor + Documents fake, `C:\dev\pdf-proyecto\isolated-proof-20261029161954-592c5e94`, se conservó y se reutilizó como fuente del PDF; no se repitió como prueba aislada.
- Limpieza comprobada: `docker compose down` eliminó únicamente los contenedores y la red de este proyecto. No quedaron contenedores ni red con el nombre de la ejecución; se retuvieron las imágenes y archivos de evidencia.
- Cambios de código en esta continuación: sanitización/propagación de X-Request-ID, reenvío validado de Retry-After, pruebas focalizadas y reemplazo de `assert` por validaciones explícitas en `scripts/check_api.py`. Documentación actualizada. No hubo cambios en Extractor, Documents ni Infra.
- Prueba previa durante el trabajo: un test de propagación usando RESPX no registró llamadas por el ciclo de vida del cliente compartido; se sustituyó por una comprobación directa con `httpx.MockTransport` que inspecciona cada request saliente. El flujo real confirmó el header en los logs del Extractor.

Fuentes de requisitos leídas completas: `Trabajo Práctico Test de Carga y Stress sobre Microservicio.pdf` (4 páginas), `Plan_Maestro_Microservicios_PDF_Extractext_260930_185001.pdf` (22 páginas) y `1_5100494171915946430_261021_175241.pdf` (14 páginas físicas). La asignación resultante deja `/process` y la carga breve de API en API; extracción CPU, conjunto PDF y benchmark k6/Vegeta oficial en Extractor; Mongo y almacenamiento en Documents; proxy compartido en Infra. El stack Traefik de esta corrida fue independiente y solo verifica esa configuración aislada.

### Verificación final

- `uv run --locked pytest -v`: **73 passed, 1 skipped, 1 warning**. El skip es la prueba live condicionada por variables de entorno; la integración real se comprobó con el cliente interno del Compose dedicado.
- `uv lock --check --offline`: aprobado, 33 paquetes.
- Build final de API: `pdf-api-service:integration-final-20261029164147-5fa2d721`, aprobado. El build de las imágenes API/Extractor/Documents para la integración también terminó correctamente.
- `docker compose ... config --quiet`: aprobado para el Compose dedicado. `git diff --check`: aprobado.
- Sin staging, commits ni push. Los cambios locales preexistentes, incluidos los del Dockerfile, schemas/orquestador, scripts, fixtures y tests, se conservaron. Solo se añadieron los cambios descritos arriba.



## Revalidación posterior a refactorizaciones — 29/10/2026

- Se ejecutó `integration/real-stack/run.ps1` una vez con `-SkipLoad`. El runner creó un proyecto/directorio únicos, reconstruyó la API desde el checkout local con el tag `pdf-api-real:20261029202204-7cdb782a` (image ID `sha256:d38a0807a7d82c9bfc9540c3203db4479b8f952e584423d8a071e6277f41ebee`) y no ejecutó carga.
- Health/readiness: 200. PDF válido: 200 `extracted`, luego 200 `existing`, mismo ID/checksum y contador HTTP `/extract` `0→1→1`. Firma inválida: API 400 `invalid_pdf` sin extracción; PDF malformado con firma: 422 `pdf_rejected` desde el rechazo del Extractor.
- Persistencia: tras reiniciar Documents, readiness 200, documento existente y contador estable `4→4`; Mongo registró 2 documentos e índice único de checksum. Traefik exclusivo: health/readiness/proceso 200 y contador estable `2→2`. Dependencias detenidas: readiness 503 y proceso 502 sanitizado.
- Cleanup verificado: no quedan contenedores ni red con el prefijo del proyecto; imágenes y evidencia ignorada se retuvieron. Dataset oficial, PDF grande, Traefik compartido y benchmark oficial siguen pendientes.
- Resumen nuevo y compacto: `integration/real-stack/results/2026-10-29-post-refactor.json`. Evidencia detallada local e ignorada por Git: `integration/real-stack/run/20261029202204-7cdb782a/`. Es una corrida separada del resumen histórico `2026-10-29-summary.json`.

## Revisión de SOLID y código limpio — 29/10/2026

- **Responsabilidad única:** `main.py` queda como punto de composición del lifespan y las rutas; la lectura/límite del PDF sigue en `validation.py`, las llamadas HTTP en sus clientes y el flujo checksum → extracción → persistencia en `Orchestrator`. Se extrajeron los metadatos OpenAPI y la regla de validación de request-id de las declaraciones largas para hacerlas legibles sin cambiar el contrato.
- **Inversión de dependencias / segregación:** `Orchestrator` ahora tipa dos Protocols estructurales y estrechos (`DocumentsGateway`, `ExtractorGateway`) con solo las operaciones del flujo de proceso. Las implementaciones HTTP siguen inyectándose en el lifespan; las pruebas ya pueden sustituirlas por dobles sin herencia ni servicios reales.
- **Validación y tipos:** la respuesta de Extractor usa un modelo `ExtractionResult` estricto con contenido string y páginas enteras positivas. `ProcessResponse.source` expresa sus dos valores válidos como `Literal`. La validación manual previa y el modelo hacen cumplir el mismo contrato; no cambian estados HTTP ni payloads válidos.
- **Simplificación:** el resultado del orquestador recibe un `DocumentPayload` ya validado, por lo que se quitaron fallbacks para ID/checksum imposibles bajo ese modelo. Se retiró `app/cache.py`: `ResultCache`/`NullResultCache` no tenían consumidores y solo anunciaban una extensión hipotética; README ahora describe que la API opera sin caché.
- **OCP/LSP:** no se agregó framework de plugins ni jerarquía de clases. Los mapeos de error siguen siendo explícitos porque Extractor y Documents tienen contratos HTTP distintos y son solo dos dependencias. No hay herencia de producción que requiera una comprobación LSP; la sustitución relevante se cubre mediante inyección estructural.
- **Scripts/harness:** las comprobaciones siguen separadas entre `run.ps1`, `verify.py`, `persistence_check.py`, `dependency_check.py` y `check_api.py`; no se agregaron capas al código de prueba. Para la revalidación posterior se agregaron `-SkipLoad`, un directorio de evidencia por corrida, inspección del tag único de API y validación segura del metadata de cleanup. La primera ejecución expuso que `git status --porcelain` vacío es `$null` en PowerShell; el runner ahora lo trata como checkout limpio. Se ejecutó el harness completo luego de esos cambios; resultados en la sección anterior. El resumen histórico se conserva sin sobrescribirlo.

### Evidencia de esta refactorización

- `uv run --locked pytest -v`: **73 passed, 1 skipped, 1 warning** (aviso conocido de deprecación Starlette/TestClient). Incluye validación de respuestas inválidas del Extractor, mapeo de errores, deduplicación, contrato de Documents, request-id y cierre del cliente HTTP.
- Las comprobaciones de scripts/harness se ejecutan al cierre de esta revisión: parseo de Python/PowerShell, sintaxis del wrapper shell y `git diff --check`. No se ejecutó la integración real ni se construyeron imágenes porque sus comandos y verificaciones no cambiaron.
- No se incorporaron dependencias, servicios ni herramientas de lint nuevas.


## Revisión final previa al commit

Se revisaron diff completo y seis archivos nuevos (20 archivos candidatos en total). Se conserva la sección preexistente de pruebas con fakes del README, con correcciones de sintaxis y aclaración de integración real pendiente. El fixture sample.pdf tiene 1372 bytes, una página, texto de prueba y metadatos genéricos; es necesario para los tests.

Ejecución final: `.venv/Scripts/python.exe -m pytest -q -m 'not integration' -p no:cacheprovider` => **64 passed, 1 deselected, 1 warning**, 11,78 s. Incluye lifespan; la integración real quedó excluida explícitamente. Warning conocido de Starlette/TestClient. El CMD con exec conserva la evidencia Docker aprobada en la sección siguiente; pytest no sustituye esa prueba de señales. No se repitieron builds ni pruebas Docker.

`git diff --check` aprobado. Revisión de candidatos y búsqueda de patrones de credenciales sin hallazgos; no hay .env real, cachés, logs, claves privadas ni archivos de entorno entre los candidatos. Las referencias a secretos en tests son marcadores sintéticos. El informe contiene rutas locales de trazabilidad, no credenciales. No se hicieron staging, commit ni push.

Observación menor pendiente: los validadores del script de carga/E2E usan assert y deben ejecutarse sin `python -O` ni PYTHONOPTIMIZE; las invocaciones documentadas usan Python normal. Una mejora futura es reemplazarlos por validaciones explícitas para conservar esos controles también bajo optimización.

## Verificación adicional de desechabilidad y shutdown

Se agregó `exec` al CMD del Dockerfile conservando el destino real `app.main:app`, los argumentos y `${PORT:-8000}`. El shell expande PORT y luego es reemplazado por Uvicorn; no queda como intermediario para las señales. El ejemplo `app.main` sin `:app` no se adoptó porque no conserva el destino ASGI vigente.

El lifespan ya utiliza `async with httpx.AsyncClient(...)`: ambos clientes comparten esa instancia y se cierra al salir del contexto. No necesitó cambios. La nueva prueba `tests/test_lifespan.py` comprueba identidad compartida, estado abierto dentro del lifespan y `is_closed` al terminar: **1 passed** (`python -m pytest tests/test_lifespan.py -q -p no:cacheprovider`).

`docker build -t pdf-api-service:shutdown-check .` terminó con código 0. Se arrancó únicamente un contenedor propio con `docker run -d --init --network none -e PORT=8123 pdf-api-service:shutdown-check`, sin publicar puertos, usando el CMD de la imagen. La consulta interna a `/health` respondió 200 y el log confirmó puerto 8123: expansión de PORT verificada. Se detuvo con `docker stop --time 15 <id-propio>` (Docker recomienda ahora `--timeout`), se inspeccionó y se eliminó exclusivamente ese contenedor.

Resultado del contenedor: **ExitCode=143, OOMKilled=false**. 143 corresponde a terminación por SIGTERM; no se presenta como salida 0. Los logs confirman que Uvicorn completó el cierre ordenado antes de finalizar:

```text
Shutting down
Waiting for application shutdown.
Application shutdown complete.
Finished server process [7]
```

La prueba reproduce `init: true` mediante `--init` y verifica apagado en reposo. No demuestra drenaje de solicitudes de extracción en curso ni cierre de conexiones activas con servicios reales: el contenedor estuvo sin red. El cierre efectivo del cliente HTTP se verificó por separado con el test de lifespan. No se modificó infraestructura de terceros ni se hicieron commits o despliegues compartidos.

Fecha: 28/10/2026, America/Argentina/Buenos_Aires. Auditoría de código y verificaciones aisladas, sin correcciones de implementación.

## Actualización tras implementación autorizada — 28/10/2026

Esta actualización prevalece sobre la matriz histórica que sigue, conservada como trazabilidad de la auditoría inicial.

- Corregidos F01/F02: resultado Documents conserva 200/201; source refleja existencia; 409 excepcional con reconsulta; fake estricto, hash válido, páginas estrictas positivas, extras prohibidos, id/created_at y duplicados 200.
- Corregidos F03/F06: fixture PDF válido controlado; integración real exige API_DEDICATED_TEST_ENV=1 y API_TEST_URL. Respuestas necesarias estrictas, checksum coincidente, contenido ausente rechazado pero cadena vacía permitida. created_at/filename remotos no son obligatorios porque no se necesitan para la respuesta pública.
- Corregido F04: 400/415 extractor =>422, 413=>413, 429/503=>503, timeout=>504, conexión/protocolo=>502. No se registran cuerpos upstream ni se propaga detail. Diagnóstico de transporte por tipo de excepción.
- F05 conserva límite de cuerpo completo por pedido explícito, documentado y probado con varios chunks y fronteras binario/multipart.
- F07 sigue requiriendo coordinación: un 404 de ruta no se distingue universalmente de ausencia; no se inventó un formato remoto.
- F08: OpenAPI describe ambos cuerpos y headers, logging stdout, README/fences/curl corregidos, contratos sincronizados. PORT=8000 y dev/test alternativos documentados. Fijar digests/lock de fakes sigue siendo mejora opcional.
- Scripts E2E comparten validador Python/httpx: status, campos, hash local e igualdad ID/checksum; fallan ante errores. Carga conservadora preparada, destino explícito, 1..4 workers y 1..30 segundos; escenario repetido identificado. No se ejecutó carga ni E2E real; no se inventaron métricas.

### Verificaciones de la implementación

- `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`: **63 passed, 1 skipped, 1 warning**, 14,88 s. Warning existente de Starlette/TestClient. Incluye contratos, privacidad, tamaños, caminos 200/201/409, respuestas inválidas y recorrido de orquestador con Documents ASGI/fake y contador extractor (una extracción para dos envíos). Esto es integración en memoria con dobles, no servicios reales.
- Tres `docker compose ... config --quiet` (base, base+dev y test): salida correcta, exit 0.
- `uv lock --check --offline`: exit 0, 33 paquetes.
- `docker build -t pdf-api-service:audit-fixed .`: exit 0, con caché de dependencias.
- `docker run --rm --network none --entrypoint python pdf-api-service:audit-fixed ...`: arranque uvicorn y GET interno /health =>200, salida ordenada, exit 0. Sin puertos publicados; se eliminó solo el contenedor efímero propio. Primer intento a los 3 segundos consultó antes del fin del arranque; repetición a los 10 segundos aprobada.
- `python scripts/check_api.py --help`: exit 0. Scripts preparados; no se atribuye ejecución end-to-end real.
- Hubo una primera ejecución con cuatro fallos de transporte durante implementación; se corrigieron y la suite final pasó.

Pendientes externos: stack real dedicado API/Extractor/Documents/Mongo 7, fixture exacto de 279 páginas y 17.749.468 bytes, instrumentación del extractor real para acreditar no reextracción, y entorno de carga exclusivo. Sin estos recursos no se certifican Traefik, Mongo, resiliencia ni throughput real.

Archivos funcionales modificados: app/clients/{base,documents,extractor}.py, app/{main,schemas}.py, app/services/orchestrator.py; tests/fakes/documents.py, tests/test_service.py, tests/test_integration.py; scripts/e2e.ps1 y e2e.sh; README.md y docs/contracts.md. Nuevos: scripts/check_api.py, tests/test_contract_corrections.py y tests/fixtures/sample.pdf con README de reproducción. Este informe permanece sin seguimiento desde la auditoría inicial.

Repositorio y rama conservados: Lourdesrizza/pdf-api-service, main. Sin commit, push, merge ni despliegue compartido. El cambio previo del README (sección de fakes en reemplazo de instrucciones antiguas) se integró y se reparó su formato.

---

## Auditoría inicial histórica — anterior a las correcciones

Las secciones 1–11 siguientes describen el estado anterior a la implementación. Sus hallazgos y casillas pendientes no representan el estado final: consultar las actualizaciones al inicio.

## 1. Conclusión

La API tiene implementado el flujo principal con una separación de responsabilidades adecuada. Los antiguos errores de ruta de Documents, campo enviado, límite de 10 MiB, readiness del extractor y dependencias cruzadas del Compose independiente **ya están corregidos en el código revisado**. No corresponde repetirlos como defectos actuales.

La entrega todavía no puede considerarse terminada: el duplicado concurrente con HTTP 200 se anuncia como `source=extracted`; el fake de Documents no reproduce el contrato estricto ni los códigos de duplicación; la prueba live usa bytes que no constituyen un PDF procesable; faltan pruebas reales aisladas y carga simple de API. Hay inconsistencias de errores, modelos y documentación.

Resultado ejecutado: **22 tests aprobados, 1 test de integración excluido explícitamente**. Las tres configuraciones Compose validan. La imagen `pdf-api-service:audit-b8cf302` se construyó correctamente, con caché. Esto no demuestra arranque, conectividad Docker ni integración con Mongo/Extractor reales. No se calcula porcentaje de avance.

## 2. Identidad, alcance y conservación

| Dato | Verificación inicial |
|---|---|
| Raíz real | `C:\dev\pdf-proyecto\pdf-api-service` |
| Remoto fetch/push | `https://github.com/Lourdesrizza/pdf-api-service.git` |
| Rama | `main` |
| Commit | `b8cf3026c6b75982dc116b1bb4ec2f8dee8114bb` |
| Estado inicial | ` M README.md` |
| Implementación auditada | Árbol de trabajo actual de este repositorio independiente, incluido README local |
| AGENTS.md | No se encontraron en este repositorio ni en `C:\`, `C:\dev`, `C:\dev\pdf-proyecto` |

Comandos de identidad: `git rev-parse --show-toplevel`, `git remote -v`, `git branch --show-current`, `git rev-parse HEAD`, `git status --short`, `git diff -- README.md`, `git ls-files`.

No se ejecutó pull, fetch, checkout, reset, commit ni push. No se certifica igualdad con el último estado remoto de GitHub: el objeto auditado es el checkout identificado. No se usó `pdf-extractext` como implementación de la API. En el directorio padre solo se encontró este repositorio; no había repositorios hermanos de Documents, Extractor o infraestructura para contrastar su código actual.

Se revisaron todos los fuentes de `app`, tests/fakes, scripts, contratos, README, Dockerfile, los tres Compose, `.env.example`, metadatos de dependencias, `uv.lock`, archivos de exclusión y listado de archivos Git. No hay workflow CI versionado. Las referencias `archivo:línea` corresponden al árbol auditado, antes de agregar este informe.

## 3. Fuentes y reconciliación de documentos

Se leyeron completamente mediante extracción de texto de todas las páginas:

- **M**: `C:\Users\lulir\Downloads\Plan_Maestro_Microservicios_PDF_Extractext_260930_185001.pdf`: 22 páginas, Plan del 30/09/2026.
- **G**: `C:\Users\lulir\Downloads\1_5100494171915946430_261021_175241.pdf`: 14 páginas físicas, identificado por su contenido como Guía revisada del 21/10/2026. Su numeración impresa salta de 12 a 14; las referencias de esta auditoría usan páginas físicas.
- **P**: pedido de auditoría adjunto. Sus controles adicionales se distinguen de obligaciones de los PDF.

La guía G actualiza el plan M así:

1. M §6.1 sugería `/documents/checksum/{checksum}`; G pp.3–4 fija `/documents/by-checksum/{checksum}`, `content`, `page_count` y respuestas 201 nuevo / 200 existente. Un alias de la ruta antigua es opcional de Documents, no una solución necesaria de la API.
2. M §7 describía validaciones generales; G p.5 concreta 20 MiB = 20.971.520 bytes y la prueba de 279 páginas / 17.749.468 bytes. Para multipart permite documentar si el límite incluye el sobre; no exige inequívocamente un parser que limite solo el archivo.
3. G p.5 diferencia liveness y `/health/ready`, con `/ready` público 503 si una dependencia requerida no puede atender.
4. G pp.2 y 7 exige independencia del Compose de API y permite un stack separado de fakes. `depends_on` no está prohibido en tests o integración.
5. M describe separación, Traefik e integración como trabajo pendiente histórico; G pp.1 y 11 informa infraestructura/extractor conectados. Esa afirmación es antecedente, no evidencia de funcionamiento actual.
6. M §13 dejaba abierta la ubicación de Redis, con participación condicional de Lourdes. G p.11 lo sitúa como referencia del extractor y no asigna Redis a API ni Documents. `NullResultCache` no es un incumplimiento obligatorio de esta API.
7. G no define contratos de Kafka/Consul; quedan separados y pendientes de especificación, no como faltantes automáticos de Lourdes.
8. M §§1 y 12 mantiene el benchmark completo del extractor y al menos una carga simple de los otros servicios más E2E. La guía no demuestra que esos entregables estén ejecutados hoy.

Los nombres y códigos publicados deben confirmarse/versionarse con Angelina según la propia guía. Esta auditoría usa ese contrato como referencia, sin certificar el código actual de su repositorio.

## 4. Matriz de cumplimiento

Estados usados: **CV** = Cumplido y verificado; **IE** = Implementado, pendiente de verificación en ejecución; **PA** = Parcial; **NI** = No implementado; **NV** = No verificable con el entorno disponible; **NC** = No corresponde a este repositorio; **OP** = Opcional o pendiente de definición.

CV indica verificación del alcance citado: una prueba en memoria no acredita red, persistencia o procesamiento real. P0 bloquea el contrato básico/entrega; P1 completa corrección o evidencia; P2 mejora entregabilidad. En filas ya verificadas, la prioridad indica conservar/regresión.

| ID | Requisito y origen | Responsable / alcance | Estado y evidencia | Falta / criterio verificable de finalización | Prioridad |
|---|---|---|---|---|---|
| A01 | Repo independiente, M §4, G p.4 | Lourdes/API | CV: identidad Git y estructura propia | Conservar identidad; permisos de colaboradores no auditados | P1 |
| A02 | `POST /process`, G p.3, M §7 | Lourdes/API | CV local: `app/main.py:74`, tests de flujo aprobados | E2E separado en I01 | P0 |
| A03 | PDF binario/multipart `file`, G p.3 | Lourdes/API | CV local: `validation.py:35`, test parametrizado | Conservar ambos; ampliar bordes multipart | P1 |
| A04 | MIME, vacío, firma, M §7.1 | Lourdes/API | CV local: `validation.py:36–49`, 4 casos aprobados | Firma básica no demuestra PDF procesable; debe rechazarlo extractor real | P1 |
| A05 | SHA-256 sobre bytes PDF, M §7.1 | Lourdes/API | CV: `checksum.py:4`, test hashlib; orquestador recibe archivo ya separado | Añadir aserción de checksum idéntico entre modalidades y enviado a Documents | P1 |
| A06 | Consultar antes de extraer, M §7.1 | Lourdes/API | CV local: `orchestrator.py:13–17`; test existing verifica cero llamadas a extractor | Confirmar en red/logs del escenario real | P0 |
| A07 | Extraer y persistir nuevo, M §7.1 | Lourdes/API | CV con mocks: `orchestrator.py:17–18`, tests nuevo/binario/multipart | Prueba real y aserciones del payload exacto | P0 |
| A08 | Respuesta pública 5 campos, G p.3 | Lourdes/API | PA: `schemas.py:4–9`, `orchestrator.py:28`; páginas permiten null | Acordar modelo obligatorio y probar todos los campos/valores | P1 |
| A09 | Filename/default, P | Lourdes/API | IE: `validation.py:40–53`, multipart tiene precedencia, fallback `document.pdf`, máximo 255 caracteres | Tests de nombre ausente, extensión, largo y precedencia; truncar puede quitar extensión | P2 |
| A10 | No Mongo ni extracción interna/imports ajenos, M §§6–7 | Lourdes/API | CV estático: clientes HTTP; no drivers Mongo ni librería de extracción en pyproject | Conservar límites de responsabilidad | P0 |
| A11 | HTTP entre servicios / cliente gestionado, M §§7,9 | Lourdes/API | IE: `main.py:24–36`, AsyncClient compartido y cierre por contexto | Comprobar DNS/HTTP en Docker real; mocks no lo prueban | P1 |
| A12 | Timeouts/desconexiones, M §7.2 | Lourdes/API | CV local: `base.py:11–17`; tests ConnectError, ReadTimeout, RemoteProtocolError | Ampliar casos de ambos clientes, sin host interno en respuesta | P1 |
| D01 | GET canónico, G pp.3–4 | Lourdes/API | CV local: `documents.py:25`, tests usan ruta nueva | No reintroducir ruta vieja | P0 |
| D02 | POST checksum/filename/content/page_count, G pp.3–4 | Lourdes/API | CV estático: `documents.py:35` | Test del JSON exacto y rechazo de contrato viejo | P0 |
| D03 | Respuesta id/created_at/checksum/filename/content/page_count, G p.3 | Lourdes/API | PA: `schemas.py:18–29` omite created_at, permite contenido/páginas ausentes y alias antiguo | Validar mínimos acordados, rechazar respuesta malformada como 502 | P1 |
| D04 | 201 nuevo / 200 duplicado, source coherente, G pp.3–4 | Lourdes/API | PA: `documents.py:44–47` pierde código; `orchestrator.py:25` siempre extracted; reproducción confirma | Preservar resultado de creación; POST 200 => existing según semántica acordada; tests de carrera | P0 |
| D05 | 404 no existe, G p.3 | Lourdes/API | PA: `documents.py:29–30` acepta cualquier 404 | Ruta actual correcta; contrastar despliegue/contrato para no tratar ruta ausente como documento ausente | P1 |
| D06 | 409 excepcional, P/G p.10 | Lourdes/API | CV local: `orchestrator.py:19–24`, test reconsulta | Agregar conflicto sin recuperación => 502; conservar como excepción, no duplicado habitual | P1 |
| D07 | Índice único, CRUD, Mongo 7, G pp.8–10 | Angelina/Documents | NC: no hay acceso Mongo en API | Verificar en repo/DB aislada de Angelina, no implementar aquí | P1 coordinación |
| E01 | Binario `POST /extract` application/pdf, G p.3 | Lourdes/API | CV estático: `extractor.py:20–22` | Confirmar bytes y headers en prueba de contrato y red real | P0 |
| E02 | Leer content/page_count, G p.3 | Lourdes/API | PA: `extractor.py:26–34` valida tipos parcialmente, acepta 0 y bool | Entero estricto positivo coherente con Documents; inválidos => 502 sin persistencia | P1 |
| E03 | Readiness real, G p.5 | Lourdes/API | CV local: `extractor.py:15`, `documents.py:17`, tests 200/503 | Comprobar dependencia real y fallos de transporte | P1 |
| E04 | problem+json y privacidad, G p.5 | Lourdes/API | PA: parsea detail sin depender de MIME; `base.py:25–28` lo devuelve sin sanear | Prueba sintética confirma propagación de marcador sensible; filtrar detalle antes de responder | P1 |
| E05 | Mapear 400/413/415/429/503, G p.5 | Lourdes/API | PA: 400=>422; 413/415=>502; 429/503=>503 | Publicar tabla explícita y probarla; 415 actual contradice contrato escrito 422 | P1 |
| U01 | 20 MiB código/config/Compose/env/docs, G p.5 | Lourdes/API | CV estático: `config.py:10`, env y ambos Compose con límite | Conservar 20971520; suite actual usa 1024, no prueba producción por sí sola | P0 |
| U02 | Lectura por chunks y 413, G p.5 | Lourdes/API | CV local: `validation.py:5–13`; reproducción exacto binario aceptado / +1 rechazado | Aumentar cobertura de chunks múltiples y no llamar upstream al exceder | P1 |
| U03 | Alcance límite multipart, G p.5 | Lourdes/API | PA: se limita cuerpo completo en `validation.py:39` antes de parsear | Documentar alcance permitido por guía o acordar límite de archivo; prueba exacta multipart produce 413 | P1 |
| U04 | PDF real 279 páginas/17749468 bytes, G pp.5,12 | Lourdes + equipo | NV: no se encontró PDF de ese tamaño en Descargas ni fixture del repo | Conseguir fixture autorizado, comprobar hash/tamaño y page_count=279 en stack real aislado | P1 |
| H01 | /health liveness, M §11 | Lourdes/API | CV local: `main.py:58–60`, test aprobado | Arranque de contenedor pendiente | P1 |
| H02 | /ready 503 si requerida caída, G pp.5,12 | Lourdes/API | CV con mocks: `main.py:63–71`, gather sin extraer | Probar Documents/Mongo caído real en entorno dedicado | P1 |
| H03 | Healthcheck Docker, M §8/11 | Lourdes/API | IE: `Dockerfile:16` consulta /health con PORT | Comprobar healthy al ejecutar imagen aislada; liveness no acredita dependencias | P1 |
| C01 | Dockerfile propio, lock, M §§4,10 | Lourdes/API | CV build con caché: multietapa, uv locked/no-dev y usuario app | Arranque y build desde caché vacía pendientes; tags base mutables | P1 |
| C02 | URLs por entorno / DNS Docker, M §§7,9 | Lourdes/API | CV estático: `config.py:7–8`, Compose y env | Confirmar aliases vigentes con Jeremías | P1 |
| C03 | Red externa y labels, M §10 | Lourdes + Jeremías | IE: Compose base `pdf-network external`, labels TLS | Config válida no prueba red existente, router o certificados | P1 |
| C04 | Compose API independiente, G p.7 | Lourdes/API | CV estático/config: base+dev solo api, sin depends_on ajeno | Mantener separación; dev publica loopback 8002 | P0 |
| C05 | Fakes aislados, G p.7 | Lourdes/API | CV configuración: test project pdf-api-test, red propia, fake-*; depends_on apropiado aquí | Arranque no ejecutado; puerto 8002 coincide con dev, usar escenarios alternativos o parametrizar | P1 |
| C06 | Recursos / escalabilidad, M §§10,14 | Lourdes + Infra | IE: Compose base 1 CPU/512M sin container_name | Verificar recursos efectivos; no confundir con obligación de 5 réplicas de API | P1 |
| C07 | PORT configurable coherente, M §14 | Lourdes/API | PA: comando/health usan PORT; labels y puerto interno dev permanecen 8000 | Documentar PORT=8000 en Docker o interpolar destino coherentemente; probar PORT distinto | P2 |
| Q01 | Modularidad, M §§4,17 | Lourdes/API | CV estático: frontera, checksum, clientes, servicio y errores separados | Conservar; no se justifica reescritura grande | P2 |
| Q02 | Stateless, M §14 | Lourdes/API | CV estático: persistencia delegada; contador local solo backpressure | Sin límite global entre réplicas; no es almacenamiento de negocio | P1 |
| Q03 | Logs stdout, M §14 | Lourdes/API | PA literal: `main.py:20` basicConfig usa stderr, reproducción confirma | Docker captura ambos, M §10 los permite; corregir promesa stdout de README o configurar stream | P2 |
| Q04 | Errores uniformes y sin trazas, M §7 / G p.5 | Lourdes/API | PA: `errors.py` uniforma JSON y 500 genérico; detail extractor no saneado | Resolver E04; revisar logs upstream de hasta 1000 caracteres (`base.py:22`) | P1 |
| Q05 | OpenAPI y /docs, M §11 | Lourdes/API | PA: FastAPI los genera; spec comprobada omite requestBody de /process | Declarar binario, multipart/file y headers sin cambiar comportamiento; /docs debe permitir entender/enviar entrada | P1 |
| Q06 | README completo y consistente, M §§15,17, G p.6 | Lourdes/API | PA: incluye instalación, Docker, vars, endpoints, tests; bloque sin cerrar y curl malformado | Cerrar fence después de down; URL plana en comando; explicar source, límites multipart, códigos y logs | P2 |
| Q07 | Contratos sincronizados, G p.6 | Lourdes/API | PA: `docs/contracts.md:9,15,18–22`, schemas | Quitar ambigüedad histórica incompatible con acuerdo vigente; readiness y 201/200 bien definidos | P1 |
| T01 | Tests puros y funcionales, M §11 | Lourdes/API | CV en alcance: 22 aprobados usando TestClient/respx | No equivalen a servicios reales; ampliar faltantes indicados abajo | P1 |
| T02 | Fake estricto realista, G p.6 | Lourdes/API | PA: ruta/content corregidos; esquema y códigos no | extra forbid, hash válido, páginas strict >0, created_at, duplicado 200 | P0 |
| T03 | Payload extracted_text rechazado, G p.6 | Lourdes/API | IE: falta content da validación; extras se ignoran si también hay content | Test negativo del campo viejo con y sin content; ambos deben rechazarse | P1 |
| T04 | Nuevo/existente y no reextracción, G p.6 | Lourdes/API | CV local para existing y nuevo; tests no inspeccionan JSON exacto del POST | Añadir aserciones de payload, bytes, contadores y secuencia repetida | P1 |
| T05 | Integración con PDF válido, G p.6 | Lourdes/API | PA: `test_integration.py:14` usa firma + texto, solo un envío | Fixture procesable; dos envíos, ID/hash iguales y contador extractor inalterado segundo envío | P0 |
| T06 | Scripts E2E vía Traefik, M §7 | Lourdes + equipo | PA: `scripts/e2e.*` dos envíos, sin comparar IDs/hash entre respuestas | Validar status, campos, hash local, igualdad ID/checksum y ausencia de llamada extractor | P1 |
| T07 | Carga simple API, M §12 | Lourdes/API | NI: no script ni resultados versionados | Prueba limitada en entorno dedicado con req/s, errores y latencias; no golpear compartido | P1 |
| T08 | CI automatizada, P calidad | Lourdes/API | OP: no workflow versionado; PDF no impone plataforma CI | Recomendación: ejecutar tests/lock/config al cambiar contrato | P2 |
| I01 | HTTP real API→Extractor→Documents/Mongo, M §§9,16 / G p.12 | Equipo | NV: repos externos/stack real aislado no disponibles | Ejecución protegida con versiones y evidencia completa | P1 |
| I02 | Índice único concurrente / Mongo caído, G p.12 | Angelina + Lourdes + Infra | NV: solo mocks y fake en memoria disponibles | Dos POST simultáneos, un registro Mongo; API coherente; caída DB => 503 | P1 coordinación |
| I03 | Benchmark k6/Vegeta y 5 réplicas, M §§1,5,12,17 | Maite + Jeremías | NC: no es implementación de API | Verificar métricas/dataset oficial en repos correspondientes; no reasignar a Lourdes | P1 equipo |
| I04 | Redis fail-open / recuperación worker, G pp.11–12 | Extractor + Infra | NC: API consume readiness y errores | Coordinación de pruebas reales; no agregar Redis a API para completar checklist ajeno | P1 equipo |
| I05 | Consul/Kafka, M §3 / G p.11 | Equipo/profesor | OP: sin contrato aplicable de API | Definir alcance aparte antes de implementar | P2 |
| I06 | Caché en orquestador, M §13 / G p.11 | Equipo | OP: punto de extensión `cache.py`, no conectado | Solo si nueva decisión arquitectónica explícita; no es falta obligatoria actual | P2 |
| I07 | CRUD/README/URI/test DB aislada de Documents, G pp.8–10 | Angelina/Documents | NC: repositorio no disponible | Pedir evidencias/versiones de su entrega, sin modificar API para suplirlas | P1 coordinación |

## 5. Hallazgos concretos e impacto

### F01. Se pierde el resultado 200 de un alta duplicada

`DocumentClient.create()` admite 200 y 201 pero devuelve únicamente un `DocumentPayload`. `Orchestrator.process()` atribuye `extracted` a todo resultado no nulo. Reproducción en memoria con MockTransport: GET 404, extracción correcta y POST Documents 200 => **source=extracted**. Esto contradice G p.4 cuando otro request ya persistió el documento. La deduplicación de almacenamiento corresponde al índice de Documents; este fallo es de semántica pública de API. Tampoco hay exclusión por checksum en la API: dos solicitudes simultáneas pueden extraer ambas antes de persistir. No se exige inventar un bloqueo distribuido para corregir el indicador.

### F02. El fake no es una prueba fiable del contrato real

`tests/fakes/documents.py:8–12` acepta cualquier checksum, campos extra por defecto y páginas null, cero, negativas o coercibles. `:30–32` devuelve 409 al repetir y omite `created_at`. Reproducción: checksum `x`, page_count 0 y campo extra fueron aceptados; el campo extra desapareció silenciosamente; segundo create produjo 409. Ruta nueva y `content` obligatorio **sí están corregidos**. Un payload solo con extracted_text falla por ausencia de content; uno con content más extracted_text puede pasar, por lo que no hay rechazo estricto del campo obsoleto.

`tests/fakes/extractor.py:13–15` produce texto prefijado Fake extraction a partir de cualquier cuerpo; no procesa PDF ni cuenta páginas. Es válido como doble identificado, no como certificado de extracción.

### F03. La prueba de integración no acredita el flujo real

`tests/test_integration.py:14` usa `%PDF-1.4` seguido de texto arbitrario, sin estructura PDF. Solo manda una vez y comprueba status/checksum, sin Markdown, páginas, persistencia, ID estable ni no reextracción. Se habilita por existencia de dos variables, sin comprobar aislamiento de destino. No se ejecutó contra servicios reales. Los scripts E2E requieren un PDF nuevo y comprueban source, pero no comparan ambos ID/checksum; PowerShell usa curl sin `--fail`, por lo que debe validar status además de JSON. Ninguno demuestra por sí solo que el extractor no fue invocado: eso requiere contador/log o instrumentación del entorno de prueba.

### F04. Errores del extractor y confidencialidad

`base.py:20–39` dio estos resultados al invocarse con respuestas sintéticas problem+json:

| Upstream | Público actual | Observación |
|---|---:|---|
| 400 | 422 | Propaga detail literalmente; marcador sintético sensible apareció en salida |
| 413 | 502 | No hay regla específica ni test existente |
| 415 | 502 | Contradice `docs/contracts.md:9`, que anuncia 422 |
| 429 | 503 | Con Retry-After 1 fijo |
| 503 | 503 | Con Retry-After 1 fijo |

G permite contrato público propio: 413/415 no deben cambiarse por dogma, pero necesitan decisión explícita coherente, documentación y pruebas. Devolver como fallo de gateway un rechazo de tamaño sin explicación dificulta al cliente corregir la carga. `detail` puede contener información interna del upstream; el 500 propio es genérico, pero eso no cubre la propagación del 400. Los logs también registran hasta 1000 caracteres del body upstream; revisar qué puede incluir antes de prometer ausencia de datos sensibles.

### F05. El límite multipart incluye el envoltorio

La lectura por chunks corta al superar max_upload_bytes antes del parseo MIME. Prueba directa de `receive_pdf` con Request sintético: cuerpo binario de exactamente 20.971.520 bytes aceptado; el mismo archivo multipart rechazado 413; binario de 20.971.521 bytes rechazado 413. Los bytes usados solo tenían firma PDF: demuestra frontera de tamaño, **no extracción de PDF válido**. La guía pide documentar el alcance; puede bastar ese ajuste si el equipo acepta límite de cuerpo. No afirmar que hoy acepta archivos multipart de hasta 20 MiB completos. Hay copias de buffers en memoria; con concurrencia ilimitada por defecto, medir consumo antes de decidir una optimización.

No se encontró el PDF de 17.749.468 bytes al buscar PDFs en Descargas (incluyendo subdirectorios) ni en fixtures versionados. Esto no demuestra que no exista en otra carpeta de la computadora. Su aceptación y page_count=279 quedan pendientes.

### F06. Modelos permisivos pueden ocultar respuestas incompatibles

`DocumentPayload` tolera `extracted_text`, ausencia de `content` y `page_count`, ignora `created_at` y otros extras; puede convertir un documento incompleto en respuesta pública exitosa con contenido vacío y páginas null. No verifica que el checksum recibido corresponda al calculado; `_result` prefiere el checksum remoto no vacío. Esa compatibilidad histórica no está confirmada por G y contradice la frase de contratos «no hay traducción de campos». No es error enviar un campo antiguo en el POST actual: el problema está en la validación de respuesta.

`ExtractorClient` permite 0 y booleanos como page_count (`bool` es subtipo de int), mientras G p.6 exige entero positivo estricto para persistir. Una respuesta anómala puede alcanzar Documents y fallar después. Validar mínimo acordado evita trasladar el diagnóstico a otro servicio.

### F07. 404 de recurso y 404 de ruta no se distinguen

La ruta vigente es correcta. Sin embargo, cualquier 404 se interpreta como ausencia de documento. Si se configura una URL base equivocada o se despliega una versión incompatible, se extraerá innecesariamente antes del fallo de persistencia. No se puede distinguir confiablemente usando solo el código 404: hace falta acordar señal de error o validar contrato/despliegue; no inventar un formato que Angelina no publique. Readiness solo comprueba status 200 y no certifica rutas de negocio.

### F08. Entregabilidad y configuración

- OpenAPI de `/process` tiene respuestas pero no `requestBody`, porque el handler recibe Request sin declarar los dos formatos. La prueba actual solo comprueba nombres de rutas; `/docs` no describe cómo cargar el archivo.
- README local tiene un fence abierto en línea 97 sin cierre tras el comando down (línea 100); el siguiente bloque se interpreta incorrectamente. El comando de línea 99 contiene enlace Markdown en vez de URL de curl. El cambio es preexistente y no fue corregido por esta auditoría.
- `docs/contracts.md` sigue marcando contrato pendiente, menciona `/health` en vez de explicar readiness y mezcla 201/200 con el 409 histórico. El README dice stdout, pero basicConfig escribe stderr (confirmado). Docker captura ambos: es una inconsistencia menor; M §10 acepta stdout/stderr.
- PORT cambia uvicorn y healthcheck, pero labels y mapeo dev/test fijan destino 8000. Con PORT distinto, el proxy/publicación puede dejar de alcanzar la API. El default 8000 sí es coherente.
- Las imágenes base usan tags mutables; `uv.lock` y `uv --locked` estabilizan paquetes, no el sistema base completo. `tests/fakes/Dockerfile` instala FastAPI/uvicorn sin lock. Mejoras de reproducibilidad, sin justificar una reescritura.
- Ambos escenarios dev y test publican 127.0.0.1:8002. Sus redes son diferentes pero no pueden publicar ese puerto simultáneamente. Evaluar escenarios excluyentes o parametrizar; no es prueba de dependencia cruzada.

## 6. Qué conservar, qué completar y qué falta

**Conservar:** validación de frontera previa a HTTP; SHA-256 simple; separación de clientes/orquestación; cliente AsyncClient único por lifespan; timeouts y límites de conexiones; rutas/payload actuales; manejo genérico de red/timeout; búsqueda antes de extraer; health separado de readiness; no Mongo ni extracción interna; Docker con usuario no root y lock; Compose independiente con red externa y stack de fakes separado.

**Parcial:** semántica de creación/source; fake estricto; modelos de respuesta; traducción/documentación de errores; OpenAPI de entrada; scripts E2E; README y contratos; cobertura de tamaño y multipart; validación de port binding.

**Falta:** carga simple de API y una prueba automatizada completa con PDF válido, dos envíos e integración real aislada. **Falta evidencia**, sin afirmar ausencia de implementación externa, para PDF 279 páginas, persistencia Mongo, índice único concurrente, Traefik/DNS/red, arranque del contenedor, degradación de worker y Redis fail-open.

## 7. Verificaciones ejecutadas y límites de evidencia

| Comando/comprobación | Resultado real | Qué demuestra / qué no |
|---|---|---|
| Identidad Git y lectura de fuentes indicadas en §2 | Repo correcto; README modificado previamente | Identifica checkout; no asegura que sea último remoto |
| `.\.venv\Scripts\python.exe -m pytest -v -m 'not integration' -p no:cacheprovider` | Fuera del sandbox: **22 passed, 1 deselected, 1 warning**, 21,14 s | Flujos con mocks, validación básica y backpressure local; no HTTP real ni PDF procesable |
| Mismo pytest dentro del sandbox | Se detuvo sin completar, tras primer test y comienzo de TestClient | No se cuenta como aprobado; el resultado válido es la repetición autorizada externa |
| `docker compose -f docker-compose.yml config --quiet` | exit 0 |
| `docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet` | exit 0 | Los tres config validan sintaxis/modelo; no levantan servicios, no prueban DNS, recursos o Traefik |
| `docker compose -f docker-compose.test.yml config --quiet` | exit 0 |
| `docker version --format '{{.Server.Version}}'` | 29.8.2 tras autorización externa; sandbox dio permiso denegado | Motor accesible; no confirma estado de la aplicación |
| `uv lock --check --offline` | Fuera del sandbox: exit 0, 33 paquetes resueltos | Lock consistente con proyecto; no auditoría de vulnerabilidades ni instalación limpia |
| Lock check restringido inicial | Reintentos por acceso denegado a caché | No aprobado; se repitió con autorización |
| `docker build --network=none -t pdf-api-service:audit-b8cf302 .` | Falló descargando h11, DNS sin red en RUN | No prueba fallo del código: se deshabilitó red explícitamente |
| `docker build -t pdf-api-service:audit-b8cf302 .` | exit 0, imagen creada con caché | Dockerfile construye en entorno actual; no construcción limpia sin caché ni arranque de contenedor |
| Comparación importlib.metadata contra uv.lock | fastapi 0.143.1, starlette 1.8.0, httpx 0.28.1, uvicorn 0.54.0, pydantic 2.14.1, pytest 9.1.1, respx 0.23.1 coinciden | Paquetes principales de tests coinciden; no se comparó exhaustivamente cada transitiva |
| `git diff --check` inicial | Sin errores | Whitespace de cambios locales, no corrige fence Markdown |
| Python por stdin: MockTransport + Orchestrator / map_upstream_status / Request sintético + receive_pdf / modelos del fake / app.openapi | exit 0; resultados detallados F01–F08 | Reproducciones locales sin llamadas reales, sin agregar tests/código al repositorio |
| Primera variante ASGI de comprobaciones dentro del sandbox | Sin salida concluyente durante la espera | No contada como prueba; reemplazada por comprobaciones en memoria completadas |
| pypdf con Python del runtime: todas las páginas de ambos documentos | 22 y 14 páginas extraídas/leídas; primera salida interrumpida por codificación, repetición UTF-8 correcta | Requisitos textuales y tablas; no se alteraron los PDF |
| Búsqueda de fixture en repo y PDFs tamaño 17749468 en Descargas | Sin coincidencias | No acredita ausencia en toda la PC; prueba grande pendiente |

El warning de pytest es `StarletteDeprecationWarning` por uso de httpx con TestClient; no hubo fallo. No se cambió dependencia ni se instaló una librería nueva en el proyecto.

La reproducción adicional completada se lanzó con PowerShell: `@' ... '@ | .\.venv\Scripts\python.exe -u -`. Su secuencia fue: MockTransport devuelve GET 404 y POST 200 con documento; extractor local devuelve ('ok',1); se ejecuta Orchestrator.process; se invoca el mapper con códigos 400/413/415/429/503 y body problem+json; Request entrega un único chunk binario exacto, multipart exacto y binario +1; se instancia CreateDocument con hash inválido/0/extra y se llama create dos veces; se inspeccionan app.openapi y streams del logging. No se guardó un archivo de test porque el alcance autoriza únicamente este informe.

**No ejecutado:** test live, scripts E2E, carga/estrés, CRUD real, fallos de Mongo/worker, arranque de stacks ni reinicios. Las variables de servicios reales no estaban definidas en el proceso y no había stack real de pruebas protegido disponible. Que `.env` pudiera configurarse en otro entorno no autoriza a usarlo como destino seguro. No se borraron bases, contenedores o volúmenes ni se alteró infraestructura compartida. El build dejó imagen/caché local; no se desplegó.

## 8. Plan mínimo ordenado

Este plan es recomendación; **no fue implementado**. Las prioridades se asignan al estado actual, no copian automáticamente las del informe histórico.

| Prioridad | Archivo / dueño | Cambio mínimo recomendado y motivo | Prueba de aceptación |
|---|---|---|---|
| P0 | `app/clients/documents.py`, `app/services/orchestrator.py` / Lourdes | Retener si POST fue 201 o 200; definir source coherente con existencia persistida | GET404 + POST201 => extracted; GET404 + POST200 => existing; ambos mantienen ID/checksum remoto válido; 409 sigue excepcional |
| P0 | `tests/fakes/documents.py`, `tests/test_service.py` / Lourdes | Alinear esquema estricto y 201/200/404; incluir created_at | JSON canónico aceptado; extracted_text/extra/hash inválido/páginas null, bool, 0, negativas o string rechazados; duplicado mismo ID sin segundo registro |
| P0 | `tests/test_integration.py` / Lourdes | Sustituir cuerpo inválido por fixture PDF procesable; dos envíos y resguardo de entorno | PDF nuevo produce Markdown/páginas reales; segundo mismo ID/hash, existing y contador extractor sin incremento |
| P1 | `app/clients/base.py`, tests, `docs/contracts.md` / Lourdes | Acordar 413/415 y sanear detail; conservar 429/503/timeout/red | Tabla de cinco códigos probada con problem+json, JSON no esperado y texto; ninguna respuesta contiene marcador sensible |
| P1 | `app/schemas.py`, `app/clients/extractor.py`, tests / Lourdes | Validar contrato mínimo de respuesta y checksum esperado; abandonar tolerancias no acordadas | Respuestas incompletas o páginas no enteras positivas => 502 sin persistir; contenido legítimo vacío solo si contrato lo permite |
| P1 | `app/validation.py`, README, tests / Lourdes | Documentar cuerpo vs archivo o ajustar límite según acuerdo; cubrir borde real | 20971520/20971521 binario; borde multipart según contrato; varias chunks; PDF 279 real aceptado |
| P1 | `app/main.py` / Lourdes | Completar requestBody OpenAPI para ambas modalidades | Especificación muestra PDF binario y multipart file; /docs describe carga y respuestas |
| P1 | `scripts/e2e.ps1`, `scripts/e2e.sh` / Lourdes | Validar status/campos y comparar hash local e IDs/checksums | Dos respuestas correctas con evidencia de no reextracción; errores HTTP fallan claramente |
| P1 | Nuevo script de carga y README / Lourdes | Carga API simple limitada y documentada | Resultados req/s, errores y latencias en entorno exclusivo, indicando recursos/versión y distribución nuevo/repetido |
| P1 | Configuración de integración / Jeremías + equipo | Consumir versiones acordadas en stack aislado; confirmar aliases y Traefik | DNS, health/ready, E2E, Mongo 7 dedicado, carrera y degradaciones con evidencia |
| P2 | README y `docs/contracts.md` / Lourdes | Reparar fence/curl; eliminar contradicciones sobre contrato, errores, readiness y logs | Comandos copiables, Markdown correcto y ejemplos iguales a respuestas probadas |
| P2 | Compose / Lourdes + Infra | Hacer PORT coherente o fijar/documentar restricción; evitar colisión dev/test | Modo documentado alcanza API, sin doble bind de 8002 |
| P2 | Dockerfiles/dependencias / Lourdes | Evaluar digest base y lock de fakes | Build limpio reproducible con versiones registradas; no se exige reemplazar Docker actual |
| P2 | `.github/workflows` si se adopta / Lourdes | Automatizar checks existentes, sin convertir CI en requisito inventado | PR ejecuta tests aislados, lock y Compose; integración solo protegida |

## 9. Pendientes de Lourdes y coordinaciones

**Propios de Lourdes:** F01–F08 en sus archivos, fake estricto, fixture y pruebas API/E2E, evidencia del límite, OpenAPI, carga simple y documentación. Requieren cambios acotados; no migrar frameworks ni reescribir capas.

| Coordinación | Evidencia / indicio | Impacto | Responsable / acuerdo necesario |
|---|---|---|---|
| Contrato Documents | G pp.3/8 describe 200/201 y schema; repo actual no disponible | API/fake deben coincidir con versión desplegada | Angelina + Lourdes: modelos y errores versionados; no pedir renombrar ruta para fake viejo |
| MongoDB 7 e índice único | Solo antecedente de G | Persistencia/concurrencia no certificadas | Angelina + Infra: instancia/base/volumen de pruebas propios y evidencia de índice |
| DNS/URLs/Traefik | Labels en API y defaults; falta configuración real de Infra | Imagen construida puede no ser enrutable | Jeremías: hostnames, aliases, puerto, entrypoint/TLS y versión integrada |
| Extractor/Redis/worker | G informa integración previa; no hay prueba actual | Readiness y resiliencia de cadena no certificadas | Maite + Infra: errores reales y pruebas de worker/Redis aisladas; Lourdes verifica reacción API |
| Dataset grande y benchmark | Fixture no encontrado; benchmark corresponde extractor | Falta aceptación de 279 páginas y métricas del TP | Equipo facilita dataset; Maite/Infra benchmark completo, Lourdes carga simple API |

No se detectó ni se atribuye un defecto nuevo al código actual de un repositorio ajeno que no fue inspeccionado. Las coordinaciones son necesidades de evidencia y contrato, no órdenes de reimplementación para otros integrantes.

## 10. Checklist para terminar la API

- [x] Repositorio independiente identificado y código modular.
- [x] Ruta canónica y POST con content/page_count implementados.
- [x] Flujo existente evita extractor en pruebas aisladas.
- [x] Nuevo documento extrae y persiste con mocks.
- [x] Defaults 20 MiB alineados en código, env y Compose.
- [x] Health/readiness diferenciados; dependencia degradada produce 503 con mocks.
- [x] Compose independiente sin extractor real ajeno; fakes en stack separado.
- [x] Tests actuales verdes y build de imagen confirmado con caché.
- [ ] 200 duplicado/201 nuevo y source coherentes, con test de carrera.
- [ ] Fake estricto fiel al contrato, con created_at y pruebas negativas.
- [ ] Contratos de respuesta, páginas y checksum validados.
- [ ] Errores 400/413/415/429/503 acordados, probados y sin detail sensible.
- [ ] Alcance del límite multipart documentado y bordes automatizados.
- [ ] Fixture PDF válido y E2E completo, protegido contra destino compartido.
- [ ] OpenAPI describe entrada; README y contratos consistentes/copiables.
- [ ] Carga simple API documentada y medida en entorno dedicado.
- [ ] Arranque/health del contenedor verificados sin tocar el despliegue compartido.

## 11. Checklist separado de integración real

- [ ] Registrar versiones exactas de API, Documents, Extractor e infraestructura.
- [ ] Acordar ambiente, proyecto Docker, MongoDB 7 y datos exclusivos para pruebas.
- [ ] Confirmar DNS/red externa, puertos y ruta TLS a través de Traefik.
- [ ] Comprobar /health y /ready de API y /health/ready de ambas dependencias.
- [ ] PDF nuevo válido: SHA-256 local igual al devuelto, ID real, Markdown, páginas y persistencia verificados.
- [ ] PDF repetido: mismo ID y checksum, existing, sin segunda extracción.
- [ ] PDF de 279 páginas/17.749.468 bytes: no rechazo por frontera y páginas correctas.
- [ ] Mayor a 20 MiB => 413; vacío=>400, MIME incorrecto=>415.
- [ ] Solicitudes concurrentes: un documento Mongo y resultados coherentes 200/201/source.
- [ ] Mongo o dependencia no disponible: errores/readiness previstos sin afectar datos compartidos.
- [ ] Redis fail-open y recuperación de worker: evidencia a cargo de Extractor/Infra y reacción de API comprobada.
- [ ] Métricas de carga API separadas del benchmark oficial k6/Vegeta del extractor.
- [ ] Guardar comandos, respuestas, logs sanitizados y recursos efectivos para defensa oral.

La afirmación defendible hoy es: «La API ya orquesta correctamente los caminos básicos en pruebas aisladas y construye su imagen; las correcciones históricas centrales están aplicadas. Quedan ajustes concretos de contrato y pruebas antes de certificar la integración real».
