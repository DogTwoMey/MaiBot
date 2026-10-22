"""Verify cached descriptions retain readable image files after reupload."""

from contextlib import contextmanager
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlmodel import Session, create_engine, select

import base64
import pytest
import sys


IMAGE_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aNogAAAAASUVORK5CYII="
)
IMAGE_HASH = sha256(IMAGE_BYTES).hexdigest()
CACHED_DESCRIPTION = "isolated cached description"


@pytest.fixture
def cache_case(monkeypatch, tmp_path):
    """Use real image persistence with isolated storage and external services."""
    from src.common.database.database_model import Images, ImageType
    from src.common.utils import image_path

    engine = create_engine("sqlite:///" + str(tmp_path / "cache.sqlite3"))
    Images.__table__.create(engine)
    monkeypatch.setattr(image_path, "PROJECT_ROOT", tmp_path)

    @contextmanager
    def get_db_session():
        """Provide transactions against the isolated SQLite database."""
        with Session(engine) as session:
            yield session
            session.commit()

    errors = []
    logger = SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda message, **k: errors.append(message),
    )
    model_config = SimpleNamespace(model_task_config=SimpleNamespace(vlm=SimpleNamespace(model_list=["test"])))
    config_manager = SimpleNamespace(get_model_config=lambda: model_config)
    monkeypatch.setitem(sys.modules, "src.common.logger", SimpleNamespace(get_logger=lambda _: logger))
    monkeypatch.setitem(sys.modules, "src.common.database.database", SimpleNamespace(get_db_session=get_db_session))
    monkeypatch.setitem(sys.modules, "src.config.config", SimpleNamespace(config_manager=config_manager))
    monkeypatch.setitem(sys.modules, "src.prompt.prompt_manager", SimpleNamespace(prompt_manager=SimpleNamespace()))
    monkeypatch.setitem(sys.modules, "src.services.llm_service", SimpleNamespace(LLMServiceClient=lambda **k: None))

    source = Path(__file__).resolve().parents[2] / "src/chat/image_system/image_manager.py"
    spec = spec_from_file_location("image_cache_restoration_test_loaded", source)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    module.IMAGE_DIR = tmp_path / "images"
    module.IMAGE_DIR.mkdir()
    manager = module.image_manager
    vlm = AsyncMock(side_effect=AssertionError("Cached image must not invoke VLM"))
    monkeypatch.setattr(manager, "_generate_image_description", vlm)

    def seed(*, no_file_flag=True, file_exists=False):
        """Store an existing description with controlled file availability."""
        path = module.IMAGE_DIR / (IMAGE_HASH + ".png")
        if file_exists:
            path.write_bytes(IMAGE_BYTES)
        with get_db_session() as session:
            session.add(
                Images(
                    image_hash=IMAGE_HASH,
                    image_type=ImageType.IMAGE,
                    full_path=image_path.serialize_stored_image_path(path),
                    description=CACHED_DESCRIPTION,
                    vlm_processed=True,
                    no_file_flag=no_file_flag,
                )
            )
        return path

    def read_state():
        """Read persisted cache state after image processing."""
        with get_db_session() as session:
            row = session.exec(select(Images).where(Images.image_hash == IMAGE_HASH)).one()
            return {
                "no_file_flag": row.no_file_flag,
                "description": row.description,
                "path": image_path.resolve_stored_image_path(row.full_path),
            }

    yield SimpleNamespace(module=module, manager=manager, seed=seed, read_state=read_state, vlm=vlm, errors=errors)
    engine.dispose()


@pytest.mark.parametrize("wait_for_build", [True, False])
@pytest.mark.parametrize("no_file_flag", [True, False])
@pytest.mark.asyncio
async def test_reupload_restores_cached_image_without_vlm(cache_case, wait_for_build, no_file_flag):
    path = cache_case.seed(no_file_flag=no_file_flag)
    assert not path.exists()

    result = await cache_case.manager.get_image_description(image_bytes=IMAGE_BYTES, wait_for_build=wait_for_build)

    state = cache_case.read_state()
    assert state["path"].is_file()
    assert state["path"].read_bytes() == IMAGE_BYTES
    assert state["no_file_flag"] is False
    assert result == state["description"] == CACHED_DESCRIPTION
    cache_case.vlm.assert_not_awaited()
    assert not cache_case.manager._pending_description_tasks


@pytest.mark.asyncio
async def test_hash_only_lookup_preserves_cached_description(cache_case):
    path = cache_case.seed()

    result = await cache_case.manager.get_image_description(image_hash=IMAGE_HASH)

    assert result == CACHED_DESCRIPTION
    assert not path.exists()
    cache_case.vlm.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_image_reuses_file_without_vlm(cache_case):
    path = cache_case.seed(no_file_flag=False, file_exists=True)
    modified_at = path.stat().st_mtime_ns

    result = await cache_case.manager.get_image_description(image_bytes=IMAGE_BYTES)

    assert result == CACHED_DESCRIPTION
    assert path.stat().st_mtime_ns == modified_at
    assert path.read_bytes() == IMAGE_BYTES
    cache_case.vlm.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_failure_raises_and_keeps_missing_state(cache_case, tmp_path):
    cache_case.seed()
    blocked = tmp_path / "not-a-directory"
    blocked.write_bytes(b"file blocks the cache directory")
    cache_case.module.IMAGE_DIR = blocked

    with pytest.raises(OSError):
        await cache_case.manager.get_image_description(image_bytes=IMAGE_BYTES)
    assert cache_case.read_state()["no_file_flag"] is True
    cache_case.vlm.assert_not_awaited()
    assert not cache_case.manager._pending_description_tasks
