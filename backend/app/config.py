"""运行配置：端口、跨域、运行环境。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    app_name: str = "轨道交通信号设备检修平台"
    env: str = "local"
    port: int = 8000
    # 资料归档落盘目录：图纸、竣工资料的元数据与文件本体都放这里，
    # 服务重启后已归档资料仍然在；相对路径相对后端工作目录（backend/）。
    archive_dir: str = "data/archive"
    # 单份资料大小上限（字节），默认 50MB，防止一次校验把内存撑爆。
    archive_max_bytes: int = 50 * 1024 * 1024
    # 暂存校验结果保留时长（秒）：超时未确认的批次启动时清掉，不留半成品。
    archive_staging_ttl: int = 2 * 60 * 60
    allowed_origins: list[str] = field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
    page_size_default: int = 20
    page_size_max: int = 200


settings = Settings()
