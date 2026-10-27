from http.cookies import SimpleCookie
from typing import Optional
from unittest.mock import patch

from fastapi import Depends, FastAPI, Request, Response
from fastapi.testclient import TestClient

import pytest

from src.config.config import global_config
from src.webui.app import create_app
from src.webui.core import auth as auth_module
from src.webui.dependencies import require_auth


def test_plugin_webui_routes_use_instance_cookie(monkeypatch) -> None:
    from src.webui.routers.plugin import support, webui_extensions

    async def run_inline(coroutine):
        return await coroutine

    async def empty_result(*args):
        return {"success": True, "extensions": []}

    monkeypatch.setattr(webui_extensions, "run_on_main_loop", run_inline)
    monkeypatch.setattr(webui_extensions, "_list_extensions", empty_result)
    monkeypatch.setattr(webui_extensions, "_invoke", empty_result)
    app = FastAPI()
    app.include_router(webui_extensions.router)
    other_port = 8101 if auth_module.COOKIE_NAME != "maibot_session_8101" else 8001
    with patch.object(support, "get_token_manager") as manager:
        manager.return_value.verify_cookie_token.side_effect = lambda token: token == "test-token"
        for cookie_name, expected in (
            (auth_module.COOKIE_NAME, 200),
            (auth_module.build_auth_cookie_name(other_port), 401),
            ("maibot_session", 401),
            (None, 401),
        ):
            with TestClient(app) as client:
                if cookie_name:
                    client.cookies.set(cookie_name, "test-token")
                assert client.get("/runtime/webui").status_code == expected
                assert client.post("/runtime/webui/test/page/queries/summary", json={}).status_code == expected


def test_auth_cookie_name_is_isolated_by_webui_port() -> None:
    assert auth_module.build_auth_cookie_name(8001) == "maibot_session_8001"
    assert auth_module.build_auth_cookie_name(8101) == "maibot_session_8101"


def test_auth_dependency_reads_only_current_instance_cookie() -> None:
    app = FastAPI()

    @app.get("/")
    async def protected_route(token: str = Depends(require_auth)) -> dict[str, str]:
        return {"token": token}

    other_port = 8101 if auth_module.COOKIE_NAME != "maibot_session_8101" else 8001
    current_client = TestClient(app)
    current_client.cookies.set(auth_module.COOKIE_NAME, "current-token")
    legacy_client = TestClient(app)
    legacy_client.cookies.set("maibot_session", "current-token")
    other_instance_client = TestClient(app)
    other_instance_client.cookies.set(auth_module.build_auth_cookie_name(other_port), "current-token")

    with patch.object(auth_module, "is_token_valid", side_effect=lambda token: token == "current-token"):
        current_response = current_client.get("/")
        legacy_response = legacy_client.get("/")
        other_instance_response = other_instance_client.get("/")

    assert current_response.status_code == 200
    assert current_response.json() == {"token": "current-token"}
    assert legacy_response.status_code == 401
    assert other_instance_response.status_code == 401


def test_set_and_clear_auth_cookie_use_current_instance_name() -> None:
    set_response = Response()
    clear_response = Response()

    with patch.object(auth_module, "_is_secure_environment", return_value=False):
        auth_module.set_auth_cookie(set_response, "test-token")
        auth_module.clear_auth_cookie(clear_response)

    set_cookie_header = set_response.headers["set-cookie"]
    clear_cookie_header = clear_response.headers["set-cookie"]

    assert set_cookie_header.startswith(f"{auth_module.COOKIE_NAME}=test-token;")
    assert clear_cookie_header.startswith(f'{auth_module.COOKIE_NAME}="";')
    assert "Max-Age=0" in clear_cookie_header


def test_get_auth_cookie_value_reads_current_instance_cookie() -> None:
    app = FastAPI()

    @app.get("/")
    async def read_cookie(request: Request) -> dict[str, str | None]:
        return {"token": auth_module.get_auth_cookie_value(request)}

    client = TestClient(app)
    client.cookies.set(auth_module.COOKIE_NAME, "current-token")

    assert client.get("/").json() == {"token": "current-token"}


def test_create_app_registers_dashboard_api_routes() -> None:
    app = create_app(enable_static=False)
    routes = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert ("GET", "/api/webui/auth/check") in routes
    assert ("GET", "/api/webui/plugins/config/{plugin_id}/bundle") in routes


def test_plugin_release_list_uses_current_instance_cookie(monkeypatch) -> None:
    from src.webui.routers.plugin import marketplace

    async def load_empty_catalog(*args):
        return {"success": True, "plugins": [], "releases": []}

    monkeypatch.setattr(marketplace.service, "get_detail", load_empty_catalog)
    app = FastAPI()
    app.include_router(marketplace.router)
    other_port = 8101 if auth_module.COOKIE_NAME != "maibot_session_8101" else 8001
    with patch.object(auth_module, "is_token_valid", side_effect=lambda token: token == "test-token"):
        for cookie_name, expected in (
            (auth_module.COOKIE_NAME, 200),
            (auth_module.build_auth_cookie_name(other_port), 401),
            ("maibot_session", 401),
            (None, 401),
        ):
            client = TestClient(app)
            if cookie_name:
                client.cookies.set(cookie_name, "test-token")
            assert client.get("/marketplace/test.plugin").status_code == expected


