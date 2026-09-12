"""Maisaka 推理引擎测试。"""

from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, Mock

import pytest

from src.common.data_models.llm_service_data_models import LLMResponseResult
from src.core.tooling import ToolExecutionContext, ToolExecutionResult, ToolInvocation, ToolSpec
from src.llm_models.model_client.base_client import GenerationAttempt, GenerationTrace
from src.llm_models.payload_content.context_item import (
    ContextItemMeta,
    ProviderActivityItem,
)
from src.llm_models.payload_content.native_tool import NativeToolCallSummary
from src.llm_models.payload_content.tool_option import ToolCall
from src.maisaka.chat_loop_service import ChatResponse, MaisakaChatLoopService
from src.maisaka.context.messages import ReferenceMessage, ReferenceMessageType
from src.maisaka.display.prompt_cli_renderer import PromptCLIVisualizer
from src.maisaka.mode_policy import is_idle_cycle_reason
from src.maisaka.monitor.events import _serialize_planner_block, _serialize_tool_results
from src.maisaka.reasoning_engine import STOP_AFTER_EXECUTION_PAUSE_REASON, MaisakaReasoningEngine


class _ToolRegistryStub:
    """按顺序返回预设工具结果。"""

    def __init__(self, results: list[ToolExecutionResult]) -> None:
        self._results = list(results)
        self.invoked_tool_names: list[str] = []

    async def list_tools(self, context: object) -> list[object]:
        del context
        return []

    async def invoke(self, invocation: ToolInvocation, context: ToolExecutionContext) -> ToolExecutionResult:
        del context
        self.invoked_tool_names.append(invocation.tool_name)
        return self._results.pop(0)


def _build_tool_engine(results: list[ToolExecutionResult]) -> tuple[MaisakaReasoningEngine, SimpleNamespace]:
    """构造仅用于工具批次测试的推理引擎。"""

    runtime = SimpleNamespace(
        _tool_registry=_ToolRegistryStub(results),
        session_id="session-test",
        chat_stream=SimpleNamespace(
            is_group_session=True,
            group_id="group-test",
            user_id="",
            platform="test",
        ),
        is_action_tool_currently_available=lambda tool_name: True,
        _update_stage_status=lambda *args, **kwargs: None,
        _reset_consecutive_wait_count=Mock(),
        _end_planner_continuation=Mock(),
        _enter_stop_state=Mock(),
        log_prefix="[test]",
    )
    engine = MaisakaReasoningEngine(runtime)
    engine._record_tool_execution_effects = AsyncMock()  # type: ignore[method-assign]
    engine._append_tool_execution_result = lambda *args, **kwargs: None  # type: ignore[method-assign]
    engine._append_tool_post_history_messages = lambda messages: None  # type: ignore[method-assign]
    return engine, runtime


@pytest.mark.asyncio
async def test_successful_stop_request_finishes_after_full_tool_batch() -> None:
    engine, runtime = _build_tool_engine(
        [
            ToolExecutionResult(
                tool_name="terminal_tool",
                success=True,
                content="已完成",
                stop_after_execution=True,
            ),
            ToolExecutionResult(
                tool_name="second_terminal_tool",
                success=True,
                content="第二个终止工具完成",
                stop_after_execution=True,
            ),
            ToolExecutionResult(tool_name="following_tool", success=True, content="后续工具完成"),
        ]
    )

    should_pause, pause_reason, _, monitor_results = await engine._handle_tool_calls(
        [
            ToolCall(call_id="call-1", func_name="terminal_tool"),
            ToolCall(call_id="call-2", func_name="second_terminal_tool"),
            ToolCall(call_id="call-3", func_name="following_tool"),
        ],
        "测试思考",
    )

    assert should_pause is True
    assert pause_reason == STOP_AFTER_EXECUTION_PAUSE_REASON
    assert runtime._tool_registry.invoked_tool_names == [
        "terminal_tool",
        "second_terminal_tool",
        "following_tool",
    ]
    assert [result["stop_after_execution"] for result in monitor_results] == [True, True, False]
    runtime._end_planner_continuation.assert_called_once_with()
    assert runtime._reset_consecutive_wait_count.call_args_list[-1].args == ("tool_stop_after_execution",)
    runtime._enter_stop_state.assert_called_once_with()

    cycle_end = engine._cycle_end_for_pause_tool(pause_reason)
    assert cycle_end.reason == "tool_stop_after_execution"
    assert is_idle_cycle_reason(cycle_end.reason) is True


@pytest.mark.asyncio
async def test_failed_stop_request_keeps_planner_running() -> None:
    engine, runtime = _build_tool_engine(
        [
            ToolExecutionResult(
                tool_name="terminal_tool",
                success=False,
                error_message="执行失败",
                stop_after_execution=True,
            ),
            ToolExecutionResult(tool_name="following_tool", success=True, content="后续工具完成"),
        ]
    )

    should_pause, pause_reason, _, _ = await engine._handle_tool_calls(
        [
            ToolCall(call_id="call-1", func_name="terminal_tool"),
            ToolCall(call_id="call-2", func_name="following_tool"),
        ],
        "测试思考",
    )

    assert should_pause is False
    assert pause_reason == ""
    assert runtime._tool_registry.invoked_tool_names == ["terminal_tool", "following_tool"]
    runtime._end_planner_continuation.assert_not_called()
    runtime._enter_stop_state.assert_not_called()


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


