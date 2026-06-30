from types import SimpleNamespace

import pytest

from src.config.config import global_config
from src.core.tooling import ToolAvailabilityContext, ToolInvocation

import src.maisaka.turn_scheduler as turn_scheduler_module
from src.maisaka.builtin_tool import get_builtin_tools
from src.maisaka.builtin_tool.context import BuiltinToolRuntimeContext
from src.maisaka.builtin_tool.wait import handle_tool as handle_wait_tool
from src.maisaka.context.messages import ReferenceMessage, ReferenceMessageType
from src.maisaka.mode_policy import is_idle_cycle_reason, is_reply_necessity_trigger_enabled
from src.maisaka.reasoning_engine import MaisakaReasoningEngine
from src.maisaka.turn_scheduler import MessageTurnScheduler


def _tool_names(tool_definitions: list[dict]) -> set[str]:
    return {
        str(tool_definition.get("name") or "").strip()
        for tool_definition in tool_definitions
        if str(tool_definition.get("name") or "").strip()
    }


def _availability_context() -> ToolAvailabilityContext:
    return ToolAvailabilityContext(
        session_id="session-1",
        stream_id="session-1",
        is_group_chat=True,
    )


def test_planner_exposes_wait_without_no_action_or_finish() -> None:
    tool_names = _tool_names(get_builtin_tools(_availability_context()))

    assert "wait" in tool_names
    assert "finish" not in tool_names
    assert "no_action" not in tool_names


def test_planner_no_tool_ends_cycle() -> None:
    class DummyRuntime:
        log_prefix = "[test]"

        def __init__(self) -> None:
            self._chat_history = []
            self.ended = False
            self.stopped = False
            self.wait_reset_reason = ""

        def _end_planner_continuation(self) -> None:
            self.ended = True

        def _reset_consecutive_wait_count(self, reason: str) -> None:
            self.wait_reset_reason = reason

        def _enter_stop_state(self) -> None:
            self.stopped = True

    runtime = DummyRuntime()
    engine = MaisakaReasoningEngine.__new__(MaisakaReasoningEngine)
    engine._runtime = runtime
    planner_extra_lines: list[str] = []

    count, cycle_end, should_end = engine._handle_planner_no_tool_retry(
        0,
        planner_extra_lines,
    )

    assert count == 1
    assert cycle_end.reason == "planner_no_tool_end"
    assert is_idle_cycle_reason(cycle_end.reason)
    assert "结束" in cycle_end.detail
    assert planner_extra_lines == ["状态：未调用工具，已结束本轮思考"]
    assert should_end is True
    assert runtime.ended is True
    assert runtime.stopped is True
    assert runtime.wait_reset_reason == "planner_no_tool_end"


def test_planner_no_tool_with_reply_intent_retries_once() -> None:
    class DummyRuntime:
        log_prefix = "[test]"

        def __init__(self) -> None:
            self._chat_history = []
            self.ended = False
            self.stopped = False
            self.wait_reset_reason = ""

        def _end_planner_continuation(self) -> None:
            self.ended = True

        def _reset_consecutive_wait_count(self, reason: str) -> None:
            self.wait_reset_reason = reason

        def _enter_stop_state(self) -> None:
            self.stopped = True

    runtime = DummyRuntime()
    engine = MaisakaReasoningEngine.__new__(MaisakaReasoningEngine)
    engine._runtime = runtime
    planner_extra_lines: list[str] = []

    count, cycle_end, should_end = engine._handle_planner_no_tool_retry(
        0,
        planner_extra_lines,
        '兔兔在撒娇，我需要接住她的情绪。立即回复她。',
    )

    assert count == 1
    assert cycle_end.reason == "planner_no_tool_retry"
    assert should_end is False
    assert runtime.ended is False
    assert runtime.stopped is False
    assert runtime.wait_reset_reason == ""
    assert planner_extra_lines == ["状态：未调用工具但检测到回复意图，已追加工具提示并重试"]
    assert len(runtime._chat_history) == 1
    hint_message = runtime._chat_history[0]
    assert isinstance(hint_message, ReferenceMessage)
    assert hint_message.reference_type == ReferenceMessageType.PLANNER_TOOL_HINT
    assert "reply" in hint_message.content
    assert "msg_id" in hint_message.content


