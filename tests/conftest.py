import http.server
import os
import threading
from pathlib import Path

import pytest

from zorko import Browser
from zorko.guard import Policy

PAGES = Path(__file__).parent / "pages"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(PAGES), **kw)

    def translate_path(self, path):
        p = super().translate_path(path.split("?")[0])
        if not os.path.exists(p) and os.path.exists(p + ".html"):
            return p + ".html"
        return p

    def log_message(self, *a):
        pass


@pytest.fixture(scope="session")
def site():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture()
def zhome(tmp_path, monkeypatch):
    monkeypatch.setenv("ZORKO_HOME", str(tmp_path))
    (tmp_path / "config.json").write_text('{"consent": "local"}', encoding="utf-8")
    return tmp_path


@pytest.fixture()
def browser(zhome):
    b = Browser(policy=Policy(allow_private=True), persist=False)
    b.start()
    yield b
    b.close()
