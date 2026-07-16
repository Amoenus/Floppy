
import pytest


@pytest.fixture(autouse=True)
def _yamtrack_env(monkeypatch):
    """Point every test at a fake instance; respx intercepts the requests."""
    monkeypatch.setenv("YAMTRACK_URL", "https://yamtrack.test")
    monkeypatch.setenv("YAMTRACK_TOKEN", "test-token")
    # Force a fresh client per test since the module caches one globally.
    import yamtrack_mcp.client as client_module

    client_module._client = None
    yield
    client_module._client = None


@pytest.fixture
def api_base_url():
    return "https://yamtrack.test/api/v1"
