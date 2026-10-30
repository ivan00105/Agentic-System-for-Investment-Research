"""Project .env setup uses isolated files and never calls a provider."""

from fastapi.encoders import jsonable_encoder
import pytest

from research_assistant import api
from research_assistant.application import Application


def clean_environment(monkeypatch):
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED")
    for name in ("SEC_USER_AGENT", "RESEARCH_MODEL_PROVIDER", "RESEARCH_MODEL",
                 "OPENROUTER_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "RESEARCH_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)


def configuration(app):
    application = Application(None)
    app.state.application = application
    try:
        endpoint = next(route.endpoint for route in app.routes if route.path == "/api/config")
        return jsonable_encoder(endpoint())
    finally:
        application.close()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_project_dotenv_configures_factory_and_data_directory(tmp_path, monkeypatch, encoding):
    clean_environment(monkeypatch)
    monkeypatch.setattr(api, "PROJECT", tmp_path)
    data_dir = tmp_path / "saved data"
    (tmp_path / ".env").write_text(
        f'SEC_USER_AGENT="Fieldnote contact@example.invalid"\n'
        'RESEARCH_MODEL_PROVIDER=openrouter\n'
        'RESEARCH_MODEL="vendor/${MODEL_NAME}"\n'
        'OPENROUTER_API_KEY="secret-test-key"\n'
        f'RESEARCH_DATA_DIR="{data_dir.as_posix()}"\n', encoding=encoding
    )
    launch_dir = tmp_path / "launch"
    launch_dir.mkdir()
    (launch_dir / ".env").write_text("RESEARCH_MODEL=wrong-directory\n", encoding="utf-8")
    monkeypatch.chdir(launch_dir)
    result = configuration(api.create_app())
    assert result["sec_configured"] is True
    assert result["connections"]["model"]["configured"] is True
    assert result["connections"]["model"]["provider"] == "OpenRouter"
    assert result["model"] == "vendor/${MODEL_NAME}"  # Values are literal, not expanded.
    assert "secret-test-key" not in str(result)
    assert data_dir.is_dir()


def test_existing_environment_including_empty_value_wins(tmp_path, monkeypatch):
    clean_environment(monkeypatch)
    monkeypatch.setattr(api, "PROJECT", tmp_path)
    monkeypatch.setenv("SEC_USER_AGENT", "")
    monkeypatch.setenv("RESEARCH_MODEL", "chosen-in-environment")
    (tmp_path / ".env").write_text(
        'SEC_USER_AGENT="Fieldnote contact@example.invalid"\nRESEARCH_MODEL=from-file\n', encoding="utf-8"
    )
    result = configuration(api.create_app(tmp_path / "data"))
    assert result["sec_configured"] is False
    assert result["model"] == "chosen-in-environment"


def test_missing_dotenv_needs_no_setup(tmp_path, monkeypatch):
    clean_environment(monkeypatch)
    monkeypatch.setattr(api, "PROJECT", tmp_path)
    result = configuration(api.create_app(tmp_path / "data"))
    assert result["sec_configured"] is False
    assert result["model_configured"] is False
