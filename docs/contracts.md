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
- Para un 429/503 upstream, la API reenvía `Retry-After` si es entero decimal entre 1 y 86400; ante un valor ausente o inválido usa `1`. La API no reintenta llamadas upstream.
- Timeout upstream -> 504; conexión/protocolo o respuesta inválida -> 502. Los mensajes públicos no propagan el `detail` remoto.
- Límite de 20 MiB sobre el cuerpo completo de la solicitud, incluido el envoltorio multipart.
- `/health` es liveness de la API; `/ready` consulta `/health/ready` de Extractor y Documents.

## Reproducción de integración real

El Compose aislado, proveedor de archivo de Traefik, generador de fixtures pequeños y probes están en [`integration/real-stack/`](../integration/real-stack/README.md). La guía fija los commits revisados del Extractor y Documents; las rutas de los tres checkouts son parámetros y la API se construye desde su árbol de trabajo. La ejecución no usa `pdf-network`, no publica puertos y elimina solo sus contenedores/red al terminar.
