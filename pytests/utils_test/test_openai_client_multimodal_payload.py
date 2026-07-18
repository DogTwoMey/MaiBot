from src.llm_models.model_client.openai_client import (
    QWEN_VL_IMAGE_MAX_PIXELS,
    QWEN_VL_IMAGE_MIN_PIXELS,
    _convert_messages,
    _should_use_qwen_vl_image_options,
)
from src.llm_models.payload_content.message import MessageBuilder


TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB"
    "/6X7Wm0AAAAASUVORK5CYII="
)


def test_qwen_vl_dashscope_payload_adds_pixel_options() -> None:
    message = MessageBuilder().add_text_content("看图").add_image_content("png", TINY_PNG_BASE64).build()

    payload = _convert_messages([message], use_qwen_vl_image_options=True)

    content = payload[0]["content"]
    assert isinstance(content, list)
    image_url = content[1]["image_url"]
    assert image_url["url"].startswith("data:image/png;base64,")
    assert image_url["min_pixels"] == QWEN_VL_IMAGE_MIN_PIXELS
    assert image_url["max_pixels"] == QWEN_VL_IMAGE_MAX_PIXELS


def test_standard_openai_payload_does_not_add_dashscope_pixel_options() -> None:
    message = MessageBuilder().add_text_content("看图").add_image_content("png", TINY_PNG_BASE64).build()

    payload = _convert_messages([message])

    content = payload[0]["content"]
    assert isinstance(content, list)
    image_url = content[1]["image_url"]
    assert set(image_url) == {"url"}


def test_qwen_vl_image_options_only_apply_to_dashscope_qwen_vl() -> None:
    assert _should_use_qwen_vl_image_options(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen-vl-plus",
    )
    assert _should_use_qwen_vl_image_options(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen3-vl-flash",
    )
    assert not _should_use_qwen_vl_image_options("https://api.openai.com/v1", "gpt-4o")
    assert not _should_use_qwen_vl_image_options(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "text-embedding-v4",
    )
