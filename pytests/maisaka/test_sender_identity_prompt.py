from datetime import datetime
from types import SimpleNamespace

import pytest

from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator
from src.common.data_models.message_component_data_model import MessageSequence
from src.llm_models.payload_content.context_item import get_item_text
from src.maisaka.context.messages import ComplexSessionMessage, InternalContextMessage, SessionBackedMessage
from src.maisaka.context import messages as context_messages


@pytest.mark.parametrize("user_id", ["test-user-1", "test-user-2"])
@pytest.mark.parametrize("message_type", [SessionBackedMessage, ComplexSessionMessage])
def test_history_preserves_account_when_nickname_matches(user_id, message_type):
    message = SimpleNamespace(
        platform="qq",
        message_info=SimpleNamespace(user_info=SimpleNamespace(user_id=user_id)),
    )
    sequence = MessageSequence([])
    sequence.text("[同名用户]你好")
    history = message_type(
        raw_message=sequence, visible_text="[同名用户]你好", timestamp=datetime.now(), original_message=message,
        message_id="identity-history",
    )

    if isinstance(history, ComplexSessionMessage):
        history.prompt_text = "[同名用户]你好"
    text = get_item_text(history.to_context_item())

    assert f"platform=qq, user_id={user_id}" in text
    assert "[同名用户]你好" in text


@pytest.mark.parametrize("retro", [False, True])
def test_reply_target_preserves_sender_account(retro):
    generator = object.__new__(BaseMaisakaReplyGenerator)
    generator._build_target_message_content = lambda message: "你好"
    message = SimpleNamespace(
        platform="qq", message_id="identity-target", is_notify=False, timestamp=datetime.now(),
        raw_message=MessageSequence([]).text("你好"),
        message_info=SimpleNamespace(user_info=SimpleNamespace(
            user_id="test-user-1", user_cardname="新显示名", user_nickname="同名用户",
        )),
    )
    method = generator._build_retro_reply_target_block if retro else generator._build_target_message_block

    assert "platform=qq, user_id=test-user-1" in method(message)


def test_internal_context_does_not_claim_sender_account():
    context = InternalContextMessage(
        raw_message=MessageSequence([]).text("内部任务"), visible_text="内部任务", timestamp=datetime.now(),
    )
    assert get_item_text(context.to_context_item()) == "内部任务"


def test_history_forwards_image_quality_without_losing_sender_identity(monkeypatch):
    original = SimpleNamespace(platform="qq", message_info=SimpleNamespace(user_info=SimpleNamespace(user_id="test-user-1")))
    history = SessionBackedMessage(
        raw_message=MessageSequence([]).text("你好"), visible_text="你好", timestamp=datetime.now(),
        original_message=original, message_id="quality-history",
    )
    captured = {}

    def build(*args, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(context_messages, "_build_item_from_sequence", build)
    history.to_context_item(max_image_side=512)
    assert captured["max_image_side"] == 512
    assert "user_id=test-user-1" in captured["sender_identity"]
