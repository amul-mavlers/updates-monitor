import pytest

import feed_to_gchat


@pytest.fixture(autouse=True)
def _catalog_goes_to_tmp(tmp_path, monkeypatch):
    """Tests that run main() must not write catalog.json into the repository."""
    monkeypatch.setattr(feed_to_gchat, "CATALOG_FILE", tmp_path / "catalog.json")
