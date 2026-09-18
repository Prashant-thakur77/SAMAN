"""The API can serve the built frontend itself: the single-container image runs
one process on one port, with no web server in front. Client-side routes get
the shell, files get the file, unknown API paths stay a 404, and nothing
outside the directory is ever served."""

from pathlib import Path

import pytest

from app import main


@pytest.fixture
def frontend(tmp_path: Path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>SAMAN</title>")
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log('saman')")
    (tmp_path.parent / "outside.txt").write_text("not yours")
    monkeypatch.setattr(main, "FRONTEND_DIR", tmp_path)
    return tmp_path


class TestWithoutAFrontendDirectory:
    def test_the_root_is_the_api_card(self, client):
        assert main.FRONTEND_DIR is None
        body = client.get("/").json()
        assert body["docs"] == "/api/docs"

    def test_an_unknown_path_is_a_404(self, client):
        assert client.get("/workbench").status_code == 404


class TestServingTheFrontend:
    def test_the_root_and_every_client_route_get_the_shell(self, client, frontend):
        for path in ("/", "/workbench", "/dashboard/executive", "/items/42"):
            r = client.get(path)
            assert r.status_code == 200 and "<title>SAMAN</title>" in r.text, path
        assert client.get("/workbench").headers["cache-control"] == "no-cache"

    def test_a_built_file_is_served_and_cached_for_good(self, client, frontend):
        r = client.get("/assets/app-abc123.js")
        assert r.status_code == 200 and r.text.startswith("console.log")
        assert "immutable" in r.headers["cache-control"]

    def test_unknown_api_paths_stay_a_404_not_the_shell(self, client, frontend):
        r = client.get("/api/no-such-endpoint")
        assert r.status_code == 404 and "<title>" not in r.text

    def test_the_api_still_answers(self, client, frontend):
        assert client.get("/api/health").status_code == 200

    def test_nothing_outside_the_directory_is_served(self, client, frontend):
        r = client.get("/../outside.txt")
        assert "not yours" not in r.text
        r = client.get("/assets/../../outside.txt")
        assert "not yours" not in r.text