def test_plugin_install_and_market_routes_use_current_instance_cookie() -> None:
    from src.webui.routers.plugin import management, marketplace, zip_install

    app = FastAPI()
    for router in (management.router, marketplace.router, zip_install.router):
        app.include_router(router)
    paths = app.openapi()["paths"]
    for path, method in (
        ("/install", "post"),
        ("/update", "post"),
        ("/uninstall", "post"),
        ("/marketplace/source", "get"),
        ("/marketplace/source", "put"),
        ("/marketplace", "get"),
        ("/marketplace/{plugin_id}", "get"),
        ("/install-zip", "post"),
    ):
        cookies = [parameter["name"] for parameter in paths[path][method]["parameters"] if parameter["in"] == "cookie"]
        assert cookies == [auth_module.COOKIE_NAME]


@pytest.mark.parametrize(
    ("mode", "secure_cookie", "scheme", "forwarded_proto", "expected_secure"),
    [
        ("development", True, "http", None, True),
        ("production", False, "http", None, False),
        ("production", False, "https", None, False),
        ("production", False, "http", "https", False),
        ("production", True, "http", None, True),
        ("production", True, "https", None, True),
        ("production", True, "http", "https", True),
        ("development", True, "http", "https", True),
        ("development", True, "https", None, True),
        ("development", False, "http", None, False),
    ],
)
def test_cookie_security_follows_configuration(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    secure_cookie: bool,
    scheme: str,
    forwarded_proto: Optional[str],
    expected_secure: bool,
) -> None:
    monkeypatch.setattr(global_config.webui, "mode", mode)
    monkeypatch.setattr(global_config.webui, "secure_cookie", secure_cookie)
    headers = [] if forwarded_proto is None else [(b"x-forwarded-proto", forwarded_proto.encode())]
    request = Request(
        {"type": "http", "scheme": scheme, "server": ("example.com", 7999), "path": "/", "headers": headers}
    )
    response = Response()

    auth_module.set_auth_cookie(response, "test-session-token", request)
    cookie = SimpleCookie(response.headers["set-cookie"])[auth_module.COOKIE_NAME]
    assert bool(cookie["secure"]) is expected_secure
    assert cookie["httponly"]

    cleared = Response()
    auth_module.clear_auth_cookie(cleared)
    assert bool(SimpleCookie(cleared.headers["set-cookie"])[auth_module.COOKIE_NAME]["secure"]) is expected_secure


def test_unicode_password_cookie_preserves_plugin_instance_auth(monkeypatch, tmp_path):
    import json
    from src.webui.core.security import TokenManager
    from src.webui.routers.plugin import support, webui_extensions

    password = "测试日文かな-Emoji😀"
    path = tmp_path / "webui.json"
    path.write_text(json.dumps({"access_token": password, "token_source": "configured"}), encoding="utf-8")
    manager = TokenManager(path)
    assert manager.verify_token(password)
    encoded = manager.encode_cookie_token(password)
    assert encoded.isascii() and encoded != password
    assert manager.verify_cookie_token(encoded)
    assert not manager.verify_cookie_token(password)
    monkeypatch.setattr(support, "get_token_manager", lambda: manager)

    async def run_inline(coroutine):
        return await coroutine

    async def empty_result(*args):
        return {"success": True, "extensions": []}

    monkeypatch.setattr(webui_extensions, "run_on_main_loop", run_inline)
    monkeypatch.setattr(webui_extensions, "_list_extensions", empty_result)
    app = FastAPI()
    app.include_router(webui_extensions.router)
    with TestClient(app) as client:
        client.cookies.set(auth_module.COOKIE_NAME, encoded)
        assert client.get("/runtime/webui").status_code == 200
        client.cookies.clear()
        client.cookies.set("maibot_session", encoded)
        assert client.get("/runtime/webui").status_code == 401


def test_instance_cookie_name_follows_shared_http_port() -> None:
    assert auth_module.COOKIE_NAME == auth_module.build_auth_cookie_name(global_config.http.port)


def test_request_auth_reads_only_current_instance_cookie(monkeypatch):
    from types import SimpleNamespace

    manager = SimpleNamespace(verify_cookie_token=lambda token: token == "test-token")
    monkeypatch.setattr(auth_module, "get_token_manager", lambda: manager)
    other_port = 8101 if global_config.http.port != 8101 else 8001
    for name, expected in ((auth_module.COOKIE_NAME, True), (auth_module.build_auth_cookie_name(other_port), False), ("maibot_session", False)):
        request = Request({"type": "http", "headers": [(b"cookie", f"{name}=test-token".encode())]})
        assert auth_module.is_token_valid(request) is expected
