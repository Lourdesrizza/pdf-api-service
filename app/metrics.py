"""Prometheus metrics for requests to the processing endpoint."""

from prometheus_client import CollectorRegistry, Counter, Histogram


class ProcessMetrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "pdf_api_process_requests_total",
            "Number of responses to POST /process.",
            ("status_code",),
            registry=self.registry,
        )
        self.duration = Histogram(
            "pdf_api_process_duration_seconds",
            "Time to produce a response to POST /process.",
            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60),
            registry=self.registry,
        )

    def observe(self, status_code: int, duration: float) -> None:
        self.requests.labels(status_code=str(status_code)).inc()
        self.duration.observe(duration)
