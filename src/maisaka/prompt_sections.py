"""Maisaka prompt 公共片段构造。"""

from src.common.prompt_i18n import load_prompt


def build_system_guidance_prompt(bot_name: str) -> str:
    """构造所有 Maisaka 主流程共用的系统级指导。"""

    return load_prompt("system_guidance", bot_name=bot_name)
