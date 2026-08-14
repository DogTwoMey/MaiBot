from types import SimpleNamespace

import pytest

from src.config.model_configs import APIProvider, ModelInfo, TaskConfig
from src.llm_models.exceptions import ModelAttemptFailed, RespNotOkException
from src.llm_models.model_client.base_client import APIResponse
from src.llm_models.utils_model import LLMOrchestrator, RequestType, TempMethodsLLMUtils
import src.llm_models.utils_model as utils_model


@pytest.mark.asyncio
async def test_content_inspection_rejection_falls_back_to_another_provider(monkeypatch) -> None:
    """内容审核拒绝应跳过同 Provider 模型，但不应跳过其它 Provider。"""

    model_names = ["qwen3.7-plus", "qwen3.7-flash", "deepseek-v4-flash"]
    models = {
        "qwen3.7-plus": ModelInfo(
            name="qwen3.7-plus",
            model_identifier="qwen3.7-plus",
            api_provider="BaiLian",
        ),
        "qwen3.7-flash": ModelInfo(
            name="qwen3.7-flash",
            model_identifier="qwen3.7-flash",
            api_provider="BaiLian",
        ),
        "deepseek-v4-flash": ModelInfo(
            name="deepseek-v4-flash",
            model_identifier="deepseek-v4-flash",
            api_provider="DeepSeek",
        ),
    }
    providers = {
        "BaiLian": APIProvider(name="BaiLian", base_url="https://example.com/v1", auth_type="none"),
        "DeepSeek": APIProvider(name="DeepSeek", base_url="https://example.com/v1", auth_type="none"),
    }
    orchestrator = object.__new__(LLMOrchestrator)
    orchestrator.task_name = "planner"
    orchestrator.request_type = "maisaka.planner"
    orchestrator.session_id = "session-test"
    orchestrator.model_for_task = TaskConfig(model_list=model_names, selection_strategy="sequential")
    orchestrator.model_usage = {name: (0, 0, 0) for name in model_names}
    selected_models: list[str] = []
    exclusion_history: list[set[str]] = []

    def fake_select_model(*, exclude_models=None, model_name=None):
        excluded = set(exclude_models or set())
        exclusion_history.append(excluded)
        selected_name = next(name for name in model_names if name not in excluded)
        selected_models.append(selected_name)
        model_info = models[selected_name]
        return model_info, providers[model_info.api_provider], SimpleNamespace()

    async def fake_attempt_request(api_provider, client, request, model_name):
        if api_provider.name == "BaiLian":
            error = RespNotOkException(
                400,
                "InternalError.Algo.DataInspectionFailed: Input text data may contain inappropriate content. "
                "code=data_inspection_failed",
            )
            raise ModelAttemptFailed("模型遇到硬错误", original_exception=error)
        return APIResponse()

    monkeypatch.setattr(orchestrator, "_select_model", fake_select_model)
    monkeypatch.setattr(orchestrator, "_build_client_request", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(orchestrator, "_attempt_request_on_model_with_timeout", fake_attempt_request)
    monkeypatch.setattr(TempMethodsLLMUtils, "get_model_info_by_name", lambda name: models[name])
    monkeypatch.setattr(utils_model, "has_request_snapshot", lambda error: True)
    monkeypatch.setattr(utils_model, "update_failed_request_attempt", lambda *args, **kwargs: None)

    result = await orchestrator._execute_request(RequestType.RESPONSE)

    assert result.model_info.name == "deepseek-v4-flash"
    assert selected_models == ["qwen3.7-plus", "deepseek-v4-flash"]
    assert exclusion_history[1] == {"qwen3.7-plus", "qwen3.7-flash"}
