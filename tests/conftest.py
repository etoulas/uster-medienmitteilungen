import os
import tempfile

import pytest


@pytest.fixture(autouse=True)
def tmp_db(monkeypatch, tmp_path):
    """Point database.DB_PATH to a temporary file for every test."""
    db_file = str(tmp_path / "test.db")
    monkeypatch.setattr("database.DB_PATH", db_file)

    import database
    database.init_db()
    return db_file


@pytest.fixture(autouse=True)
def no_llama_fallback(monkeypatch):
    """Disable the llama.cpp fallback by default so tests never hit the network."""
    monkeypatch.setenv("LLAMA_CPP_URL", "")
