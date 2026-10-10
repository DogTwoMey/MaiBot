"""Maisaka 消息触发调度。"""

from typing import TYPE_CHECKING

from src.common.logger import get_logger
from src.maisaka.focus import focus_mode_manager
from src.maisaka.mode_policy import is_dynamic_reply_trigger_enabled

from .gates import DynamicReplyTurnGate, FrequencyThresholdTurnGate

if TYPE_CHECKING:
    from src.maisaka.runtime import MaisakaHeartFlowChatting

logger = get_logger("maisaka_turn_scheduler")


class MessageTurnScheduler:
    """决定外部消息何时进入 Maisaka 内部循环。"""

    def __init__(self, runtime: "MaisakaHeartFlowChatting") -> None:
        self._runtime = runtime
        self._dynamic_reply_gate = DynamicReplyTurnGate(runtime)
        self._frequency_threshold_gate = FrequencyThresholdTurnGate(runtime)

    def record_reply(self) -> None:
        """记录 Planner 实际调用了一次 reply，供动态门控统计回复次数。"""

        self._dynamic_reply_gate.record_reply()

    def schedule_message_turn(self) -> None:
        runtime = self._runtime
        if not focus_mode_manager.can_decide(
            runtime.session_id,
            is_group_chat=runtime.chat_stream.is_group_session,
        ):
            logger.debug(f"{runtime.log_prefix} 当前不在 focus 状态，跳过 Maisaka 决策调度")
            return

        if runtime._agent_state == runtime._STATE_WAIT:
            if not runtime._is_reply_frequency_silent():
                if runtime.chat_stream.is_group_session:
                    return
                logger.info(f"{runtime.log_prefix} 私聊 wait 期间收到新消息，结束等待并进入 Planner")
                runtime._enter_running_state()
            else:
                runtime._enter_stop_state()

        pending_count = runtime._get_pending_message_count()
        if pending_count <= 0:
            return

        if runtime._message_turn_scheduled:
            has_forced_trigger = runtime._has_forced_turn_trigger()
            has_queued_turn = not runtime._internal_turn_queue.empty()
            if not has_forced_trigger or has_queued_turn or runtime._agent_state == runtime._STATE_RUNNING:
                return
            logger.warning(
                f"{runtime.log_prefix} 检测到强制触发仍未被消费，"
                "但消息调度占位没有对应的待执行 turn，已释放占位并重新调度"
            )
            runtime._mark_message_turn_unscheduled()

        effective_frequency = runtime._get_effective_reply_frequency()
        formatted_frequency = f"{effective_frequency:.3f}"
        if runtime._is_reply_frequency_silent():
            logger.info(
                f"{runtime.log_prefix} 调度=静默消费 待处理={pending_count} 频率={formatted_frequency}"
            )
            runtime._enqueue_message_turn()
            return

        if runtime._has_forced_turn_trigger():
            # @ 强制触发的回复同样占用动态门控的回复额度
            self._dynamic_reply_gate.record_forced_turn(runtime.message_cache[runtime._last_processed_index :])
            logger.info(
                f"{runtime.log_prefix} 调度=强制触发 待处理={pending_count} 频率={formatted_frequency}"
            )
            runtime._enqueue_message_turn()
            return

        if runtime._idle_backoff.should_delay(pending_count):
            return

        trigger_threshold = runtime._get_message_trigger_threshold()
        schedule_detail = f"待处理={pending_count} 阈值={trigger_threshold} 频率={formatted_frequency}"
        if is_dynamic_reply_trigger_enabled():
            dynamic_result = self._dynamic_reply_gate.evaluate(
                pending_messages=runtime.message_cache[runtime._last_processed_index :],
                frequency=effective_frequency,
            )
            logger.info(
                f"{runtime.log_prefix} 回复调度 待处理={pending_count} 频率={formatted_frequency} "
                f"{dynamic_result.detail}"
            )
            if dynamic_result.should_trigger:
                runtime._enqueue_message_turn()
            return

        frequency_result = self._frequency_threshold_gate.evaluate(
            pending_count=pending_count,
            trigger_threshold=trigger_threshold,
        )
        logger.info(f"{runtime.log_prefix} 回复调度 {schedule_detail} {frequency_result.detail}")
        if frequency_result.should_trigger:
            runtime._enqueue_message_turn()
            return

        if frequency_result.decision == "delay" and frequency_result.delay_seconds is not None:
            runtime._defer_message_turn_check(frequency_result.delay_seconds)
