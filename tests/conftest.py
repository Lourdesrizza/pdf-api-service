import pytest


@pytest.fixture(autouse=True)
def bypass_proxies_for_local_tests(request, monkeypatch):
    if request.node.get_closest_marker("integration") is None:
        monkeypatch.setenv("no_proxy", "*")