def test_successful_reply_is_terminal_for_current_logical_turn() -> None:
    """可见回复发送成功后，不应继续同一逻辑轮并再次调用 reply。"""

    invocation = ToolInvocation(tool_name="reply", call_id="call-reply-1")
    result = ToolExecutionResult(tool_name="reply", success=True)

    assert MaisakaReasoningEngine._is_terminal_tool_result(invocation, result)


def test_failed_reply_is_not_terminal_for_current_logical_turn() -> None:
    """reply 发送失败时仍应允许 Planner 修正参数或重试。"""

    invocation = ToolInvocation(tool_name="reply", call_id="call-reply-1")
    result = ToolExecutionResult(tool_name="reply", success=False)

    assert not MaisakaReasoningEngine._is_terminal_tool_result(invocation, result)


@pytest.mark.asyncio
async def test_handle_tool_calls_pauses_after_successful_reply() -> None:
    """真实工具执行链应在 reply 成功后立即暂停当前逻辑轮。"""

    class ReplyRegistry:
        async def list_tools(self, context: object) -> list[ToolSpec]:
            del context
            return [ToolSpec(name="reply")]

        async def invoke(self, invocation: ToolInvocation, context: object) -> ToolExecutionResult:
            del invocation, context
            return ToolExecutionResult(tool_name="reply", success=True, content="已发送")

    runtime = SimpleNamespace(
        _tool_registry=ReplyRegistry(),
        _chat_history=[],
        session_id="test-session",
        log_prefix="[测试]",
        is_action_tool_currently_available=lambda name: True,
        _update_stage_status=lambda *args, **kwargs: None,
        _reset_consecutive_wait_count=lambda reason: None,
        _end_planner_continuation=lambda: None,
        _enter_stop_state=lambda: None,
    )
    engine = MaisakaReasoningEngine(runtime)
    engine._build_tool_execution_context = lambda latest_thought: SimpleNamespace()
    engine._build_tool_availability_context = lambda: SimpleNamespace()
    engine._record_tool_execution_effects = lambda *args, **kwargs: _async_none()
    engine._append_tool_execution_result = lambda *args, **kwargs: None
    engine._append_tool_display_results = lambda **kwargs: None

    paused, tool_name, _, _ = await engine._handle_tool_calls(
        [ToolCall(call_id="call-reply-1", func_name="reply", args={})],
        "回复用户",
    )

    assert paused is True
    assert tool_name == "reply"


@pytest.mark.asyncio
async def test_handle_tool_calls_sends_only_first_reply_in_same_batch() -> None:
    """模型同批次误发多个 reply 时，只允许第一条成为可见消息。"""

    class ReplyRegistry:
        def __init__(self) -> None:
            self.reply_count = 0

        async def list_tools(self, context: object) -> list[ToolSpec]:
            del context
            return [ToolSpec(name="reply")]

        async def invoke(self, invocation: ToolInvocation, context: object) -> ToolExecutionResult:
            del invocation, context
            self.reply_count += 1
            return ToolExecutionResult(tool_name="reply", success=True, content="已发送")

    registry = ReplyRegistry()
    runtime = SimpleNamespace(
        _tool_registry=registry,
        _chat_history=[],
        session_id="test-session",
        log_prefix="[测试]",
        is_action_tool_currently_available=lambda name: True,
        _update_stage_status=lambda *args, **kwargs: None,
        _reset_consecutive_wait_count=lambda reason: None,
        _end_planner_continuation=lambda: None,
        _enter_stop_state=lambda: None,
    )
    engine = MaisakaReasoningEngine(runtime)
    engine._build_tool_execution_context = lambda latest_thought: SimpleNamespace()
    engine._build_tool_availability_context = lambda: SimpleNamespace()
    engine._record_tool_execution_effects = lambda *args, **kwargs: _async_none()
    engine._append_tool_execution_result = lambda *args, **kwargs: None
    engine._append_tool_display_results = lambda **kwargs: None

    paused, tool_name, _, _ = await engine._handle_tool_calls(
        [
            ToolCall(call_id="call-reply-1", func_name="reply", args={}),
            ToolCall(call_id="call-reply-2", func_name="reply", args={}),
        ],
        "回复用户",
    )

    assert paused is True
    assert tool_name == "reply"
    assert registry.reply_count == 1


async def _async_none() -> None:
    return None


def test_tool_stop_request_is_serialized_for_monitor() -> None:
    tools = _serialize_tool_results(
        [
            {
                "tool_call_id": "call-test",
                "tool_name": "test_tool",
                "success": True,
                "stop_after_execution": True,
            }
        ]
    )

    assert tools[0]["stop_after_execution"] is True


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
    assert generation_attempts[0].attempt_id == "planner-attempt-1"
    assert not hasattr(generation_attempts[0], "wire_response")
