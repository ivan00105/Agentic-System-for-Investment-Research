import pytest
from fake_llm import FakeClient
from fastapi.testclient import TestClient
from sec_files import make_context

from research_assistant import cli
from research_assistant.api import create_app


@pytest.fixture(autouse=True)
def isolate_configuration(monkeypatch):
    """Tests use explicit doubles, never local credentials or the real data directory."""
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    for name in (
        "SEC_USER_AGENT", "RESEARCH_MODEL_PROVIDER", "RESEARCH_MODEL",
        "OPENROUTER_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL",
        "OPENAI_ORG_ID", "OPENAI_PROJECT_ID", "RESEARCH_DATA_DIR", "TIINGO_API_KEY", "PRICE_PROVIDERS",
    ):
        # Track absent keys too: load_dotenv writes directly into os.environ.
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)


@pytest.fixture
def web(tmp_path, monkeypatch):
    """The web app with a scripted model and the SEC fixtures: set `web.model` before starting a run."""
    monkeypatch.setenv("RESEARCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RESEARCH_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("RESEARCH_MODEL", "fake-model")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(cli, "sec_client", lambda: make_context(tmp_path).sec)
    monkeypatch.setattr(cli, "model_client", lambda settings: web.model)
    with TestClient(create_app(tmp_path), base_url="http://localhost:8000") as web:
        web.traces, web.model = tmp_path / "traces", FakeClient()
        yield web
