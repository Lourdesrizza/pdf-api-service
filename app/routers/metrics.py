"""Protected endpoint for Prometheus to scrape."""

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_PLAIN_0_0_4, generate_latest

from app.auth import require_bearer_token
from app.errors import APIError

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    process_metrics = request.app.state.process_metrics
    if process_metrics is None:
        raise APIError(404, "not_found", "No se encontró el recurso.")

    expected_token = request.app.state.settings.metrics_api_token.get_secret_value()
    require_bearer_token(request, expected_token)
    return Response(
        content=generate_latest(process_metrics.registry),
        headers={"Content-Type": CONTENT_TYPE_PLAIN_0_0_4, "Cache-Control": "no-store"},
    )
