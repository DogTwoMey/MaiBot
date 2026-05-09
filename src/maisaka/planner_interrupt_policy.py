"""Planner 打断策略模块

封装"新消息到达时是否应打断当前 Planner"的决策。

本地 fork 专属改动，旨在对 `runtime.register_message` 保持极小侵入；
策略演进只需改本文件，无须触碰核心循环代码，便于后续与 upstream 合并。

策略档位：
- aggressive       任何消息都触发打断（等价于未启用缓冲前的行为）
- buffered         仅 @ / 提及 自己的消息打断，其余进入 message_cache 缓冲（默认）
- strict_buffered  完全不打断，所有消息都走缓冲

"连续打断上限已达"、"本请求已发起过打断"这类守卫条件由策略层统一处理，
runtime 层只负责执行 `should_interrupt` 的最终决定。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

StrategyName = Literal["aggressive", "buffered", "strict_buffered"]

DEFAULT_STRATEGY: StrategyName = "buffered"


@dataclass(frozen=True)
class InterruptDecisionContext:
    """策略决策所需的最小化输入。

    刻意不引用 `SessionMessage` 等业务类型，保持策略层无副作用、易测试。
    """

    message_id: str
    is_at_bot: bool
    is_mentioned: bool
    already_requested: bool
    consecutive_count: int
    max_consecutive_count: int


@dataclass(frozen=True)
class InterruptDecision:
    should_interrupt: bool
    log_reason: str


class PlannerInterruptPolicy(Protocol):
    name: StrategyName

    def decide(self, ctx: InterruptDecisionContext) -> InterruptDecision: ...


def _check_guards(ctx: InterruptDecisionContext) -> InterruptDecision | None:
    """处理所有策略共享的守卫条件，命中则直接返回拒绝决定。"""
    if ctx.already_requested:
        return InterruptDecision(
            False,
            f"收到新消息，但当前请求已发起过一次规划器打断，本次不重复打断; "
            f"消息编号={ctx.message_id} "
            f"连续打断次数={ctx.consecutive_count}/{ctx.max_consecutive_count}",
        )
    if ctx.max_consecutive_count > 0 and ctx.consecutive_count >= ctx.max_consecutive_count:
        return InterruptDecision(
            False,
            f"收到新消息，但已达到规划器连续打断上限，将等待当前请求自然完成; "
            f"消息编号={ctx.message_id} "
            f"连续打断次数={ctx.consecutive_count}/{ctx.max_consecutive_count}",
        )
    return None


def _accept(ctx: InterruptDecisionContext, trigger_reason: str) -> InterruptDecision:
    return InterruptDecision(
        True,
        f"收到新消息，发起规划器打断; 触发原因={trigger_reason} "
        f"消息编号={ctx.message_id} "
        f"连续打断次数={ctx.consecutive_count + 1}/{ctx.max_consecutive_count}",
    )


class _AggressivePolicy:
    name: StrategyName = "aggressive"

    def decide(self, ctx: InterruptDecisionContext) -> InterruptDecision:
        guard = _check_guards(ctx)
        if guard is not None:
            return guard
        return _accept(ctx, "aggressive 策略允许任意消息打断")


class _BufferedPolicy:
    name: StrategyName = "buffered"

    def decide(self, ctx: InterruptDecisionContext) -> InterruptDecision:
        guard = _check_guards(ctx)
        if guard is not None:
            return guard
        if ctx.is_at_bot:
            return _accept(ctx, "@消息")
        if ctx.is_mentioned:
            return _accept(ctx, "提及消息")
        return InterruptDecision(
            False,
            f"普通消息进入缓冲，不打断当前 Planner; 消息编号={ctx.message_id} "
            f"策略=buffered",
        )


class _StrictBufferedPolicy:
    name: StrategyName = "strict_buffered"

    def decide(self, ctx: InterruptDecisionContext) -> InterruptDecision:
        guard = _check_guards(ctx)
        if guard is not None:
            return guard
        return InterruptDecision(
            False,
            f"消息进入缓冲，不打断; 消息编号={ctx.message_id} 策略=strict_buffered",
        )


_POLICY_REGISTRY: dict[str, PlannerInterruptPolicy] = {
    "aggressive": _AggressivePolicy(),
    "buffered": _BufferedPolicy(),
    "strict_buffered": _StrictBufferedPolicy(),
}


def get_policy(strategy_name: str | None) -> PlannerInterruptPolicy:
    """根据配置字符串返回对应策略；无效值回退到默认策略。"""
    key = (strategy_name or "").strip().lower()
    return _POLICY_REGISTRY.get(key, _POLICY_REGISTRY[DEFAULT_STRATEGY])


__all__ = [
    "DEFAULT_STRATEGY",
    "InterruptDecision",
    "InterruptDecisionContext",
    "PlannerInterruptPolicy",
    "StrategyName",
    "get_policy",
]
