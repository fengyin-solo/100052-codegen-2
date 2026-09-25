"""资料归档接口：批量校验、确认入库、版本查看/下载、按区段打包。"""
from __future__ import annotations

import mimetypes
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from app.config import settings
from app.schemas import ArchiveBatchPayload, ArchiveCommitPayload, PageResult
from app.services.archive import TYPE_COMPLETION, ArchiveError, ArchiveService
from app.services.archive_store import ArchiveStore

router = APIRouter(prefix="/api/archive", tags=["资料归档"])

# 模块级单例：与其他业务模块的内存数据不同，归档服务自带落盘存储，重启不丢。
service = ArchiveService(ArchiveStore(settings.archive_dir, settings.archive_staging_ttl))


@router.get("/options")
def options() -> dict[str, object]:
    """区段、车站、资料类型的可选口径，全部来自设备台账，避免手工填错对不上。"""
    return service.options()


@router.get("/stats")
def stats() -> dict[str, object]:
    return {"cards": service.stats()}


@router.get("", response_model=PageResult[dict])
def list_archives(
    区段编码: str | None = Query(default=None, alias="区段编码"),
    车站: str | None = Query(default=None, alias="车站"),
    资料类型: str | None = Query(default=None, alias="资料类型"),
    keyword: str | None = Query(default=None, description="按资料名称或文件名检索"),
    全部版本: bool = Query(default=False, alias="全部版本", description="默认只看当前生效版本"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """归档列表：默认只返回每份资料的当前生效版本；已归档资料重启后仍然在。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        section=区段编码,
        station=车站,
        doc_type=资料类型,
        keyword=keyword,
        only_latest=not 全部版本,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/versions/{group_id}")
def versions(group_id: str) -> dict[str, object]:
    """同一份资料的版本沿革：最新在前，旧版本标注不可下载（竣工资料）。"""
    rows = service.list_versions(group_id)
    if not rows:
        raise HTTPException(status_code=404, detail="该资料没有归档版本")
    return {"group_id": group_id, "total": len(rows), "items": rows}


@router.post("/preflight")
def preflight(payload: ArchiveBatchPayload) -> dict[str, object]:
    """一次上传多份：先校验，通过/驳回/重复三类条目分别列出，确认前不入库。"""
    try:
        return service.preflight(payload.items)
    except ArchiveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/commit")
def commit(payload: ArchiveCommitPayload) -> dict[str, object]:
    """确认入库：校验通过的条目同批落盘，失败整体回滚，不会残留半份资料。"""
    try:
        return service.commit(payload.token.strip())
    except ArchiveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/discard")
def discard(payload: ArchiveCommitPayload) -> dict[str, object]:
    """放弃本批：清掉暂存校验结果，明确没有任何资料入库。"""
    return service.discard(payload.token.strip())


def _content_response(version_id: int, *, as_download: bool) -> Response:
    row = service.get_version(version_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"资料版本 {version_id} 不存在")

    # 竣工资料换版后，旧版本只能查看不能再下载；图纸历史版本不在此限。
    if as_download and row.get("资料类型") == TYPE_COMPLETION and not row.get("is_latest"):
        raise HTTPException(status_code=403, detail="该竣工资料已有新版本生效，历史版本仅供查看，不能再下载")

    blob = service.store.read_blob(str(row.get("content_hash")))
    if blob is None:
        raise HTTPException(status_code=410, detail="文件本体缺失，请联系档案管理员核对落盘目录")

    filename = str(row.get("文件名") or f"archive-{version_id}")
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    disposition = "attachment" if as_download else "inline"
    # RFC 5987：中文文件名要 filename* 走百分号编码，浏览器才不会存成乱码。
    encoded = quote(filename)
    return Response(
        content=blob,
        media_type=media_type,
        headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded}"},
    )


@router.get("/package/zip")
def package_section(
    区段编码: str = Query(..., alias="区段编码", description="必填：按哪个区段打包"),
    车站: str | None = Query(default=None, alias="车站", description="可选：进一步限定到单个车站"),
) -> StreamingResponse:
    """按区段打包取走：zip 内是该区段每份资料的当前生效版本，历史版本不进包。"""
    try:
        buffer, filename, count = service.build_section_package(区段编码, 车站)
    except ArchiveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    encoded = quote(filename)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
            "X-Archive-Count": str(count),
        },
    )


@router.get("/{version_id}/view")
def view_version(version_id: int) -> Response:
    """在线查看（浏览器内联打开）：当前版本、历史版本都允许。"""
    return _content_response(version_id, as_download=False)


@router.get("/{version_id}/download")
def download_version(version_id: int) -> Response:
    """下载：竣工资料的历史版本在此被拦下，只可查看。"""
    return _content_response(version_id, as_download=True)