def test_planner_no_tool_reply_intent_retry_has_single_attempt_limit() -> None:
    class DummyRuntime:
        log_prefix = "[test]"

        def __init__(self) -> None:
            self._chat_history = []
            self.ended = False
            self.stopped = False
            self.wait_reset_reason = ""

        def _end_planner_continuation(self) -> None:
            self.ended = True

        def _reset_consecutive_wait_count(self, reason: str) -> None:
            self.wait_reset_reason = reason

        def _enter_stop_state(self) -> None:
            self.stopped = True

    runtime = DummyRuntime()
    engine = MaisakaReasoningEngine.__new__(MaisakaReasoningEngine)
    engine._runtime = runtime
    planner_extra_lines: list[str] = []

    count, cycle_end, should_end = engine._handle_planner_no_tool_retry(
        1,
        planner_extra_lines,
        "还是需要回复她。",
    )

    assert count == 2
    assert cycle_end.reason == "planner_no_tool_end"
    assert should_end is True
    assert runtime.ended is True
    assert runtime.stopped is True
    assert runtime.wait_reset_reason == "planner_no_tool_end"
    assert runtime._chat_history == []


def test_reply_necessity_trigger_is_optional(monkeypatch) -> None:
    monkeypatch.setattr(global_config.chat.reply_timing, "reply_trigger_mode", "frequency")

    assert is_reply_necessity_trigger_enabled() is False

    monkeypatch.setattr(global_config.chat.reply_timing, "reply_trigger_mode", "reply_necessity")

    assert is_reply_necessity_trigger_enabled() is True


def test_wait_completed_message_includes_elapsed_seconds() -> None:
    class DummyRuntime:
        def _consume_pending_wait_state(self):
            return "wait-1", 3.2, 10.0

    engine = MaisakaReasoningEngine.__new__(MaisakaReasoningEngine)
    engine._runtime = DummyRuntime()

    message = engine._build_wait_completed_message(has_new_messages=True)

    assert message.tool_call_id == "wait-1"
    assert message.tool_name == "wait"
    assert "实际等待 3.2 秒" in message.content
    assert "原计划等待 10.0 秒" in message.content


def test_private_chat_message_breaks_wait(monkeypatch) -> None:
    monkeypatch.setattr(turn_scheduler_module.focus_mode_manager, "can_decide", lambda *args, **kwargs: True)
    monkeypatch.setattr(turn_scheduler_module, "is_reply_necessity_trigger_enabled", lambda: False)

    class DummyIdleBackoff:
        @staticmethod
        def should_delay(pending_count: int) -> bool:
            del pending_count
            return False

    class DummyRuntime:
        _STATE_WAIT = "wait"
        _STATE_RUNNING = "running"

        def __init__(self, *, is_group_session: bool) -> None:
            self.session_id = "session-1"
            self.chat_stream = SimpleNamespace(is_group_session=is_group_session)
            self.log_prefix = "[test]"
            self._agent_state = self._STATE_WAIT
            self._message_turn_scheduled = False
            self._idle_backoff = DummyIdleBackoff()
            self.enqueued = False

        @staticmethod
        def _is_reply_frequency_silent() -> bool:
            return False

        def _enter_running_state(self) -> None:
            self._agent_state = self._STATE_RUNNING

        @staticmethod
        def _get_pending_message_count() -> int:
            return 1

        @staticmethod
        def _get_effective_reply_frequency() -> float:
            return 1.0

        @staticmethod
        def _format_reply_frequency_for_display(value: float) -> str:
            return str(value)

        @staticmethod
        def _has_forced_turn_trigger() -> bool:
            return False

        @staticmethod
        def _get_message_trigger_threshold() -> int:
            return 1

        def _enqueue_message_turn(self) -> None:
            self.enqueued = True
            self._message_turn_scheduled = True

    private_runtime = DummyRuntime(is_group_session=False)
    MessageTurnScheduler(private_runtime).schedule_message_turn()

    assert private_runtime._agent_state == private_runtime._STATE_RUNNING
    assert private_runtime.enqueued is True

    group_runtime = DummyRuntime(is_group_session=True)
    MessageTurnScheduler(group_runtime).schedule_message_turn()

    assert group_runtime._agent_state == group_runtime._STATE_WAIT
    assert group_runtime.enqueued is False


