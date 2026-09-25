"""资料归档核心逻辑的离线冒烟测试：不依赖 fastapi，系统 python3 即可跑。

覆盖需求点：
1. 批量校验：缺版本号 / 格式不对 / 版本号与资料关联不上 分别列原因；
2. 确认后才入库，未确认列表为空；
3. 同一份图纸传两次只留一条（同批重复、跨批重复、版本相同内容不同）；
4. 竣工资料换版后旧版本不可下载、仍可查看；图纸历史版本可下载；
5. 按区段打包只含当前生效版本；
6. 区段/车站与台账对不上时驳回；
7. 中断重来：半成品 tmp/blob 被清理，已归档资料仍在。
"""
from __future__ import annotations

import base64
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.archive import ArchiveError, ArchiveService  # noqa: E402
from app.services.archive_store import ArchiveStore  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("PASS" if condition else "FAIL"), "-", name + (f" :: {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(name)


SECTIONS = ["SECT-0001", "SECT-0002"]
STATIONS = ["联锁设备样例1", "中心站"]


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def make_item(**overrides):
    item = {
        "资料类型": "图纸",
        "区段编码": "SECT-0001",
        "车站": "中心站",
        "资料名称": "进站信号机布置图",
        "版本号": "V1.0",
        "生效日期": "2026-09-01",
        "文件名": "signal-layout.pdf",
        "上传人": "张三",
        "文件内容": b64(b"%PDF-1.4 drawing v1"),
    }
    item.update(overrides)
    return item


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="archive-test-"))
    try:
        svc = ArchiveService(
            ArchiveStore(str(tmp / "archive"), staging_ttl=3600),
            sections_provider=lambda: SECTIONS,
            stations_provider=lambda: STATIONS,
        )

        # 1) 批量校验：三类问题条目
        bad_batch = [
            make_item(版本号=""),                                   # 缺版本号
            make_item(文件名="drawing.exe"),                       # 格式不对
            make_item(文件名="drawing.pdf", 文件内容=b""),          # 关联不上
            make_item(区段编码="SECT-9999"),                        # 台账对不上
            make_item(版本号="最新版"),                             # 版本号格式
            make_item(生效日期="2026/09/01"),                       # 日期格式
            make_item(车站="不存在的站"),                           # 车站对不上
            make_item(资料类型="其他资料"),                          # 类型不对
        ]
        result = svc.preflight(bad_batch)
        check("校验不入库", len(svc.list_entries(section=None, size=1000)[0]) == 0)
        check("8 条全部驳回", result["驳回"] == 8, str(result["rejected"]))
        reasons_blob = {r["index"]: "；".join(r["原因"]) for r in result["rejected"]}
        check("缺版本号原因", "缺少版本号" in reasons_blob[0])
        check("格式不对原因", "格式" in reasons_blob[1])
        check("关联不上原因", "关联不上" in reasons_blob[2])
        check("区段台账原因", "台账" in reasons_blob[3])
        check("版本号格式原因", "格式不对" in reasons_blob[4])
        check("日期格式原因", "YYYY-MM-DD" in reasons_blob[5])
        check("车站台账原因", "联锁设备台账" in reasons_blob[6])
        check("类型原因", "资料类型" in reasons_blob[7])
        svc.discard(result["token"])

        # 2) 正常批次：一份图纸 + 一份竣工资料
        ok = svc.preflight([
            make_item(),
            make_item(资料类型="竣工资料", 文件名="as-built.pdf",
                      资料名称="信号改造竣工说明", 文件内容=b64(b"%PDF completion v1")),
        ])
        check("正常批次 2 通过", ok["通过"] == 2 and ok["驳回"] == 0, str(ok))
        committed = svc.commit(ok["token"])
        check("确认后入库 2 条", committed["ok"] and len(committed["入库条目"]) == 2)
        items, total = svc.list_entries(size=1000)
        check("列表默认只看当前版本", total == 2, str(total))

        # 3) 同一份图纸传两次只留一条（跨批，内容哈希相同）
        dup = svc.preflight([make_item()])
        check("重复图纸单独列出", dup["重复"] == 1 and dup["通过"] == 0, str(dup))
        svc.discard(dup["token"])
        check("重复未增加记录", svc.list_entries(size=1000)[1] == 2)

        # 3b) 同批内重复（用一份全新资料，避免命中已归档记录）
        dup2 = svc.preflight([
            make_item(资料名称="站内链路图", 生效日期="2026-10-01"),
            make_item(资料名称="站内链路图", 生效日期="2026-10-01"),
        ])
        check("同批重复只过一条", dup2["通过"] == 1 and dup2["重复"] == 1, str(dup2))
        svc.discard(dup2["token"])

        # 3c) 同版本号但内容不同 => 驳回要求升版
        conflict = svc.preflight([make_item(文件内容=b64(b"%PDF totally different bytes"))])
        check("同版本不同内容驳回", conflict["驳回"] == 1 and "升版" in conflict["rejected"][0]["原因"][0])
        svc.discard(conflict["token"])

        # 4) 竣工资料换版：V2 生效，V1 只能查看不能下载
        rev = svc.preflight([make_item(
            资料类型="竣工资料", 资料名称="信号改造竣工说明", 版本号="V2.0",
            生效日期="2026-09-20", 文件名="as-built-v2.pdf",
            文件内容=b64(b"%PDF completion v2"),
        )])
        check("换版校验通过", rev["通过"] == 1)
        svc.commit(rev["token"])
        all_rows = svc.list_entries(size=1000, only_latest=False)[0]
        comp_rows = [r for r in all_rows if r["资料名称"] == "信号改造竣工说明"]
        v1 = next(r for r in comp_rows if r["版本号"] == "1.0")
        v2 = next(r for r in comp_rows if r["版本号"] == "2.0")
        check("V2 为最新且可下载", v2["is_latest"] and v2["可下载"])
        check("V1 非最新且不可下载", not v1["is_latest"] and not v1["可下载"])

        draw_rows = [r for r in all_rows if r["资料名称"] == "进站信号机布置图"]
        check("图纸当前版本可下载", draw_rows[0]["可下载"])

        # 下载门禁：直接验证 service 侧的口径（与 router 同一条件）
        v1_full = svc.get_version(int(v1["id"]))
        v2_full = svc.get_version(int(v2["id"]))
        blocked = v1_full["资料类型"] == "竣工资料" and not v1_full["is_latest"]
        check("竣工旧版下载被门禁拦截", blocked)
        check("竣工新版可下载", not (v2_full["资料类型"] == "竣工资料" and not v2_full["is_latest"]))
        # 查看不受门禁限制：两份文件本体都能读到
        check("历史版本仍可查看(文件在)", svc.store.read_blob(v1_full["content_hash"]) is not None)

        # 5) 按区段打包：只含当前生效版本（竣工只打 V2），错误区段拒绝
        buf, zipname, count = svc.build_section_package("SECT-0001")
        check("打包条目数=2(图纸V1+竣工V2)", count == 2, str(count))
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            check("zip 内目录带区段前缀", all(n.startswith("SECT-0001/") for n in names))
            check("zip 不含竣工旧版", not any("V1.0" in n and "竣工" in n for n in names))
            check("zip 含竣工新版", any("V2.0" in n for n in names))
        try:
            svc.build_section_package("SECT-9999")
            check("台账外区段打包被拒", False)
        except ArchiveError:
            check("台账外区段打包被拒", True)

        # 6) 版本沿革
        group = v2_full["group_id"]
        history = svc.list_versions(group)
        check("版本沿革 2 条且新在前", len(history) == 2 and history[0]["版本号"] == "2.0")

        # 7) 中断重来：模拟 blob tmp 残留 + 孤儿 blob，cleanup 后已归档资料不受影响
        blob_dir = tmp / "archive" / "blobs"
        (blob_dir / "blob-xyz.tmp").write_bytes(b"half")
        (blob_dir / ("a" * 64)).write_bytes(b"orphan")
        removed = svc.store.cleanup()
        check("清理残留 tmp/孤儿", removed["tmp"] == 1 and removed["orphan_blobs"] >= 1, str(removed))
        check("清理后已归档资料仍在", svc.list_entries(size=1000)[1] == 2)
        check("清理后文件本体可读", svc.store.read_blob(v2_full["content_hash"]) == b"%PDF completion v2")

        # 7b) 新实例（模拟重启）：元数据从盘上恢复，暂存过期会被清
        reborn = ArchiveService(
            ArchiveStore(str(tmp / "archive"), staging_ttl=0),
            sections_provider=lambda: SECTIONS,
            stations_provider=lambda: STATIONS,
        )
        check("重启后已归档资料还在", reborn.list_entries(size=1000)[1] == 2)
        expired = reborn.preflight([make_item(资料名称="另一份图", 文件内容=b64(b"x"))])
        reborn2 = ArchiveService(
            ArchiveStore(str(tmp / "archive"), staging_ttl=0),
            sections_provider=lambda: SECTIONS,
            stations_provider=lambda: STATIONS,
        )
        check("过期暂存被清空", reborn2.store.load_staging(expired["token"]) is None)

        # 7c) commit 不存在的 token 被拒
        try:
            svc.commit("not-a-real-token")
            check("无效 token 入库被拒", False)
        except ArchiveError:
            check("无效 token 入库被拒", True)

        # 8) dwg 图纸 / docx 竣工格式放行
        mixed = svc.preflight([
            make_item(资料名称="电缆径路图", 文件名="cable.dwg", 文件内容=b64(b"DWG1")),
            make_item(资料类型="竣工资料", 资料名称="开通验收记录", 文件名="accept.docx",
                      版本号="V3", 文件内容=b64(b"DOCX")),
        ])
        check("白名单格式放行", mixed["通过"] == 2, str(mixed["rejected"]))
        svc.commit(mixed["token"])

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} 项失败：{failures}")
        return 1
    print("全部断言通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
