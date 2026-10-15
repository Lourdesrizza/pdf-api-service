# Contratos entre servicios

Las respuestas 429 y 503 de cualquiera de los servicios upstream se devuelven como 503 en la API, con `Retry-After: 1`.

## Extractor (implementado por Maite)

- `GET /health` responde `{"status":"ok","service":"extractor"}`.
- `POST /extract`, `Content-Type: application/pdf`, body binario; responde `{"content":"...","page_count":N}`.
- Sus respuestas 400 (incluidos PDF inválido/protegido) se traducen a 422 públicas y se propaga `detail`. El 415 remoto se traduce a 422 si ocurre después de la validación pública.

## Document Service (PENDIENTE DE CONFIRMAR CON ANGELINA)

Contrato adaptado en `app/clients/documents.py`; confirmar rutas, nombres y códigos con Angelina antes de integrar servicios reales.

- `GET /health` responde 200 si está disponible.
- `GET /documents/checksum/{checksum}` responde 200 `{id, filename, checksum, extracted_text, created_at}` o 404.
- `POST /documents` recibe `{filename, checksum, extracted_text, page_count}` y responde 201 con el documento creado; 409 indica duplicado.
- `page_count` es opcional en las respuestas, por compatibilidad con documentos históricos.
- El adaptador traduce `extracted_text` del servicio a `content` en la API pública. La respuesta acepta el contenido bajo `extracted_text` o `content`.
- El ID se proyecta como `document_id` (string) en la API pública.

La propuesta de POST, su campo `page_count`, el `409` de unicidad, el endpoint de health y la forma del identificador requieren confirmación. El flujo reconsulta el checksum después de un `409` para resolver carreras.
