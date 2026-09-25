"""资料归档业务规则。

设计口径：
- 资料身份（同一份图纸/竣工资料）= 资料类型 + 区段编码 + 车站 + 资料名称；
  同一身份下的每次上传是一条独立版本，最新版本按（生效日期、上传时间）取大。
- preflight 只校验不落库：通过条目、驳回条目（逐条列原因）、重复条目三类分开；
  commit 全部通过条目一次性入库，中途任一环节失败整体回滚，不留半份。
- 区段编码必须在线路区段台账里、车站必须在联锁设备台账的“所属车站”里，
  保证资料上的区段/车站和设备台账对得上。
"""
from __future__ import annotations

import base64
import binascii
import io
import re
import secrets
import zipfile
from datetime import datetime
from typing import Any, Callable

from app.config import settings
from app.services.archive_store import ArchiveStore
from app.store import store

MODULE_SECTION = "section"
MODULE_INTERLOCK = "interlock"

TYPE_DRAWING = "图纸"
TYPE_COMPLETION = "竣工资料"
DOC_TYPES = [TYPE_DRAWING, TYPE_COMPLETION]

# 各资料类型允许归档的文件格式：图纸以 PDF/CAD 为主，竣工资料以办公文档和压缩包为主。
ALLOWED_EXTENSIONS = {
    TYPE_DRAWING: {"pdf", "dwg", "dxf"},
    TYPE_COMPLETION: {"pdf", "doc", "docx", "xls", "xlsx", "zip", "rar"},
}

# 版本号：V1、v1.0、2.3.1 这类形态；“最新版”“初稿”这种文字不算版本号。
VERSION_PATTERN = re.compile(r"^[Vv]?\d+(?:\.\d+)*$")
DATE_FMT = "%Y-%m-%d"

REQUIRED_FIELDS = ["资料类型", "区段编码", "车站", "资料名称", "版本号", "生效日期"]

# 一份资料在身份键里的字段顺序，group_id 就由这串内容哈希得到。
IDENTITY_FIELDS = ["资料类型", "区段编码", "车站", "资料名称"]


class ArchiveError(Exception):
    """入库环节出错时抛出：调用方负责整体回滚后的应答。"""


def _group_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(str(item.get(field) or "").strip() for field in IDENTITY_FIELDS)  # type: ignore[return-value]


def ledger_sections() -> list[str]:
    """设备台账里登记过的区段编码，去重后供前端下拉和后端校验共用。"""
    return sorted({str(row.get("区段编码") or "").strip() for row in store.rows(MODULE_SECTION) if row.get("区段编码")})


def ledger_stations() -> list[str]:
    """车站口径取联锁设备台账的“所属车站”，保证资料车站与设备台账一致。"""
    return sorted({str(row.get("所属车站") or "").strip() for row in store.rows(MODULE_INTERLOCK) if row.get("所属车站")})