def test_forced_turn_recovers_stale_scheduled_flag(monkeypatch) -> None:
    monkeypatch.setattr(turn_scheduler_module.focus_mode_manager, "can_decide", lambda *args, **kwargs: True)

    class DummyQueue:
        @staticmethod
        def empty() -> bool:
            return True

    class DummyRuntime:
        _STATE_WAIT = "wait"
        _STATE_STOP = "stop"
        _STATE_RUNNING = "running"
        log_prefix = "[test]"
        session_id = "session-1"
        chat_stream = SimpleNamespace(is_group_session=True)
        message_cache = [object()]
        _last_processed_index = 0
        _internal_turn_queue = DummyQueue()

        def __init__(self) -> None:
            self._agent_state = self._STATE_STOP
            self._message_turn_scheduled = True
            self.unscheduled = False
            self.enqueued = False

        @staticmethod
        def _is_reply_frequency_silent() -> bool:
            return False

        @staticmethod
        def _get_pending_message_count() -> int:
            return 1

        @staticmethod
        def _has_forced_turn_trigger() -> bool:
            return True

        @staticmethod
        def _get_effective_reply_frequency() -> float:
            return 1.0

        @staticmethod
        def _format_reply_frequency_for_display(value: float) -> str:
            return str(value)

        def _mark_message_turn_unscheduled(self) -> None:
            self.unscheduled = True
            self._message_turn_scheduled = False

        def _enqueue_message_turn(self) -> None:
            self.enqueued = True
            self._message_turn_scheduled = True

    runtime = DummyRuntime()
    MessageTurnScheduler(runtime).schedule_message_turn()

    assert runtime.unscheduled is True
    assert runtime.enqueued is True
    assert runtime._message_turn_scheduled is True


@pytest.mark.asyncio
async def test_wait_tool_rejects_after_consecutive_limit(monkeypatch) -> None:
    monkeypatch.setattr(global_config.chat.reply_timing, "max_consecutive_wait_count", 5, raising=False)

    class DummyRuntime:
        def __init__(self) -> None:
            self.count = 0

        def _try_enter_wait_state(self, seconds=None, tool_call_id=None):
            del seconds, tool_call_id
            max_count = int(global_config.chat.reply_timing.max_consecutive_wait_count)
            if self.count >= max_count:
                return False, self.count, max_count
            self.count += 1
            return True, self.count, max_count

    tool_ctx = BuiltinToolRuntimeContext.__new__(BuiltinToolRuntimeContext)
    tool_ctx.runtime = DummyRuntime()
    invocation = ToolInvocation(tool_name="wait", arguments={"seconds": 1}, call_id="wait-1")

    for _ in range(5):
        result = await handle_wait_tool(tool_ctx, invocation)
        assert result.success is True
        assert result.metadata.get("pause_execution") is True

    result = await handle_wait_tool(tool_ctx, invocation)

    assert result.success is True
    assert result.metadata.get("pause_execution") is True
    assert result.metadata.get("wait_limit_reached") is True
    assert result.metadata.get("wait_rest") is True
    assert result.metadata.get("consecutive_wait_count") == 5
