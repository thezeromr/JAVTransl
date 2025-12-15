"""生成字幕文件的逻辑模块，后续用于封装外部程序调用。"""

from __future__ import annotations

from pathlib import Path


def generate_srt(media_path: Path) -> Path:
    """占位函数：接收媒体文件路径，返回生成的 SRT 路径。"""

    raise NotImplementedError("TODO: 在此处接入外部字幕生成程序")
