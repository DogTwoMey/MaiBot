from unittest.mock import AsyncMock, Mock

import pytest

from src.maisaka.reasoning_engine import MaisakaReasoningEngine
from src.maisaka.runtime import MaisakaHeartFlowChatting


@pytest.mark.parametrize("frequency,forced,silent", [(0, False, True), (0, True, False), (0.1, False, False)])
def test_forced_turn_bypasses_zero_frequency(frequency, forced, silent):
    runtime = object.__new__(MaisakaHeartFlowChatting)
    runtime._get_effective_reply_frequency = lambda: frequency
    runtime._forced_turn_enabled = forced
    assert runtime._is_reply_frequency_silent() is silent
    runtime._clear_forced_turn_state()
    assert runtime._is_reply_frequency_silent() is (frequency == 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("arrives_during_debounce", [False, True])
async def test_turn_rechecks_silence_after_debounce(arrives_during_debounce):
    runtime = object.__new__(MaisakaHeartFlowChatting)
    runtime._get_effective_reply_frequency = lambda: 0.0
    runtime._forced_turn_enabled = False
    runtime._agent_state = runtime._STATE_STOP
    runtime._mark_message_turn_unscheduled = Mock()
    runtime._has_pending_messages = lambda: True
    message = object()
    runtime._collect_pending_messages = lambda: [message]
    runtime._update_stage_status = Mock()
    runtime._has_pending_wait_tool_call = lambda: False

    async def wait_for_message():
        if arrives_during_debounce:
            runtime._arm_forced_turn_state(message_id="at-message", reason="@消息")

    runtime._wait_for_message_quiet_period = wait_for_message
    engine = object.__new__(MaisakaReasoningEngine)
    engine._runtime = runtime
    engine._drain_ready_turn_triggers = lambda _: (True, False, False)
    engine._ingest_messages = AsyncMock()

    context = await engine._prepare_turn_start_context("message")

    assert context.silent_reply_frequency is (not arrives_during_debounce)
    assert context.trigger_message is message
    engine._ingest_messages.assert_awaited_once_with([message])
