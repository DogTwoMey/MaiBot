import pytest

from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator


def test_build_system_prompt_injects_reference_info(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replyer 应把工具传入的长期记忆参考写入 system prompt。"""

    generator = object.__new__(BaseMaisakaReplyGenerator)
    captured_context: dict[str, str] = {}

    monkeypatch.setattr(generator, "_resolve_session_id", lambda stream_id: "session-a")
    monkeypatch.setattr(generator, "_build_group_chat_attention_block", lambda session_id: "")
    monkeypatch.setattr(generator, "_build_replyer_output_instruction", lambda: "output")
    monkeypatch.setattr(generator, "_build_personality_prompt", lambda: "identity")
    monkeypatch.setattr(generator, "_select_reply_style", lambda: "style")

    def fake_load_prompt(prompt_name: str, **context: str) -> str:
        assert prompt_name == "maisaka_replyer"
        captured_context.update(context)
        return "system prompt"

    monkeypatch.setattr(generator, "_load_prompt", fake_load_prompt, raising=False)

    system_prompt = generator._build_system_prompt(
        reply_message=None,
        reply_reason="",
        reference_info="用户喜欢深夜打游戏",
    )

    assert system_prompt == "system prompt"
    assert "用户喜欢深夜打游戏" in captured_context["long_term_memory_block"]
