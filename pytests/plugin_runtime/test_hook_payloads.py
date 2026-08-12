from datetime import datetime

from src.chat.message_receive.message import SessionMessage
from src.common.data_models.mai_message_data_model import MessageInfo, UserInfo
from src.common.data_models.message_component_data_model import (
    ForwardComponent,
    ForwardNodeComponent,
    ImageComponent,
    MessageSequence,
    VoiceComponent,
)
from src.plugin_runtime.hook_payloads import deserialize_modified_session_message, serialize_session_message
from src.plugin_runtime.protocol.codec import MsgPackCodec
from src.plugin_runtime.protocol.envelope import Envelope, MessageType
from src.plugin_runtime.transport.base import MAX_FRAME_SIZE


def _build_media_message() -> SessionMessage:
    message = SessionMessage("message-1", datetime.now(), "test")
    message.message_info = MessageInfo(user_info=UserInfo("user-1", "测试用户"))
    message.session_id = "session-1"
    message.processed_plain_text = "媒体消息"
    message.raw_message = MessageSequence(
        [
            ImageComponent(binary_hash="", content="图片描述", binary_data=b"image-bytes"),
            VoiceComponent(binary_hash="", content="语音文本", binary_data=b"voice-bytes"),
            ForwardNodeComponent(
                [
                    ForwardComponent(
                        user_nickname="转发用户",
                        message_id="forward-1",
                        content=[ImageComponent(binary_hash="", binary_data=b"nested-image-bytes")],
                    )
                ]
            ),
        ]
    )
    return message


def test_serialize_session_message_omits_binary_data_by_default() -> None:
    payload = serialize_session_message(_build_media_message())

    assert "binary_data_base64" not in payload["raw_message"][0]
    assert "binary_data_base64" not in payload["raw_message"][1]
    nested_image = payload["raw_message"][2]["data"][0]["content"][0]
    assert "binary_data_base64" not in nested_image
    assert payload["raw_message"][0]["hash"]
    assert payload["raw_message"][1]["hash"]


def test_serialize_session_message_can_include_binary_data_explicitly() -> None:
    payload = serialize_session_message(_build_media_message(), include_binary_data=True)

    assert payload["raw_message"][0]["binary_data_base64"]
    assert payload["raw_message"][1]["binary_data_base64"]
    nested_image = payload["raw_message"][2]["data"][0]["content"][0]
    assert nested_image["binary_data_base64"]


def test_compact_hook_payload_keeps_large_media_below_frame_limit() -> None:
    message = _build_media_message()
    message.raw_message = MessageSequence(
        [ImageComponent(binary_hash="", binary_data=b"x" * (12 * 1024 * 1024))]
    )
    codec = MsgPackCodec()

    compact_frame = codec.encode_envelope(
        Envelope(
            request_id=1,
            message_type=MessageType.REQUEST,
            method="plugin.invoke_hook",
            payload={"component_name": "large_media_hook", "args": {"message": serialize_session_message(message)}},
        )
    )
    binary_frame = codec.encode_envelope(
        Envelope(
            request_id=2,
            message_type=MessageType.REQUEST,
            method="plugin.invoke_hook",
            payload={
                "component_name": "large_media_hook",
                "args": {"message": serialize_session_message(message, include_binary_data=True)},
            },
        )
    )

    assert len(compact_frame) < MAX_FRAME_SIZE
    assert len(binary_frame) > MAX_FRAME_SIZE


def test_unmodified_hook_payload_preserves_original_message_binary_data() -> None:
    message = _build_media_message()
    payload = serialize_session_message(message)

    restored_message = deserialize_modified_session_message(message, payload, dict(payload))

    assert restored_message is message
    image = restored_message.raw_message.components[0]
    assert isinstance(image, ImageComponent)
    assert image.binary_data == b"image-bytes"


def test_modified_hook_payload_restores_matching_binary_data() -> None:
    message = _build_media_message()
    payload = serialize_session_message(message)
    modified_payload = dict(payload)
    modified_payload["processed_plain_text"] = "Hook 改写后的文本"

    restored_message = deserialize_modified_session_message(message, payload, modified_payload)

    assert restored_message is not message
    assert restored_message.processed_plain_text == "Hook 改写后的文本"
    image = restored_message.raw_message.components[0]
    assert isinstance(image, ImageComponent)
    assert image.binary_data == b"image-bytes"
    forward_node = restored_message.raw_message.components[2]
    assert isinstance(forward_node, ForwardNodeComponent)
    nested_image = forward_node.forward_components[0].content[0]
    assert isinstance(nested_image, ImageComponent)
    assert nested_image.binary_data == b"nested-image-bytes"
