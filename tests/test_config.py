from pathlib import Path

from research_assistant import config


def test_data_dir_defaults_to_project_data_folder():
    assert config.data_dir() == config.PROJECT_ROOT / "data"


def test_data_dir_follows_environment_read_at_call_time(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_DATA_DIR", str(tmp_path / "elsewhere"))
    assert config.data_dir() == Path(tmp_path / "elsewhere")


def test_blank_data_dir_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("RESEARCH_DATA_DIR", "  ")
    assert config.data_dir() == config.PROJECT_ROOT / "data"
