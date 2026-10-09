"""Owner-scoped, single-use WebUI uploads. Files never travel through JSON/RPC."""

from pathlib import Path
from typing import Any, Dict
from collections.abc import Iterator
from contextlib import contextmanager
import asyncio
import hashlib
import io
import secrets
import shutil
import sqlite3
import time
import warnings

from PIL import Image
from src.plugin_runtime.runner.plugin_paths import build_plugin_paths

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def validate_image(raw: bytes) -> str:
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("文件为空或超过 20 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"} or image.n_frames != 1:
                    raise ValueError("仅支持 JPEG、PNG、静态 WebP")
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError("图片超过 4000 万像素")
                image.load()
                return {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[image.format]
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ValueError("图片解码尺寸超限") from exc


class UploadStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS uploads (token TEXT PRIMARY KEY, owner TEXT, suffix TEXT, expires REAL, claimed INTEGER DEFAULT 0, sha TEXT)"
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.root / "uploads.sqlite3", timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def stage(self, owner: str, raw: bytes) -> str:
        build_plugin_paths(owner, PROJECT_ROOT)  # also validates the identifier
        suffix = validate_image(raw)
        token = secrets.token_hex(32)
        with self.connect() as db:
            for (old,) in db.execute("SELECT token FROM uploads WHERE expires < ?", (time.time(),)):
                (self.root / old).unlink(missing_ok=True)
            db.execute("DELETE FROM uploads WHERE expires < ?", (time.time(),))
            (self.root / token).write_bytes(raw)
            db.execute(
                "INSERT INTO uploads VALUES (?,?,?,?,0,?)",
                (token, owner, suffix, time.time() + 3600, hashlib.sha256(raw).hexdigest()),
            )
        return token

    def claim(self, owner: str, token: str) -> Dict[str, Any]:
        paths = build_plugin_paths(owner, PROJECT_ROOT)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT suffix,expires,claimed,sha FROM uploads WHERE token=? AND owner=?", (token, owner)
            ).fetchone()
            if row is None or row[1] < time.time() or row[2]:
                raise ValueError("上传凭证不存在、已过期或已领取")
            destination = paths.data_dir / "uploads" / (token + row[0])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(self.root / token), destination)
            db.execute("UPDATE uploads SET claimed=1 WHERE token=?", (token,))
        return {"path": str(destination), "sha256": row[3], "upload_id": token}


def upload_store() -> UploadStore:
    return UploadStore(PROJECT_ROOT / "temp" / "webui-uploads")


async def claim_upload(plugin_id: str, capability: str, args: Dict[str, Any]) -> Dict[str, Any]:
    del capability
    store = await asyncio.to_thread(upload_store)
    upload = await asyncio.to_thread(store.claim, plugin_id, str(args.get("upload_id", "")))
    return {"success": True, "upload": upload}
