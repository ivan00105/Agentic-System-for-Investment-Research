import pytest


@pytest.fixture(autouse=True)
def isolate_configuration(monkeypatch):
    """Tests use explicit doubles, never local credentials or the real data directory."""
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    for name in (
        "SEC_USER_AGENT", "RESEARCH_MODEL_PROVIDER", "RESEARCH_MODEL",
        "OPENROUTER_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL",
        "OPENAI_ORG_ID", "OPENAI_PROJECT_ID", "RESEARCH_DATA_DIR",
    ):
        # Track absent keys too: load_dotenv writes directly into os.environ.
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
