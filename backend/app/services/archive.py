"""资料归档业务规则：批量上传校验、版本沿革、下载与按区段打包的口径都收在这里。

上传走「先校验、确认后才入库」两段式：校验通过的资料先挂在待确认批次上，
确认时一次性写入归档表；中途放弃或超时未确认的批次会被清掉，不留半份资料。
"""
from __future__ import annotations

import re
import zipfile
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any
from uuid import uuid4

from app.store import store

MODULE = "archive"

CATEGORIES = ["图纸", "竣工资料"]
STATUS_CURRENT = "现行有效"
STATUS_HISTORY = "历史版本"
STATUSES = [STATUS_CURRENT, STATUS_HISTORY]
ALLOWED_SUFFIXES = ["pdf", "dwg", "dxf", "doc", "docx", "xls", "xlsx", "zip", "png", "jpg", "jpeg"]
VERSION_PATTERN = re.compile(r"^[Vv]?(\d+)(?:\.(\d+))?$")
BATCH_TTL_MINUTES = 30
ITEM_FIELDS = ["资料名称", "资料类别", "所属区段", "所属车站", "版本号", "生效日期", "文件名", "上传人", "文件内容", "备注"]
REQUIRED_FIELDS = ["资料名称", "资料类别", "所属区段", "所属车站", "生效日期", "文件名"]


def _parse_version(raw: str) -> tuple[int, int] | None:
    """把 V2.0、2、v1.5 这类写法解析成可比较的版本号；认不出来的返回 None。"""
    match = VERSION_PATTERN.match(raw.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2) or 0)


def _norm_version(raw: str) -> str:
    parsed = _parse_version(raw)
    return f"V{parsed[0]}.{parsed[1]}" if parsed else raw.strip()


def _doc_key(values: dict[str, Any]) -> tuple[str, str, str]:
    """同一份资料的认定口径：资料类别 + 所属区段 + 资料名称。"""
    return (
        str(values.get("资料类别", "")).strip(),
        str(values.get("所属区段", "")).strip(),
        str(values.get("资料名称", "")).strip(),
    )


def _dedup_key(values: dict[str, Any]) -> tuple[str, str, str, str]:
    """同一份图纸同一版的认定口径：资料口径再加版本号，重复上传只留一条。"""
    return _doc_key(values) + (_norm_version(str(values.get("版本号", ""))),)


def _ledger_sections() -> dict[str, dict[str, Any]]:
    """设备台账里的区段：资料上的区段必须能在这里对上。"""
    return {
        str(row.get("区段编码", "")).strip(): row
        for row in store.rows("section")
        if str(row.get("区段编码", "")).strip()
    }


