#!/usr/bin/env sh
set -eu
PDF_PATH=${1:?PDF required}
URL=${2:?Explicit dedicated test URL required}
CONFIRM=${3:?Pass dedicated-test-environment}
[ "$CONFIRM" = dedicated-test-environment ] || exit 2
exec python "$(dirname "$0")/check_api.py" e2e --url "$URL" --pdf "$PDF_PATH" --dedicated-test-environment
