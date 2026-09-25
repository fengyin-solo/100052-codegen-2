"""资料归档接口：按区段与车站归档图纸、竣工资料，覆盖批量上传校验、确认入库、下载与按区段打包。"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response

from app.schemas import ActionResult, ArchiveUploadPayload, PageResult
from app.services.archive import CATEGORIES, STATUSES, ArchiveService

router = APIRouter(prefix="/api/archive", tags=["资料归档"])

service = ArchiveService()

LIST_FIELDS = ["资料编号", "资料名称", "资料类别", "所属区段", "所属车站", "版本号", "生效日期", "文件格式", "上传人", "资料状态"]


@router.get("/sections")
def list_ledger_sections() -> dict[str, Any]:
    """设备台账里的区段清单：上传资料从这里选区段，保证资料与台账对得上。"""
    return {"items": service.ledger_sections(), "categories": CATEGORIES, "statuses": STATUSES}


@router.get("/package")
def package_section(section: str = Query(default="", description="按区段编码打包现行有效资料")) -> Response:
    """按区段打包取走：zip 里只有现行有效版本和一份归档清单，旧版本不进包。"""
    section = section.strip()
    if not section:
        raise HTTPException(status_code=400, detail="请指定要打包的区段编码")
    content = service.build_section_package(section)
    if content is None:
        raise HTTPException(status_code=404, detail=f"区段 {section} 下没有可打包的现行资料")
    filename = quote(f"资料打包-{section}.zip")
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{filename}"},
    )


@router.post("/uploads/validate")
def validate_upload(payload: ArchiveUploadPayload) -> dict[str, Any]:
    """批量上传第一步：逐条校验，可入库、未通过（含原因）、重复忽略分开列出，确认前不写库。"""
    if not payload.items:
        raise HTTPException(status_code=400, detail="本次上传没有资料条目，请先添加再校验")
    return service.validate_batch([item.model_dump() for item in payload.items])


@router.post("/uploads/{batch_id}/confirm", response_model=ActionResult)
def confirm_upload(batch_id: str) -> ActionResult:
    """批量上传第二步：确认后一次性入库；重复确认幂等，中断重传不会残留半份资料。"""
    entries, skipped, message = service.confirm_batch(batch_id)
    if entries is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(
        ok=True,
        message=message,
        entry={"入库数": len(entries), "重复跳过": len(skipped), "条目": entries},
    )


@router.delete("/uploads/{batch_id}", response_model=ActionResult)
def discard_upload(batch_id: str) -> ActionResult:
    """放弃待确认批次：暂存条目清掉，归档表不受影响。"""
    ok, message = service.discard_batch(batch_id)
    return ActionResult(ok=ok, message=message)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按资料名称检索"),
    section: str | None = Query(default=None, description="按所属区段过滤"),
    category: str | None = Query(default=None, description="图纸、竣工资料"),
    status: str | None = Query(default=None, description="现行有效、历史版本"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按名称、区段、类别、状态过滤资料列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, section=section, category=category, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出资料归档清单：返回当前全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "archive", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单份资料明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"资料 {entry_id} 不存在或已移除")
    return entry


@router.get("/{entry_id}/versions")
def get_versions(entry_id: int) -> dict[str, Any]:
    """同一份资料的版本沿革：新版本在前，历史版本仅可查看。"""
    chain = service.versions_of(entry_id)
    if chain is None:
        raise HTTPException(status_code=404, detail=f"资料 {entry_id} 不存在或已移除")
    return {"items": chain, "total": len(chain)}


@router.get("/{entry_id}/download")
def download_entry(entry_id: int) -> Response:
    """下载资料文件；换版后的历史版本只能查看，下载会被拦下并说明原因。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"资料 {entry_id} 不存在或已移除")
    if not service.downloadable(entry):
        raise HTTPException(
            status_code=409,
            detail=f"「{entry['资料名称']}」已换版，{entry['版本号']} 是历史版本，仅可查看不能下载",
        )
    content = str(entry.get("文件内容") or "").encode("utf-8")
    filename = quote(str(entry.get("文件名") or f"{entry['资料编号']}.txt"))
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{filename}"},
    )
