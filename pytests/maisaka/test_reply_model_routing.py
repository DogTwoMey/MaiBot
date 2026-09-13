"""回复路由的工具声明、白名单和请求传递验证。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.chat.replyer import model_routing
from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator, MaisakaReplyContext
from src.config.config import ModelConfig
from src.config.default_model_config import create_default_model_config
from src.maisaka.builtin_tool.reply import get_tool_spec


@pytest.fixture
def routing_config(monkeypatch):
    config = create_default_model_config(ModelConfig)
    config.model_task_config.replyer.routing_prompt = "技术问题使用 DeepSeek，日常交流使用 Aliyun。"
    monkeypatch.setattr(model_routing.config_manager, "get_model_config", lambda: config)
    return config


def test_tool_schema_tracks_prompt_and_current_candidates(routing_config):
    task = routing_config.model_task_config.replyer
    schema = get_tool_spec().parameters_schema["properties"]["reply_model"]
    assert schema["enum"] == task.model_list
    assert task.routing_prompt in schema["description"]
    assert "供应商 DeepSeek" in schema["description"]
    task.model_list = [task.model_list[0]]
    assert get_tool_spec().parameters_schema["properties"]["reply_model"]["enum"] == task.model_list
    task.routing_prompt = " "
    assert "reply_model" not in get_tool_spec().parameters_schema["properties"]
    assert model_routing.resolve_reply_model({"reply_model": "old-model"}) is None


@pytest.mark.parametrize("selected", ["not-in-pool", 1, ["qwen3.7-flash"]])
def test_invalid_route_is_rejected(routing_config, selected):
    with pytest.raises(ValueError):
        model_routing.resolve_reply_model({"reply_model": selected})


@pytest.mark.asyncio
@pytest.mark.parametrize("hook_fails", [False, True])
async def test_route_reaches_request_and_does_not_leak_to_next_reply(routing_config, monkeypatch, hook_fails):
    selected = routing_config.model_task_config.replyer.model_list[-1]
    sent_models = []

    class Client:
        task_name = "replyer"

        async def generate_response_with_context(self, *, context_factory, options):
            sent_models.append(options.model_name)
            raise RuntimeError("stop after request selection")

    async def invoke_hook(_name, **kwargs):
        if hook_fails:
            raise RuntimeError("hook failed")
        return SimpleNamespace(kwargs=kwargs)

    generator = object.__new__(BaseMaisakaReplyGenerator)
    generator.express_model = Client()
    generator.request_type = "maisaka.replyer"
    monkeypatch.setattr(generator, "_build_reply_context", AsyncMock(return_value=MaisakaReplyContext()))
    monkeypatch.setattr(generator, "_resolve_session_id", lambda _: "test-session")
    monkeypatch.setattr(generator, "_build_request_messages", lambda **_: [])
    monkeypatch.setattr(generator, "_get_runtime_manager", lambda: SimpleNamespace(invoke_hook=invoke_hook))

    for args in ({"reply_model": selected}, {}):
        success, result = await generator.generate_reply_with_context(chat_history=[], reply_tool_args=args)
        assert not success
        assert "stop after request selection" in result.error_message
    assert sent_models == [selected, None]

    success, result = await generator.generate_reply_with_context(
        chat_history=[], reply_tool_args={"reply_model": "not-in-pool"}
    )
    assert not success
    assert "不在当前回复模型池" in result.error_message
    assert sent_models == [selected, None]
