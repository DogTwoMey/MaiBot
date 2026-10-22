"""零频率下的显式回复触发测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import asyncio
import pytest

from src.maisaka.reasoning_engine import MaisakaReasoningEngine
from src.maisaka.runtime import MaisakaHeartFlowChatting
from src.maisaka.turn_trigger.scheduler import MessageTurnScheduler


def _runtime() -> MaisakaHeartFlowChatting:
    """构造无网络和数据库依赖的调度运行时。"""
    runtime = object.__new__(MaisakaHeartFlowChatting)
    runtime.log_prefix = "[测试群]"
    runtime.session_id = "forced-reply-test"
    runtime.chat_stream = SimpleNamespace(is_group_session=True)
    runtime._get_effective_reply_frequency = lambda: 0.0
    runtime._forced_turn_enabled = False
    runtime._forced_turn_message_id = ""
    runtime._forced_turn_reason = ""
    runtime._forced_reply_continuation_active = False
    runtime._agent_state = runtime._STATE_STOP
    runtime._internal_turn_queue = asyncio.Queue()
    runtime.message_cache = []
    runtime._last_processed_index = 0
    runtime._message_turn_scheduled = False
    runtime._deferred_message_turn_task = None
    runtime._consecutive_wait_count = 0
    runtime._wait_timeout_task = None
    return runtime


@pytest.mark.parametrize("reason", ["@消息", "提及消息"])
def test_forced_trigger_bypasses_zero_frequency(reason: str) -> None:
    runtime = _runtime()
    assert runtime._is_reply_frequency_silent()
    runtime._arm_forced_turn_state(message_id="at-1", reason=reason)
    assert not runtime._is_reply_frequency_silent()


def test_forced_turn_keeps_wait_continuation_until_stop() -> None:
    runtime = _runtime()
    runtime._arm_forced_turn_state(message_id="at-1", reason="@消息")
    assert runtime._consume_forced_turn_reason()
    assert not runtime._has_forced_turn_trigger()
    runtime._agent_state = runtime._STATE_WAIT
    assert not runtime._is_reply_frequency_silent()
    runtime._enter_running_state()
    assert not runtime._is_reply_frequency_silent()
    runtime._enter_stop_state()
    assert runtime._is_reply_frequency_silent()


def test_zero_frequency_without_forced_trigger_stays_silent() -> None:
    runtime = _runtime()
    runtime._agent_state = runtime._STATE_WAIT
    assert runtime._is_reply_frequency_silent()
    runtime._enter_running_state()
    assert runtime._is_reply_frequency_silent()


def test_scheduler_queues_forced_reply_at_zero_frequency(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime()
    runtime._arm_forced_turn_state(message_id="at-1", reason="@消息")
    runtime._get_pending_message_count = lambda: 1
    runtime._get_message_quiet_period_remaining_seconds = lambda: 0.0
    log = Mock()
    monkeypatch.setattr("src.maisaka.turn_trigger.scheduler.logger", log)
    MessageTurnScheduler(runtime).schedule_message_turn()
    assert runtime._internal_turn_queue.get_nowait() == "message"
    assert "强制触发" in log.info.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("during_debounce", [False, True])
async def test_engine_enters_planner_for_forced_message(during_debounce: bool) -> None:
    runtime = _runtime()
    message = SimpleNamespace(message_id="at-1")
    runtime._has_pending_messages = lambda: True
    runtime._collect_pending_messages = lambda: [message]
    runtime._has_pending_wait_tool_call = lambda: False
    runtime._update_stage_status = Mock()
    runtime._chat_history = []
    if not during_debounce:
        runtime._arm_forced_turn_state(message_id="at-1", reason="@消息")

    async def quiet_period() -> None:
        if during_debounce:
            runtime._arm_forced_turn_state(message_id="at-1", reason="@消息")

    runtime._wait_for_message_quiet_period = quiet_period
    engine = MaisakaReasoningEngine(runtime)
    engine._ingest_messages = AsyncMock()
    context = await engine._prepare_turn_start_context("message")
    assert context.trigger_message is message
    assert not context.silent_reply_frequency
