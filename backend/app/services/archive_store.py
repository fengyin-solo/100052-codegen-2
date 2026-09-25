"""资料归档的落盘存储：元数据 + 内容寻址文件 + 暂存批次。

目录结构（默认 backend/data/archive/）：
    meta.json          已归档资料的全部版本记录（原子写入）
    blobs/<sha256>     文件本体，按内容哈希去重，同一份图纸传两次只占一份
    staging/<token>.json  一次多份上传的校验结果，确认后删除

写入一律走“先写临时文件再 os.replace”，进程被打断也只会留下 tmp 文件，
不会有半截元数据或半截 blob 指向正式数据；启动时 cleanup() 统一回收。
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


class ArchiveStore:
    META_NAME = "meta.json"
    BLOB_DIR = "blobs"
    STAGING_DIR = "staging"

    def __init__(self, base_dir: str, staging_ttl: int = 7200) -> None:
        self.base = Path(base_dir)
        self.blob_root = self.base / self.BLOB_DIR
        self.staging_root = self.base / self.STAGING_DIR
        self.meta_path = self.base / self.META_NAME
        self.staging_ttl = staging_ttl
        self._lock = threading.RLock()
        self.base.mkdir(parents=True, exist_ok=True)
        self.blob_root.mkdir(parents=True, exist_ok=True)
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.cleanup()

    # ---------- 元数据 ----------

    def load_meta(self) -> dict[str, Any]:
        with self._lock:
            if not self.meta_path.exists():
                return {"docs": [], "next_id": 1}
            try:
                with self.meta_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (json.JSONDecodeError, OSError):
                # 元数据损坏不能带病工作：备份现场后从空库起步，避免半成品污染列表。
                backup = self.meta_path.with_suffix(".json.corrupt")
                self.meta_path.replace(backup)
                return {"docs": [], "next_id": 1}
            data.setdefault("docs", [])
            data.setdefault("next_id", max((int(d.get("id", 0)) for d in data["docs"]), default=0) + 1)
            return data

    def _atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            # 写失败/中断：删掉临时文件，正式文件保持上一版不动。
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def save_meta(self, meta: dict[str, Any]) -> None:
        with self._lock:
            self._atomic_write_json(self.meta_path, meta)

    # ---------- 文件本体 ----------

    @staticmethod
    def content_hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def put_blob(self, data: bytes) -> str:
        """写入文件本体并返回哈希；内容相同直接复用，不重复落盘。"""
        digest = self.content_hash(data)
        target = self.blob_root / digest
        if target.exists():
            return digest
        with self._lock:
            if target.exists():
                return digest
            fd, tmp_name = tempfile.mkstemp(prefix="blob-", suffix=".tmp", dir=str(self.blob_root))
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_name, target)
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        return digest

    def blob_path(self, digest: str) -> Path | None:
        # 只允许哈希形态的文件名，杜绝目录穿越。
        if not digest or not all(ch in "0123456789abcdef" for ch in digest.lower()) or len(digest) != 64:
            return None
        path = self.blob_root / digest.lower()
        return path if path.exists() else None

    def read_blob(self, digest: str) -> bytes | None:
        path = self.blob_path(digest)
        if path is None:
            return None
        return path.read_bytes()

    # ---------- 暂存批次 ----------

    def save_staging(self, token: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._atomic_write_json(self.staging_root / f"{token}.json", payload)

    def load_staging(self, token: str) -> dict[str, Any] | None:
        if not token or "/" in token or ".." in token:
            return None
        path = self.staging_root / f"{token}.json"
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None

    def drop_staging(self, token: str) -> None:
        with self._lock:
            path = self.staging_root / f"{token}.json"
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    # ---------- 中断清理 ----------

    def cleanup(self) -> dict[str, int]:
        """启动/初始化时回收残留：临时文件、过期暂存、没有任何版本引用的 blob。

        保证“上传中断后重来”不会留下半份资料或越攒越多的垃圾文件。
        """
        removed = {"tmp": 0, "staging": 0, "orphan_blobs": 0}
        with self._lock:
            for root in (self.base, self.blob_root, self.staging_root):
                if not root.exists():
                    continue
                for child in root.iterdir():
                    if child.is_file() and child.name.endswith(".tmp"):
                        child.unlink(missing_ok=True)
                        removed["tmp"] += 1

            now = time.time()
            for child in self.staging_root.glob("*.json"):
                try:
                    if now - child.stat().st_mtime > self.staging_ttl:
                        child.unlink()
                        removed["staging"] += 1
                except OSError:
                    pass

            meta = self.load_meta()
            referenced = {str(d.get("content_hash", "")).lower() for d in meta.get("docs", [])}
            for child in self.blob_root.iterdir():
                if child.is_file() and child.name not in referenced:
                    child.unlink()
                    removed["orphan_blobs"] += 1
        return removed
