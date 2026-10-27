from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import socket

import pytest

from src.main import MainSystem, global_config


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_standalone_message_service_owns_single_listener(monkeypatch, enabled):
    from src.chat.image_system import image_cache_cleanup
    from src.files import service as file_service
    from src.emoji_system import emoji_cache_cleanup
    from src.emoji_system.emoji_manager import emoji_manager
    from src.maisaka.display.prompt_preview_logger import PromptPreviewLogger
    from src.services import image_path_maintenance_service
    from src.webui.routers import data_transfer

    monkeypatch.setattr(global_config.maim_message, "enabled", enabled)
    monkeypatch.setattr(global_config.debug, "enable_console_input", False)
    monkeypatch.setattr(PromptPreviewLogger, "start", Mock())
    monkeypatch.setattr(emoji_manager, "periodic_emoji_maintenance", AsyncMock())
    monkeypatch.setattr(emoji_cache_cleanup, "periodic_emoji_cache_cleanup", AsyncMock())
    monkeypatch.setattr(image_cache_cleanup, "periodic_image_cache_cleanup", AsyncMock())
    monkeypatch.setattr(data_transfer, "periodic_transfer_temp_cleanup", AsyncMock())
    file_cleanup = AsyncMock()
    monkeypatch.setattr(file_service, "periodic_file_cleanup", file_cleanup)
    monkeypatch.setattr(image_path_maintenance_service, "should_schedule_image_path_maintenance_background", lambda: False)

    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    listeners = []

    async def bind_listener():
        listener = socket.socket()
        listeners.append(listener)
        listener.bind(("127.0.0.1", port))
        listener.listen()

    system = MainSystem()
    system.app = SimpleNamespace(run=AsyncMock(side_effect=bind_listener))
    system.server = SimpleNamespace(run=AsyncMock(side_effect=bind_listener))
    monkeypatch.setattr(system, "_register_message_handlers", Mock())
    try:
        await system.schedule_tasks()
        file_cleanup.assert_awaited_once()
        assert len(listeners) == int(enabled)
        assert system.app.run.await_count == int(enabled)
        system.server.run.assert_not_called()
        assert system._register_message_handlers.call_count == int(enabled)
    finally:
        for listener in listeners:
            listener.close()
