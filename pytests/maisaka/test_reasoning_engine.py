"""Maisaka 推理引擎测试。"""

from types import SimpleNamespace
from typing import Optional

import pytest

from src.common.data_models.llm_service_data_models import LLMResponseResult
from src.llm_models.model_client.base_client import GenerationAttempt, GenerationTrace
from src.llm_models.payload_content.context_item import (
    ContextItemMeta,
    ProviderActivityItem,
)
from src.llm_models.payload_content.native_tool import NativeToolCallSummary
from src.maisaka.chat_loop_service import ChatResponse, MaisakaChatLoopService
from src.maisaka.context.messages import ReferenceMessage, ReferenceMessageType
from src.maisaka.display.prompt_cli_renderer import PromptCLIVisualizer
from src.maisaka.monitor.events import _serialize_planner_block
from src.maisaka.reasoning_engine import MaisakaReasoningEngine


def _build_chat_response(content: Optional[str], reasoning: str) -> ChatResponse:
    """构造仅包含 Planner 思考字段的响应。"""

    result = LLMResponseResult.from_portable_output(
        response=content or "",
        reasoning=reasoning,
    )
    return ChatResponse(
        output_items=result.output_items,
        request_messages=[],
        selected_history_count=0,
        tool_count=0,
        prompt_tokens=0,
        built_message_count=0,
        completion_tokens=0,
        total_tokens=0,
    )


@pytest.mark.parametrize(
    ("content", "reasoning", "expected"),
    [
        (" Planner 工具正文 ", " Provider 原生推理 ", "Planner 工具正文"),
        ("", " Provider 原生推理 ", ""),
        (None, " Provider 原生推理 ", ""),
        ("   ", "   ", ""),
    ],
)
def test_planner_content_does_not_fall_back_to_reasoning(
    content: Optional[str],
    reasoning: str,
    expected: str,
) -> None:
    response = _build_chat_response(content, reasoning)

    result = MaisakaReasoningEngine._get_planner_content(response)

    assert result == expected


def test_native_tool_summary_is_serialized_without_provider_state() -> None:
    summary = NativeToolCallSummary(
        tool_type="web_search",
        call_id="ws_test",
        status="completed",
        action_type="search",
        details=["查询：Responses API"],
        source_count=2,
    )

    block = _serialize_planner_block("完成", [], [summary], 10, 5, 15, 100.0)

    assert block is not None
    assert block["native_tool_calls"] == [
        {
            "tool_type": "web_search",
            "call_id": "ws_test",
            "status": "completed",
            "action_type": "search",
            "details": ["查询：Responses API"],
            "source_count": 2,
        }
    ]
    assert "provider_state" not in block


@pytest.mark.parametrize(
    "planner_content",
    [
        "让我输出分析并调用reply。",
        "I will call the reply tool now.",
        "Let me send a reply.",
    ],
)
def test_planner_reply_intent_without_tool_call_retries_once(planner_content: str) -> None:
    """Planner 明确声称调用 reply 时，应追加纠正提示并重试一次。"""

    runtime = SimpleNamespace(_chat_history=[], log_prefix="[测试]")
    engine = MaisakaReasoningEngine(runtime)
    planner_extra_lines: list[str] = []

    planner_no_tool_count, cycle_end, should_end = engine._handle_planner_no_tool_retry(
        0,
        planner_extra_lines,
        planner_content,
    )

    assert planner_no_tool_count == 1
    assert cycle_end.reason == "planner_missing_reply_tool_retry"
    assert should_end is False
    assert planner_extra_lines == ["状态：reply 工具调用缺失，已纠正并重试一次"]
    assert len(runtime._chat_history) == 1
    hint = runtime._chat_history[0]
    assert isinstance(hint, ReferenceMessage)
    assert hint.reference_type == ReferenceMessageType.PLANNER_TOOL_HINT
    assert "结构化 reply 工具调用" in hint.content


def test_planner_without_tool_intent_ends_normally() -> None:
    """普通无工具分析仍应直接结束，避免为正常沉默增加模型调用。"""

    runtime = SimpleNamespace(
        _chat_history=[],
        log_prefix="[测试]",
        _end_planner_continuation=lambda: None,
        _reset_consecutive_wait_count=lambda reason: None,
        _enter_stop_state=lambda: None,
    )
    engine = MaisakaReasoningEngine(runtime)
    planner_extra_lines: list[str] = []

    planner_no_tool_count, cycle_end, should_end = engine._handle_planner_no_tool_retry(
        0,
        planner_extra_lines,
        "当前无需调用 reply，结束本轮。",
    )

    assert planner_no_tool_count == 1
    assert cycle_end.reason == "planner_no_tool_end"
    assert should_end is True
    assert planner_extra_lines == ["状态：已结束本轮思考"]
    assert runtime._chat_history == []


