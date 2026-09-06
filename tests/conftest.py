"""Shared fixtures. Nothing in the default test run touches the network."""

from __future__ import annotations

import json
import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text())


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text()


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Keep tests out of the user's real HTTP cache."""
    monkeypatch.setenv("AURORAFOX_CACHE_DIR", str(tmp_path / "cache"))
