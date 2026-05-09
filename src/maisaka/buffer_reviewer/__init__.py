"""消息缓冲浏览子代理模块

职责：Planner 内循环每轮入口被调用，若期间积累了一批新消息（通过 `pending_count`
传入），决定是否要额外跑一个轻量子代理，对这批消息做"快速浏览 + 要点摘要"，
把摘要作为 reminder 注入到即将开始的 Planner 请求 prompt 中。

本模块不负责把新消息 ingest 进 `chat_history`——这部分由 `reasoning_engine`
在 round 入口统一处理，保持职责清晰。reviewer 只关心"要不要额外生成摘要"。

触发门槛由 `global_config.chat.buffer_review_threshold` 控制：
- 0: 完全禁用浏览子代理
- N > 0: 单轮积压达到 N 条才跑子代理（低于则直接靠下一轮 Planner 自行消化）

本文件为本地 fork 专属改动，集中承载新增逻辑，方便后续 upstream 合并。
"""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING, Optional

from src.common.logger import get_logger
from src.config import config as config_module

if TYPE_CHECKING:
    from src.maisaka.runtime import MaisakaRuntime

logger = get_logger("maisaka_buffer_reviewer")

_SYSTEM_PROMPT = (
    "你是一个消息浏览助理。请快速浏览最近上下文中刚刚出现的若干条新消息，"
    "用简短中文提炼要点：\n"
    "1) 哪些发言者在说话、分别说了什么关键内容；\n"
    "2) 是否有需要立即回应的指向、问题或话题；\n"
    "3) 若存在与我（机器人）相关的内容，突出显示。\n"
    "只输出要点摘要，不要开场白，不要复述原文，控制在 120 字以内。"
)

_REMINDER_HEADER = "【缓冲区消息要点提示（自上次决策以来的新消息）】\n"


class BufferedMessageReviewer:
    """Planner round 入口调用的浏览决策器。

    无状态（水位线由 runtime 的 `_last_processed_index` 统一维护）。
    为了便于后续扩展（如节流、缓存最近一次摘要），保留类的形式。
    """

    def __init__(self, runtime: "MaisakaRuntime") -> None:
        self._runtime = runtime

    def _threshold(self) -> int:
        raw = getattr(config_module.global_config.chat, "buffer_review_threshold", 0)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return 0
        return max(0, value)

    async def review_if_needed(
        self,
        *,
        pending_count: int,
        round_index: int,
    ) -> Optional[str]:
        """决定是否调用浏览子代理并返回要注入 Planner 的 reminder 文本。

        - 阈值为 0，直接跳过（功能关闭）。
        - 积压 < 阈值，直接跳过（让下一轮 Planner 自行消化即可）。
        - 否则跑一次子代理，返回前缀加"【缓冲区消息要点提示…】"的摘要；
          子代理失败或返回空则返回 None，上层按无摘要处理。
        """

        threshold = self._threshold()
        if threshold <= 0 or pending_count < threshold:
            return None

        try:
            response = await self._runtime.run_sub_agent(
                context_message_limit=20,
                system_prompt=_SYSTEM_PROMPT,
                request_kind="buffer_review",
                max_tokens=256,
                model_task_name="planner",
            )
        except Exception as exc:
            logger.warning(
                f"{self._runtime.log_prefix} [buffer_reviewer] 子代理执行异常，降级为无摘要; "
                f"积压消息={pending_count} 轮次={round_index + 1} 异常={exc}"
            )
            logger.debug(traceback.format_exc())
            return None

        summary = (response.content or "").strip() if response is not None else ""
        if not summary:
            logger.info(
                f"{self._runtime.log_prefix} [buffer_reviewer] 子代理返回空摘要，跳过注入; "
                f"积压消息={pending_count} 轮次={round_index + 1}"
            )
            return None

        logger.info(
            f"{self._runtime.log_prefix} [buffer_reviewer] 已生成缓冲区摘要并将注入下一轮 Planner; "
            f"积压消息={pending_count} 轮次={round_index + 1} 摘要长度={len(summary)}"
        )
        return f"{_REMINDER_HEADER}{summary}"


def merge_reminders(*reminders: Optional[str]) -> Optional[list[str]]:
    """合并多段 reminder 文本，过滤空值，返回可直接作为 injected_user_messages 的列表。

    Planner 接收的 `injected_user_messages` 是 `list[str]`（参考 reasoning_engine
    对 `deferred_tools_reminder` 的处理），因此返回列表形式；全空返回 None。
    """

    merged: list[str] = []
    for item in reminders:
        if not item:
            continue
        text = item.strip()
        if text:
            merged.append(text)
    return merged if merged else None


__all__ = [
    "BufferedMessageReviewer",
    "merge_reminders",
]
