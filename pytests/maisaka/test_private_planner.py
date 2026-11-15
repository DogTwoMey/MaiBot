import pytest

from src.common.i18n import use_locale
from src.common.prompt_i18n import extract_prompt_placeholders, load_prompt_template
from src.config.config import global_config
from src.maisaka.chat_loop_service import MaisakaChatLoopService


@pytest.mark.parametrize("locale", ["zh-CN", "en-US", "ja-JP"])
@pytest.mark.parametrize("passive", [False, True])
def test_private_planner_preserves_mode_and_persona(monkeypatch, locale, passive):
    monkeypatch.setattr(global_config.experimental, "passive_replyer", passive)
    monkeypatch.setattr(global_config.experimental, "focus_on_private", False)
    service = MaisakaChatLoopService(is_group_chat=False)
    expected = "maisaka_chat_private_passive" if passive else "maisaka_chat_private"
    with use_locale(locale):
        assert service._get_chat_prompt_name() == expected
        template = load_prompt_template(expected, include_custom=False)
        assert {"bot_name", "personality"} <= extract_prompt_placeholders(template.template)
        prompt = service._build_chat_system_prompt()
        assert global_config.bot.nickname in prompt
        assert "{bot_name}" not in prompt and "{personality}" not in prompt
        assert "wait" in service._build_planner_final_user_reminder()