@pytest.mark.asyncio
async def test_chat_loop_keeps_reasoning_separate_from_content(monkeypatch) -> None:
    """Provider 仅返回 reasoning 时，不应将其回填为 Planner 正文。"""

    class FakeLLMClient:
        async def generate_response_with_context(self, context_factory, options) -> LLMResponseResult:
            del context_factory, options
            result = LLMResponseResult.from_portable_output(
                reasoning="Provider 原生推理",
                model_name="test-model",
            )
            logical_turn_id = result.output_items[0].meta.logical_turn_id
            assert logical_turn_id is not None
            result.output_items = (
                *result.output_items,
                ProviderActivityItem(
                    meta=ContextItemMeta.create(
                        logical_turn_id=logical_turn_id,
                    ),
                    provider_type="web_search",
                    call_id="ws_test",
                    status="completed",
                    action_type="search",
                    details=("查询：Responses API",),
                ),
            )
            result.generation_trace = GenerationTrace(
                provider="test-provider",
                endpoint="responses",
                model="test-model",
                response_id="resp_test",
                status="completed",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                prompt_cache_hit_tokens=0,
                prompt_cache_miss_tokens=0,
                output_item_ids=tuple(item.meta.item_id for item in result.output_items),
            )
            result.provider_response = {
                "id": "resp_test",
                "status": "completed",
                "output": [
                    {
                        "type": "reasoning",
                        "id": "rs_test",
                        "summary": [{"type": "summary_text", "text": "Provider 原生推理"}],
                    },
                    {
                        "type": "web_search_call",
                        "id": "ws_test",
                        "status": "completed",
                        "action": {"type": "search", "queries": ["Responses API"]},
                    },
                ],
            }
            result.generation_attempts = (
                GenerationAttempt(
                    attempt_id="planner-attempt-1",
                    workflow_purpose="planner",
                    workflow_attempt=1,
                    provider_attempt=1,
                    model_attempt=1,
                    status="succeeded",
                    started_at="2026-08-05T00:00:00.000",
                    duration_ms=1.0,
                    provider="test-provider",
                    endpoint="responses",
                    model="test-model",
                    client_type="openai_responses",
                    operation="response",
                    wire_protocol="responses",
                    request_items=(),
                    tool_definitions=(),
                    request_parameters={},
                    wire_response=result.provider_response,
                    output_items=result.output_items,
                    trace=result.generation_trace,
                ),
            )
            return result

    class PassthroughRuntimeManager:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        async def invoke_hook(self, hook_name: str, **kwargs: object) -> SimpleNamespace:
            self.calls.append((hook_name, kwargs))
            return SimpleNamespace(kwargs=kwargs)

    runtime_manager = PassthroughRuntimeManager()
    service = MaisakaChatLoopService(chat_system_prompt="测试系统提示词")
    monkeypatch.setattr(service, "_get_llm_chat_client", lambda request_kind: FakeLLMClient())
    monkeypatch.setattr(
        MaisakaChatLoopService,
        "_get_runtime_manager",
        staticmethod(lambda: runtime_manager),
    )
    prompt_preview_kwargs: dict[str, object] = {}

    def build_prompt_section_result(*args: object, **kwargs: object) -> SimpleNamespace:
        del args
        prompt_preview_kwargs.update(kwargs)
        return SimpleNamespace(
            panel=None,
            preview_access=SimpleNamespace(preview_web_uri=""),
        )

    monkeypatch.setattr(
        PromptCLIVisualizer,
        "build_prompt_section_result",
        build_prompt_section_result,
    )

    response = await service.chat_loop_step([])

    after_response_kwargs = next(
        kwargs for hook_name, kwargs in runtime_manager.calls if hook_name == "maisaka.planner.after_response"
    )
    assert len(after_response_kwargs["output_items"]) == 2
    assert response.content is None
    assert all(message.content == "" for message in response.raw_messages)
    assert response.reasoning == "Provider 原生推理"
    assert response.native_tool_calls[0].call_id == "ws_test"
    assert all(not hasattr(message, "native_tool_calls") for message in response.raw_messages)
    preview_output_items = prompt_preview_kwargs["output_items"]
    assert isinstance(preview_output_items, tuple)
    assert len(preview_output_items) == 2
    assert preview_output_items[0].__class__.__name__ == "ReasoningItem"
    assert preview_output_items[1].__class__.__name__ == "ProviderActivityItem"
    generation_attempts = prompt_preview_kwargs["generation_attempts"]
    assert isinstance(generation_attempts, tuple)
    assert generation_attempts[0].wire_response == {
        "id": "resp_test",
        "status": "completed",
        "output": [
            {
                "type": "reasoning",
                "id": "rs_test",
                "summary": [{"type": "summary_text", "text": "Provider 原生推理"}],
            },
            {
                "type": "web_search_call",
                "id": "ws_test",
                "status": "completed",
                "action": {"type": "search", "queries": ["Responses API"]},
            },
        ],
    }
