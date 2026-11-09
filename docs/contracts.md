# Contratos entre servicios

## Documents real

- `GET /documents/by-checksum/{checksum}` consulta un checksum hexadecimal de 64 caracteres.
- `POST /documents` recibe `checksum`, `filename`, `content` y `page_count`.
- Documents devuelve 201 al insertar y 200 al encontrar el checksum ya existente. Un 409 es excepcional; la API vuelve a consultar por checksum.
- La respuesta requiere `id` string no vacío, checksum coincidente, `content` string (vacía permitida) y `page_count` entero estricto positivo. `created_at` y `filename` no se requieren para construir la respuesta pública; se ignoran campos adicionales de respuesta.
- Documents inicia y verifica MongoDB durante su ciclo de vida, crea el índice único `uq_documents_checksum` y consulta Mongo en `/health/ready`.

## Extractor real

- La API llama `POST /extract` con `Content-Type: application/pdf` y el cuerpo PDF sin envoltorio.
- `content` debe ser string y `page_count` entero estricto positivo.
- Extractor 400/415 significa que el servicio rechazó el PDF y se traduce a API 422; extractor 413 se traduce a API 413; 429/503 se traduce a API 503.
- Un PDF vacío o sin firma `%PDF` se rechaza en la frontera de la API con 400 y no llama al Extractor. Un cuerpo que pasa esa validación pero no puede abrir Extractor sí llega a `/extract` y se traduce a API 422.

## Correlación, errores y límites

- Un `X-Request-ID` de hasta 128 caracteres ASCII imprimibles se conserva; si falta o no cumple el límite/alfabeto, la API genera uno. Se devuelve al cliente y se propaga en las llamadas HTTP a Extractor y Documents.
- Para un 429/503 upstream, la API reenvía `Retry-After` si es entero decimal entre 1 y 86400; ante un valor ausente o inválido usa `1`.
- Timeout upstream -> 504; conexión/protocolo o respuesta inválida -> 502. Los mensajes públicos no propagan el `detail` remoto.
- Límite de 20 MiB sobre el cuerpo completo de la solicitud, incluido el envoltorio multipart.
- `/health` es liveness de la API; `/ready` consulta `/health/ready` de Extractor y Documents.

## Resiliencia de las llamadas de procesamiento

- Documents y Extractor tienen circuitos independientes en memoria por proceso. La búsqueda y el guardado comparten el circuito de Documents. Las sondas de `/ready` consultan directamente a ambos servicios y quedan fuera de los circuitos.
- El circuito abre tras tres fallos consecutivos de operación. Cuentan los errores de transporte, los estados 408, 429 y 5xx, y las respuestas inválidas. Los demás 4xx se consideran evidencia de que la dependencia respondió y conservan su tratamiento HTTP.
- Durante 10 segundos, el circuito abierto rechaza operaciones con `503`, `upstream_unavailable` y `Retry-After` en segundos, sin llamar a la dependencia. Después admite una sola llamada de prueba. Una respuesta válida cierra el circuito. Un fallo o una cancelación de la prueba inicia otros 10 segundos de espera.
- Con el circuito cerrado, el GET por checksum admite un reintento tras 50 ms por timeout, fallo de red, error de protocolo remoto o un estado 408, 500, 502, 503 o 504 sin `Retry-After`. `DOCUMENT_TIMEOUT_SECONDS` acota ambas llamadas y la pausa. Solo se contabiliza el resultado final. Las pruebas de recuperación y los POST de extracción y guardado hacen un solo intento.

## Reproducción de integración real

El Compose aislado, proveedor de archivo de Traefik, generador de fixtures pequeños y probes están en [`integration/real-stack/`](../integration/real-stack/README.md). La guía fija los commits revisados del Extractor y Documents; las rutas de los tres checkouts son parámetros y la API se construye desde su árbol de trabajo. La ejecución no usa `pdf-network`, no publica puertos y elimina solo sus contenedores/red al terminar.

## Revalidación 04/11/2026

Extractor HEAD remoto `5f0de842ee1bcdcd23ce1383427f6b757d8882fa`; Infra `ff9223ad4640edfd3b2b3fd9b9b8549ecd097615`, red externa pdf-network, entrypoint web HTTP. Documents HEAD remoto `2e6a806b94459be5ca788bb278dc6dc03f139388`, posterior al checkout histórico `8e1214d0ec82df3806c096840e3dea12defe69d5`. Se leyó main.py/schemas.py actuales por URL fijada a commit. Mantiene rutas y estados de éxito y agrega DocumentTooLarge → 413; page_count también tiene máximo BSON entero de 64 bits.

La API exige **200** en Extractor y GET Documents; no admite 201, 202, 204, 206 o redirecciones como éxito aunque contengan JSON válido. POST Documents admite solo 200/201 y 409 para reconsulta. Un 413 de Documents se traduce a 502 sanitizado: falla la persistencia upstream, no el límite del cuerpo PDF. No se modificó esa traducción pública.

La frontera acepta binario o una única parte file. Rechaza partes adicionales/anidadas, transfer encoding, boundary ausente y cierres defectuosos con 400. 20 MiB limita el cuerpo completo, incluido multipart. Se valida Content-Length antes de leer y se cuenta lo efectivamente recibido. BODY_TIMEOUT_SECONDS=30 limita toda la recepción y produce 408 con error body_timeout. Cancelación libera la admisión. X-Request-ID se devuelve también en 500; los logs no incluyen inputs de validación, PDF, Markdown ni texto de excepciones inesperadas.

Matriz: entrada inválida 400; recepción lenta 408; carga/extractor 413 → 413; tipo de entrada 415; extractor 400/415 → 422; upstream 429/503 → 503 con Retry-After validado; timeout upstream → 504; conexión, protocolo, estado/JSON/schema/checksum inválidos y Documents 413 → 502; fallo interno → 500.

Consultar [cierre y evidencia](cierre-2026-11-04.md) para distinguir la ejecución actual de los antecedentes.