class ArchiveService:
    def __init__(self) -> None:
        # 待确认的上传批次是临时状态，不进业务仓库，避免污染运营概览的模块统计
        self._batches: list[dict[str, Any]] = []

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        section: str | None = None,
        category: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("资料名称", ""))]
        if section:
            rows = [row for row in rows if row.get("所属区段") == section]
        if category:
            rows = [row for row in rows if row.get("资料类别") == category]
        if status:
            rows = [row for row in rows if row.get("资料状态") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def ledger_sections(self) -> list[dict[str, Any]]:
        """给上传表单用的区段台账清单，保证资料上的区段与设备台账对得上。"""
        return [
            {"区段编码": code, "区段名称": row.get("区段名称", ""), "所属线路": row.get("所属线路", "")}
            for code, row in _ledger_sections().items()
        ]

    def versions_of(self, entry_id: int) -> list[dict[str, Any]] | None:
        """同一份资料的版本沿革：新版本在前，旧版本只看不下载。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        key = _doc_key(entry)
        chain = [row for row in store.rows(MODULE) if _doc_key(row) == key]
        return sorted(chain, key=lambda row: _parse_version(str(row.get("版本号", ""))) or (0, 0), reverse=True)

    def downloadable(self, entry: dict[str, Any]) -> bool:
        """只有现行有效版本能下载，换版后的旧版本只能查看。"""
        return entry.get("资料状态") == STATUS_CURRENT

    def validate_batch(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """批量上传第一步：逐条校验并给出结果，确认前不写归档表。"""
        self._cleanup_batches()
        ledger = _ledger_sections()
        archived = store.rows(MODULE)
        archived_keys = {_dedup_key(row) for row in archived}
        archived_docs: dict[tuple[str, str, str], set[tuple[int, int]]] = {}
        for row in archived:
            parsed = _parse_version(str(row.get("版本号", "")))
            if parsed is not None:
                archived_docs.setdefault(_doc_key(row), set()).add(parsed)

        # 第一遍做字段级校验，顺便把本批有效条目的版本收集起来，
        # 供「版本号与资料关联不上」判断使用，与条目先后次序无关。
        checked: list[tuple[int, dict[str, str], list[str], tuple[int, int] | None]] = []
        batch_docs: dict[tuple[str, str, str], set[tuple[int, int]]] = {}
        for index, raw in enumerate(items, start=1):
            values, reasons, parsed = self._check_fields(raw, ledger)
            if not reasons and parsed is not None:
                batch_docs.setdefault(_doc_key(values), set()).add(parsed)
            checked.append((index, values, reasons, parsed))

        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        batch_keys: dict[tuple[str, str, str, str], int] = {}
        for index, values, reasons, parsed in checked:
            if reasons:
                rejected.append({
                    "序号": index,
                    "资料名称": values.get("资料名称") or "（未命名）",
                    "文件名": values.get("文件名") or "—",
                    "原因": reasons,
                })
                continue
            assert parsed is not None
            if parsed[0] > 1:
                lowers = archived_docs.get(_doc_key(values), set()) | batch_docs.get(_doc_key(values), set())
                if not any(version < parsed for version in lowers):
                    rejected.append({
                        "序号": index,
                        "资料名称": values["资料名称"],
                        "文件名": values["文件名"],
                        "原因": [f"版本号与资料关联不上：归档中找不到「{values['资料名称']}」的既有版本，"
                               f"{_norm_version(values['版本号'])} 无处挂接，请先归档低版本"],
                    })
                    continue
            key = _dedup_key(values)
            if key in batch_keys:
                duplicates.append({
                    "序号": index,
                    "资料名称": values["资料名称"],
                    "版本号": _norm_version(values["版本号"]),
                    "原因": f"与本次上传第 {batch_keys[key]} 条是同一份资料，同一份图纸只留一条",
                })
                continue
            if key in archived_keys:
                duplicates.append({
                    "序号": index,
                    "资料名称": values["资料名称"],
                    "版本号": _norm_version(values["版本号"]),
                    "原因": "归档中已存在同一份资料的相同版本，同一份图纸只留一条",
                })
                continue
            batch_keys[key] = index
            accepted.append({
                "序号": index,
                "资料名称": values["资料名称"],
                "资料类别": values["资料类别"],
                "所属区段": values["所属区段"],
                "所属车站": values["所属车站"],
                "版本号": _norm_version(values["版本号"]),
                "生效日期": values["生效日期"],
                "文件名": values["文件名"],
                "上传人": values.get("上传人") or "",
                "文件内容": values.get("文件内容") or "",
                "备注": values.get("备注") or "",
            })

        batch_id = self._stage_batch(accepted) if accepted else None
        return {
            "批次号": batch_id,
            "可入库": accepted,
            "未通过": rejected,
            "重复忽略": duplicates,
            "批次有效期分钟": BATCH_TTL_MINUTES,
        }

    def confirm_batch(self, batch_id: str) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]], str]:
        """批量上传第二步：把校验通过的条目一次性写入归档表，换版同时刷新版本状态。"""
        self._cleanup_batches()
        batch = self._find_batch(batch_id)
        if batch is None:
            return None, [], f"上传批次 {batch_id} 不存在或已过期，请重新校验后再确认"
        if batch["status"] == "已入库":
            entries = [entry for entry in (store.find(MODULE, i) for i in batch["entry_ids"]) if entry]
            return entries, [], "该批次已确认入库，重复确认不会重复写入"
        if batch["status"] != "待确认":
            return None, [], f"上传批次 {batch_id} 已放弃，不能入库"

        rows = store.rows(MODULE)
        archived_keys = {_dedup_key(row) for row in rows}
        next_id = max((int(row.get("id", 0)) for row in rows), default=0)
        next_seq = max(
            (int(str(row.get("资料编号", "ARCH-0")).rsplit("-", 1)[-1]) for row in rows
             if str(row.get("资料编号", "")).startswith("ARCH-") and str(row.get("资料编号", "")).rsplit("-", 1)[-1].isdigit()),
            default=0,
        )
        entries: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for item in batch["items"]:
            if _dedup_key(item) in archived_keys:
                # 确认时归档里已有同一份同一版（别的批次先确认了），跳过不留第二条
                skipped.append(item)
                continue
            next_id += 1
            next_seq += 1
            entries.append(self._build_entry(next_id, next_seq, item))
            archived_keys.add(_dedup_key(item))
        rows.extend(entries)  # 全部条目就绪后一次性写入，确认动作不会留下半批资料
        self._refresh_version_status(rows)
        batch["status"] = "已入库"
        batch["entry_ids"] = [entry["id"] for entry in entries]
        message = f"已归档 {len(entries)} 份资料"
        if skipped:
            message += f"，{len(skipped)} 份与归档重复未写入"
        return entries, skipped, message

    def discard_batch(self, batch_id: str) -> tuple[bool, str]:
        """放弃待确认批次：暂存条目直接清掉，归档表不受影响。"""
        self._cleanup_batches()
        batch = self._find_batch(batch_id)
        if batch is None:
            return False, f"上传批次 {batch_id} 不存在或已过期"
        if batch["status"] == "已入库":
            return False, f"上传批次 {batch_id} 已入库，不能放弃"
        batch["status"] = "已放弃"
        batch["items"] = []
        return True, f"上传批次 {batch_id} 已放弃，未写入任何资料"

    def build_section_package(self, section: str) -> bytes | None:
        """按区段打包现行有效的资料，旧版本不进包；没有可打包资料时返回 None。"""
        current = [
            row for row in store.rows(MODULE)
            if row.get("所属区段") == section and row.get("资料状态") == STATUS_CURRENT
        ]
        if not current:
            return None
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            used: set[str] = set()
            manifest = ["资料编号\t资料名称\t资料类别\t版本号\t生效日期\t文件名"]
            for row in current:
                name = str(row.get("文件名") or f"{row['资料编号']}.txt")
                if name in used:
                    name = f"{row['资料编号']}-{name}"
                used.add(name)
                zf.writestr(name, str(row.get("文件内容") or ""))
                manifest.append(
                    f"{row['资料编号']}\t{row['资料名称']}\t{row['资料类别']}\t{row['版本号']}\t{row['生效日期']}\t{name}"
                )
            zf.writestr("归档清单.txt", "\n".join(manifest))
        return buffer.getvalue()

    def _check_fields(
        self, raw: dict[str, Any], ledger: dict[str, dict[str, Any]]
    ) -> tuple[dict[str, str], list[str], tuple[int, int] | None]:
        values = {field: str(raw.get(field) or "").strip() for field in ITEM_FIELDS}
        reasons: list[str] = []
        missing = [field for field in REQUIRED_FIELDS if not values.get(field)]
        if missing:
            reasons.append(f"缺少必填字段：{'、'.join(missing)}")
        parsed: tuple[int, int] | None = None
        if not values["版本号"]:
            reasons.append("缺少版本号")
        else:
            parsed = _parse_version(values["版本号"])
            if parsed is None:
                reasons.append(f"版本号与资料关联不上：版本号「{values['版本号']}」无法识别，挂不到资料版本链")
        if values["资料类别"] and values["资料类别"] not in CATEGORIES:
            reasons.append(f"资料类别「{values['资料类别']}」不在范围内，只能是：{'、'.join(CATEGORIES)}")
        if values["生效日期"]:
            try:
                date.fromisoformat(values["生效日期"])
            except ValueError:
                reasons.append(f"生效日期「{values['生效日期']}」格式不对，应为 YYYY-MM-DD")
        if values["文件名"]:
            suffix = values["文件名"].rsplit(".", 1)[-1].lower() if "." in values["文件名"] else ""
            if suffix not in ALLOWED_SUFFIXES:
                reasons.append(f"格式不对：文件「{values['文件名']}」的类型不支持，仅接受 {'、'.join(ALLOWED_SUFFIXES)}")
        if values["所属区段"] and values["所属区段"] not in ledger:
            reasons.append(f"所属区段「{values['所属区段']}」在设备台账中查不到，资料与台账对不上")
        return values, reasons, parsed

    def _stage_batch(self, accepted: list[dict[str, Any]]) -> str:
        now = datetime.now()
        batch_id = f"UPL-{now:%Y%m%d}-{uuid4().hex[:6].upper()}"
        self._batches.append({
            "batch_id": batch_id,
            "created_at": now.isoformat(timespec="seconds"),
            "expires_at": (now + timedelta(minutes=BATCH_TTL_MINUTES)).isoformat(timespec="seconds"),
            "status": "待确认",
            "items": accepted,
            "entry_ids": [],
        })
        return batch_id

    def _find_batch(self, batch_id: str) -> dict[str, Any] | None:
        for batch in self._batches:
            if batch.get("batch_id") == batch_id:
                return batch
        return None

    def _cleanup_batches(self) -> None:
        """清掉超时仍未确认的批次：上传中断后重来，不会残留半份资料。"""
        now = datetime.now().isoformat(timespec="seconds")
        self._batches[:] = [
            batch for batch in self._batches
            if not (batch.get("status") == "待确认" and str(batch.get("expires_at", "")) < now)
        ]

    def _build_entry(self, entry_id: int, seq: int, item: dict[str, Any]) -> dict[str, Any]:
        suffix = item["文件名"].rsplit(".", 1)[-1].lower()
        version = _norm_version(item["版本号"])
        return {
            "id": entry_id,
            "资料编号": f"ARCH-{seq:04d}",
            "资料名称": item["资料名称"],
            "资料类别": item["资料类别"],
            "所属区段": item["所属区段"],
            "所属车站": item["所属车站"],
            "版本号": version,
            "生效日期": item["生效日期"],
            "文件名": item["文件名"],
            "文件格式": suffix.upper(),
            "文件内容": item.get("文件内容") or f"{item['资料名称']}（{version}）归档占位内容",
            "上传人": item.get("上传人") or "值班管理员",
            "上传时间": datetime.now().isoformat(timespec="seconds"),
            "备注": item.get("备注") or "",
            "资料状态": STATUS_CURRENT,
            "status": STATUS_CURRENT,
            "可下载": True,
            "pending": False,
            "abnormal": False,
        }

    def _refresh_version_status(self, rows: list[dict[str, Any]]) -> None:
        """换版口径：同一份资料只留最高版本为现行有效，其余转历史版本、关闭下载。"""
        docs: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            docs.setdefault(_doc_key(row), []).append(row)
        for doc_rows in docs.values():
            latest = max(doc_rows, key=lambda row: _parse_version(str(row.get("版本号", ""))) or (0, 0))
            for row in doc_rows:
                is_current = row is latest
                row["资料状态"] = STATUS_CURRENT if is_current else STATUS_HISTORY
                row["status"] = row["资料状态"]
                row["可下载"] = is_current
