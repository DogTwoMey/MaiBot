from unittest.mock import patch

from fastapi import Depends, FastAPI, Response
from fastapi.testclient import TestClient

from src.webui.core import auth as auth_module
from src.webui.dependencies import require_auth


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
