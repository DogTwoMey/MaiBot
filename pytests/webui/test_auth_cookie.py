from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
import pytest

from src.host.authentication import HostCredentials
from src.host.proxy import BotProxy, register_bot_proxy
from src.host.sessions import HostSessions
from src.host.webui_auth import register_host_auth


@pytest.mark.parametrize("secure", [False, True])
def test_host_cookie_isolation_and_plugin_proxy(tmp_path, monkeypatch, secure):
    credentials = HostCredentials(tmp_path / "webui.json")
    credentials.update("固定Password!123")
    sessions = HostSessions(tmp_path, credentials=credentials, secure_cookie=secure)
    other = HostSessions(tmp_path / "other", credentials=credentials)
    assert other.cookie_name != sessions.cookie_name
    proxy = BotProxy(SimpleNamespace(), sessions)
    forward = AsyncMock(return_value=Response("ok"))
    monkeypatch.setattr(proxy, "_forward_http", forward)
    app = FastAPI()
    register_bot_proxy(app, proxy, management=True)
    def require_session(request: Request):
        proxy._require_session(request)
    register_host_auth(app, sessions, credentials, require_session, lambda request: "127.0.0.1")
    token = sessions.create_session()
    paths = ["api/webui/plugins/config/test/widgets", "api/webui/plugins/runtime/webui",
             "api/webui/plugins/install", "api/webui/plugins/market"]
    for cookie, expected in [(sessions.cookie_name, 200), (other.cookie_name, 401), ("maibot_session", 401)]:
        with TestClient(app, base_url="https://testserver") as client:
            client.cookies.set(cookie, token)
            for path in paths:
                url = f"/api/host/bots/{'a' * 32}/proxy/{path}"
                assert client.get(url).status_code == expected
                assert client.post(url, json={}).status_code == expected
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post("/api/webui/auth/verify", json={"token": credentials.token})
        assert response.json()["valid"]
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie
        assert ("Secure" in cookie) == secure
        session = client.cookies.get(sessions.cookie_name)
        assert session != credentials.token
        assert client.get("/api/webui/auth/check").json()["authenticated"]
        restored = HostSessions(tmp_path, credentials=HostCredentials(credentials.path))
        assert restored.valid(session)
        assert client.post("/api/webui/auth/logout").status_code == 200
        assert not sessions.valid(session)
        assert not client.get("/api/webui/auth/check").json()["authenticated"]


def test_host_statistics_report_requires_session(tmp_path):
    import asyncio
    from src.host.config import HostConfig
    from src.host.webui import create_host_app

    credentials = HostCredentials(tmp_path / "webui.json")
    sessions = HostSessions(tmp_path, credentials=credentials)
    workspace = SimpleNamespace(root=tmp_path)
    supervisor = SimpleNamespace(workspace=workspace)
    app = create_host_app(supervisor, SimpleNamespace(supervisor=supervisor), sessions, credentials, asyncio.Event(), config=HostConfig())
    with TestClient(app) as client:
        assert client.get("/maibot_statistics.html").status_code == 401
        client.cookies.set(sessions.cookie_name, sessions.create_session())
        assert client.get("/maibot_statistics.html").status_code == 404
        (tmp_path / "maibot_statistics.html").write_text("<h1>Statistics</h1>")
        response = client.get("/maibot_statistics.html")
        assert response.status_code == 200
        assert response.text == "<h1>Statistics</h1>"
        assert response.headers["x-robots-tag"] == "noindex, nofollow"
