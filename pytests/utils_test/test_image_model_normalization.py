from io import BytesIO

import base64

from PIL import Image as PILImage

from src.common.utils.utils_image import ImageUtils


def _encode_image(image: PILImage.Image, image_format: str, **save_kwargs: object) -> str:
    output = BytesIO()
    image.save(output, format=image_format, **save_kwargs)
    return base64.b64encode(output.getvalue()).decode("ascii")


def _decode_image(image_base64: str) -> PILImage.Image:
    return PILImage.open(BytesIO(base64.b64decode(image_base64)))


def test_large_image_is_downscaled_for_model() -> None:
    image_base64 = _encode_image(PILImage.new("RGB", (2000, 1000), "white"), "JPEG")

    normalized_base64, image_format, adjusted = ImageUtils.normalize_image_base64_for_model(
        image_base64,
        "jpeg",
    )

    with _decode_image(normalized_base64) as normalized_image:
        assert normalized_image.size == (1600, 800)
    assert image_format == "jpeg"
    assert adjusted is True


def test_metadata_is_removed_and_reported_as_adjustment() -> None:
    exif = PILImage.Exif()
    exif[0x010E] = "private description"
    image_base64 = _encode_image(PILImage.new("RGB", (128, 128), "white"), "JPEG", exif=exif)

    normalized_base64, image_format, adjusted = ImageUtils.normalize_image_base64_for_model(
        image_base64,
        "jpeg",
    )

    with _decode_image(normalized_base64) as normalized_image:
        assert normalized_image.size == (128, 128)
        assert not normalized_image.getexif()
    assert image_format == "jpeg"
    assert adjusted is True


def test_valid_image_without_metadata_is_not_reencoded() -> None:
    image_base64 = _encode_image(PILImage.new("RGB", (128, 128), "white"), "PNG")

    normalized_base64, image_format, adjusted = ImageUtils.normalize_image_base64_for_model(
        image_base64,
        "png",
    )

    assert normalized_base64 == image_base64
    assert image_format == "png"
    assert adjusted is False
