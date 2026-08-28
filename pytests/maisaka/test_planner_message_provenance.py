from datetime import datetime

from src.chat.message_receive.message import SessionMessage
from src.common.data_models.mai_message_data_model import MessageInfo, UserInfo
from src.common.data_models.message_component_data_model import MessageSequence
from src.maisaka.context.planner_messages import build_planner_user_prefix_from_session_message


def test_offline_review_history_uses_system_identity() -> None:
    message = SessionMessage(
        message_id="offline-review-private-user-old",
        timestamp=datetime(2026, 7, 3, 19, 17, 0),
        platform="qq",
    )
    message.message_info = MessageInfo(
        user_info=UserInfo(user_id="252995014", user_nickname="七月飞雪"),
        additional_config={"offline_review": True},
    )
    message.session_id = "qq_private_252995014"
    message.raw_message = MessageSequence([])
    message.is_notify = False

    prefix = build_planner_user_prefix_from_session_message(message)

    assert 'user="离线消息回顾（系统）"' in prefix
    assert 'user_id="offline-reviewer"' in prefix