class ArchiveService:
    def __init__(
        self,
        archive_store: ArchiveStore | None = None,
        *,
        sections_provider: Callable[[], list[str]] | None = None,
        stations_provider: Callable[[], list[str]] | None = None,
    ) -> None:
        self.store = archive_store or ArchiveStore(settings.archive_dir, settings.archive_staging_ttl)
        self._sections_provider = sections_provider or ledger_sections
        self._stations_provider = stations_provider or ledger_stations

    # ---------- 台账口径 ----------

    def options(self) -> dict[str, Any]:
        return {"区段编码": self._sections_provider(), "车站": self._stations_provider(), "资料类型": DOC_TYPES}

    # ---------- 单条目校验 ----------

    def _validate_item(self, item: dict[str, Any], index: int) -> tuple[dict[str, Any] | None, list[str]]:
        """校验一份待传资料；返回（规范化后的条目, 错误原因列表）。"""
        reasons: list[str] = []
        if not isinstance(item, dict):
            return None, [f"第 {index + 1} 行不是有效的资料条目"]

        normalized: dict[str, Any] = {}
        for field in REQUIRED_FIELDS:
            value = str(item.get(field) or "").strip()
            normalized[field] = value
            if not value:
                reasons.append(f"缺少{field}")

        doc_type = normalized.get("资料类型", "")
        if doc_type and doc_type not in DOC_TYPES:
            reasons.append(f"资料类型「{doc_type}」不支持，只能是：{'、'.join(DOC_TYPES)}")

        if normalized.get("区段编码") and normalized["区段编码"] not in self._sections_provider():
            reasons.append(f"区段编码「{normalized['区段编码']}」与设备台账对不上，请先在线路区段中登记")
        if normalized.get("车站") and normalized["车站"] not in self._stations_provider():
            reasons.append(f"车站「{normalized['车站']}」与联锁设备台账对不上，请核对车站名称")

        version = normalized.get("版本号", "")
        if version and not VERSION_PATTERN.match(version):
            reasons.append(f"版本号「{version}」格式不对，应为 V1、v1.0、2.3.1 这类数字版本号")
        normalized["版本号"] = version.lstrip("Vv") if VERSION_PATTERN.match(version) else version

        effective_date = normalized.get("生效日期", "")
        if effective_date:
            try:
                datetime.strptime(effective_date, DATE_FMT)
            except ValueError:
                reasons.append(f"生效日期「{effective_date}」格式不对，应为 YYYY-MM-DD")

        filename = str(item.get("文件名") or "").strip()
        content_b64 = item.get("文件内容")
        normalized["文件名"] = filename
        normalized["上传人"] = str(item.get("上传人") or "").strip() or "值班人员"

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if not filename:
            reasons.append("缺少文件名，版本号无法和具体资料关联")
        elif not ext:
            reasons.append(f"文件名「{filename}」没有扩展名，无法确认格式是否合规")
        elif doc_type in ALLOWED_EXTENSIONS and ext not in ALLOWED_EXTENSIONS[doc_type]:
            allowed = "、".join(sorted(ALLOWED_EXTENSIONS[doc_type]))
            reasons.append(f"文件格式 .{ext} 不允许归档为{doc_type}，允许格式：{allowed}")

        # “版本号与资料关联不上”：条目里只有元数据、带不上文件本体。
        if content_b64 in (None, ""):
            reasons.append("未检测到文件内容，版本号与资料关联不上，请重新选择文件")
        else:
            try:
                blob = base64.b64decode(str(content_b64), validate=True)
            except (binascii.Error, ValueError):
                reasons.append("文件内容解析失败（不是有效的 Base64 数据），版本号与资料关联不上")
                blob = b""
            else:
                if not blob:
                    reasons.append("文件内容为空，版本号与资料关联不上")
                elif len(blob) > settings.archive_max_bytes:
                    reasons.append(f"文件超过 {settings.archive_max_bytes // (1024 * 1024)}MB 上限")
                normalized["_blob_len"] = len(blob)
                normalized["_hash"] = self.store.content_hash(blob)

        if reasons:
            return None, reasons
        normalized["文件内容"] = str(content_b64)
        return normalized, []

    # ---------- 第一步：批量校验 ----------

    def preflight(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """一次上传多份时先给校验结果；任何条目都不入库，等前端确认后再 commit。"""
        if not isinstance(items, list) or not items:
            raise ArchiveError("本批没有可校验的资料条目")

        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []

        seen_in_batch: dict[tuple[str, str, str, str, str, str], int] = {}
        meta = self.store.load_meta()

        for index, raw in enumerate(items):
            item, reasons = self._validate_item(raw, index)
            label = self._item_label(raw if not isinstance(raw, dict) else {**raw})
            if reasons:
                rejected.append({"index": index, "条目": label, "原因": reasons})
                continue

            assert item is not None
            dedup_key = _group_key(item) + (item["版本号"], item["_hash"])

            if dedup_key in seen_in_batch:
                duplicates.append({
                    "index": index,
                    "条目": self._item_label(item),
                    "原因": f"与本批第 {seen_in_batch[dedup_key] + 1} 行是同一份资料的同一版本，重复上传只留一条",
                })
                continue

            existing_same_version = [
                row for row in meta["docs"]
                if _group_key(row) == _group_key(item) and str(row.get("版本号")) == item["版本号"]
            ]
            if existing_same_version:
                same_hash = next((row for row in existing_same_version if row.get("content_hash") == item["_hash"]), None)
                if same_hash is not None:
                    doc_kind = "图纸" if item["资料类型"] == TYPE_DRAWING else "竣工资料"
                    duplicates.append({
                        "index": index,
                        "条目": self._item_label(item),
                        "原因": f"该{doc_kind}的 {item['版本号']} 版已归档且文件内容一致，重复上传只留一条",
                    })
                    continue
                reasons.append(
                    f"版本号 {item['版本号']} 已归档但文件内容不同，不能覆盖既有版本，请升版后重新上传"
                )
                rejected.append({"index": index, "条目": self._item_label(item), "原因": reasons})
                continue

            seen_in_batch[dedup_key] = index
            accepted.append({
                "index": index,
                "条目": self._item_label(item),
                "资料类型": item["资料类型"],
                "区段编码": item["区段编码"],
                "车站": item["车站"],
                "资料名称": item["资料名称"],
                "版本号": item["版本号"],
                "生效日期": item["生效日期"],
                "文件名": item["文件名"],
                "上传人": item["上传人"],
                "大小": item["_blob_len"],
                "文件内容": item["文件内容"],
            })

        token = secrets.token_hex(12)
        self.store.save_staging(token, {"accepted": accepted, "created_at": datetime.now().isoformat(timespec="seconds")})
        return {
            "token": token,
            "总数": len(items),
            "通过": len(accepted),
            "驳回": len(rejected),
            "重复": len(duplicates),
            "accepted": accepted_no_content(accepted),
            "rejected": rejected,
            "duplicates": duplicates,
        }

    @staticmethod
    def _item_label(item: dict[str, Any]) -> str:
        if not isinstance(item, dict):
            return "无法识别的条目"
        parts = [str(item.get(field) or "").strip() for field in ("区段编码", "车站", "资料类型", "资料名称", "版本号")]
        parts = [part for part in parts if part]
        return " / ".join(parts) if parts else str(item.get("文件名") or "未命名资料")

    # ---------- 第二步：确认入库（整体事务） ----------

    def commit(self, token: str) -> dict[str, Any]:
        staged = self.store.load_staging(token)
        if staged is None:
            raise ArchiveError("校验批次不存在或已过期，请重新选择文件校验后再确认")

        accepted = staged.get("accepted") or []
        if not accepted:
            self.store.drop_staging(token)
            raise ArchiveError("本批没有校验通过的资料，未入库任何内容")

        # 防御性再校验：暂存之后台账可能变化；任一不过就整体不入库。
        recheck = self.preflight([
            {k: v for k, v in item.items() if k != "index"}
            for item in accepted
        ])
        problems = [f"{p['条目']}：{'；'.join(p['原因'])}" for p in recheck["rejected"]]
        problems += [f"{p['条目']}：{p['原因']}" for p in recheck["duplicates"]]
        if problems:
            self.store.drop_staging(recheck["token"])
            raise ArchiveError("确认前复核未通过，整批未入库：" + "；".join(problems))

        # 复核产生的新暂存只是临时产物，立即丢弃，继续用原批次入库。
        fresh_token = recheck["token"]
        fresh = self.store.load_staging(fresh_token)
        self.store.drop_staging(fresh_token)
        assert fresh is not None
        if len(fresh["accepted"]) != len(accepted):
            raise ArchiveError("确认前复核条目数与校验时不一致，整批未入库")

        meta = self.store.load_meta()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        added_blobs: list[str] = []
        new_rows: list[dict[str, Any]] = []
        touched_groups = set()

        try:
            # 1) 先把全部文件落 blob：任一失败都还没动元数据，直接中止即可。
            prepared = []
            for item in fresh["accepted"]:
                try:
                    blob = base64.b64decode(item["文件内容"], validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ArchiveError(f"{self._item_label(item)} 文件内容解析失败，整批未入库") from exc
                digest = self.store.put_blob(blob)
                added_blobs.append(digest)
                prepared.append((item, blob, digest))

            # 2) 在内存里构造新版本行；元数据只有最后一次原子写入。
            for item, blob, digest in prepared:
                key = _group_key(item)
                group_id = self.store.content_hash("|".join(key).encode("utf-8"))[:16]
                touched_groups.add(group_id)
                row = {
                    "id": int(meta["next_id"]),
                    "group_id": group_id,
                    "资料类型": item["资料类型"],
                    "区段编码": item["区段编码"],
                    "车站": item["车站"],
                    "资料名称": item["资料名称"],
                    "版本号": item["版本号"],
                    "生效日期": item["生效日期"],
                    "文件名": item["文件名"],
                    "content_hash": digest,
                    "大小": len(blob),
                    "上传人": item["上传人"],
                    "uploaded_at": now,
                    "is_latest": False,
                }
                meta["next_id"] = int(meta["next_id"]) + 1
                meta["docs"].append(row)
                new_rows.append(row)

            # 3) 受影响的身份组重新选最新版本：生效日期新者优先，同一天取上传时间晚的。
            docs_by_group: dict[str, list[dict[str, Any]]] = {}
            for row in meta["docs"]:
                docs_by_group.setdefault(str(row.get("group_id")), []).append(row)
            for group_id in touched_groups:
                rows = docs_by_group.get(group_id, [])
                latest = max(rows, key=lambda r: (str(r.get("生效日期", "")), str(r.get("uploaded_at", ""))), default=None)
                for row in rows:
                    row["is_latest"] = row is latest

            # 4) 元数据原子替换；失败时回收本次新增 blob，列表里绝不会出现没有文件的记录。
            self.store.save_meta(meta)
        except BaseException:
            referenced = {str(d.get("content_hash")) for d in self.store.load_meta().get("docs", [])}
            for digest in added_blobs:
                if digest not in referenced:
                    leftover = self.store.blob_path(digest)
                    if leftover is not None:
                        leftover.unlink(missing_ok=True)
            raise

        self.store.drop_staging(token)
        return {
            "ok": True,
            "message": f"已归档 {len(new_rows)} 份资料，全部条目同批生效",
            "入库条目": [self._list_shape(row) for row in new_rows],
        }

    def discard(self, token: str) -> dict[str, Any]:
        """用户放弃本批校验结果：删掉暂存，确认没有任何资料因此入库。"""
        self.store.drop_staging(token)
        return {"ok": True, "message": "已放弃本批校验结果，没有资料入库"}

    # ---------- 查询 ----------

    @staticmethod
    def _list_shape(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "group_id": row.get("group_id"),
            "资料类型": row.get("资料类型"),
            "区段编码": row.get("区段编码"),
            "车站": row.get("车站"),
            "资料名称": row.get("资料名称"),
            "版本号": row.get("版本号"),
            "生效日期": row.get("生效日期"),
            "文件名": row.get("文件名"),
            "大小": row.get("大小"),
            "上传人": row.get("上传人"),
            "uploaded_at": row.get("uploaded_at"),
            "is_latest": row.get("is_latest"),
            "可下载": row.get("资料类型") != TYPE_COMPLETION or bool(row.get("is_latest")),
        }

    def list_entries(
        self,
        *,
        section: str | None = None,
        station: str | None = None,
        doc_type: str | None = None,
        keyword: str | None = None,
        only_latest: bool = True,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self.store.load_meta()["docs"]
        if section:
            rows = [r for r in rows if r.get("区段编码") == section]
        if station:
            rows = [r for r in rows if r.get("车站") == station]
        if doc_type:
            rows = [r for r in rows if r.get("资料类型") == doc_type]
        if keyword:
            rows = [r for r in rows if keyword in str(r.get("资料名称", "")) or keyword in str(r.get("文件名", ""))]
        if only_latest:
            rows = [r for r in rows if r.get("is_latest")]
        rows.sort(key=lambda r: (str(r.get("区段编码", "")), str(r.get("车站", "")), str(r.get("资料名称", "")), str(r.get("生效日期", ""))), reverse=False)
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._list_shape(r) for r in rows[start:start + size]], total

    def get_version(self, version_id: int) -> dict[str, Any] | None:
        for row in self.store.load_meta()["docs"]:
            if int(row.get("id", 0)) == version_id:
                return row
        return None

    def list_versions(self, group_id: str) -> list[dict[str, Any]]:
        rows = [r for r in self.store.load_meta()["docs"] if r.get("group_id") == group_id]
        rows.sort(key=lambda r: (str(r.get("生效日期", "")), str(r.get("uploaded_at", ""))), reverse=True)
        return [self._list_shape(r) for r in rows]

    def stats(self) -> list[dict[str, Any]]:
        docs = self.store.load_meta()["docs"]
        latest = [d for d in docs if d.get("is_latest")]
        groups = {d.get("group_id") for d in latest}
        old_completion = [d for d in docs if d.get("资料类型") == TYPE_COMPLETION and not d.get("is_latest")]
        return [
            {"label": "已归档资料（当前版本）", "value": len(latest)},
            {"label": "资料份数（含历史版本）", "value": len(docs)},
            {"label": "覆盖图纸/竣工资料", "value": len(groups)},
            {"label": "竣工资料历史版本", "value": len(old_completion)},
        ]

    # ---------- 按区段打包 ----------

    def build_section_package(self, section: str, station: str | None = None) -> tuple[io.BytesIO, str, int]:
        """把区段下每份资料的当前生效版本打进同一个 zip；历史版本不进包。"""
        if section not in self._sections_provider():
            raise ArchiveError(f"区段编码「{section}」与设备台账对不上，无法按区段打包")
        rows = [
            r for r in self.store.load_meta()["docs"]
            if r.get("区段编码") == section and r.get("is_latest") and (not station or r.get("车站") == station)
        ]
        if not rows:
            scope = f"{section}/{station}" if station else section
            raise ArchiveError(f"区段 {scope} 下暂无可打包的已归档资料")

        buffer = io.BytesIO()
        used_names: dict[str, int] = {}
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for row in sorted(rows, key=lambda r: (str(r.get("车站", "")), str(r.get("资料类型", "")), str(r.get("资料名称", "")))):
                blob = self.store.read_blob(str(row.get("content_hash")))
                if blob is None:
                    # 正常不会发生：元数据与 blob 同事务维护；跳过并继续不影响整包。
                    continue
                base_name = f"{row['车站']}_{row['资料类型']}_{row['资料名称']}_V{row['版本号']}{self._ext(row['文件名'])}"
                name = self._unique_name(used_names, base_name)
                zf.writestr(f"{section}/{name}", blob)
        buffer.seek(0)
        scope = f"{section}-{station}" if station else section
        return buffer, f"归档资料_{scope}_{datetime.now().strftime('%Y%m%d%H%M%S')}.zip", len(rows)

    @staticmethod
    def _ext(filename: str) -> str:
        return filename[filename.rfind("."):] if "." in filename else ""

    @staticmethod
    def _unique_name(used: dict[str, int], name: str) -> str:
        if name not in used:
            used[name] = 1
            return name
        stem, dot, ext = name.rpartition(".")
        used[name] += 1
        candidate = f"{stem}({used[name]}){dot}{ext}" if dot else f"{name}({used[name]})"
        return ArchiveService._unique_name(used, candidate)


def accepted_no_content(accepted: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """回给前端的通过清单不带文件内容，避免响应体无谓膨胀。"""
    return [{k: v for k, v in item.items() if k != "文件内容"} for item in accepted]
