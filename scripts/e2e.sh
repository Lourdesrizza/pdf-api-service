#!/usr/bin/env sh
set -eu
PDF_PATH=${1:?Uso: ./scripts/e2e.sh archivo.pdf [url]}
URL=${2:-https://api.universidad.localhost/process}
FIRST=$(curl -kfsS -X POST -H 'Content-Type: application/pdf' --data-binary "@$PDF_PATH" "$URL")
printf '%s' "$FIRST" | python -c 'import json,sys; d=json.load(sys.stdin); assert d["document_id"] and d["checksum"] and d["source"] == "extracted", d'
SECOND=$(curl -kfsS -X POST -H 'Content-Type: application/pdf' --data-binary "@$PDF_PATH" "$URL")
printf '%s' "$SECOND" | python -c 'import json,sys; d=json.load(sys.stdin); assert d["source"] == "existing", d'
echo 'E2E OK: la segunda llamada reutilizó el documento.'
