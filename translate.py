"""
Translate an SRT subtitle file (Japanese -> Simplified Chinese) using LM Studio OpenAI-compatible endpoint.

Usage:
    python translate_srt.py input.srt

Output:
    input.chs.srt
"""

from __future__ import annotations
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import List, Sequence, Tuple, Dict, Optional

import requests


# ======================
# 固定配置（按需改一次）
# ======================

API_BASE = "http://localhost:1234"           # LM Studio server base
API_KEY = "lm-studio"                        # placeholder; LM Studio usually ignores it
MODEL_NAME = "Sakura GalTransl 7B v3"   # ←←← 必须改
TEMPERATURE = 0.2
TIMEOUT = 300

# Token 上限：batch 时适当大一点
MAX_TOKENS_BATCH = 1024
MAX_TOKENS_LINE = 256

# 批量大小：5000行字幕推荐 15~25
BATCH_SIZE = 20

# 重试
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 0.6  # seconds

# 行标签（用于可靠拆分）
LINE_TAG_FMT = "<L{}>"

# 跳过规则：音效/注释/音乐符号等（你可按需放宽）
SKIP_RE = re.compile(r"^\s*(\[.*?\]|\(.*?\)|（.*?）|♪.*)\s*$")


# Batch 翻译 prompt（关键：强制保持行号/行数）
SYSTEM_PROMPT_BATCH = (
    "你是专业的日译中字幕翻译助手。\n"
    "你将收到多行日文字幕，每行以 <L数字> 开头。\n"
    "请逐行翻译成自然、通顺的简体中文，并严格保持行号与行数不变。\n"
    "硬性要求：\n"
    "- 输出必须逐行对应输入：有多少行就输出多少行\n"
    "- 每一行必须以相同的 <L数字> 开头（例如 <L1>、<L2>...）\n"
    "- 不要合并、删除、新增任何行\n"
    "- 只输出译文，不要解释\n"
    "- 不要输出日文原文\n"
)

# 逐行兜底 prompt（更稳）
SYSTEM_PROMPT_LINE = (
    "你是专业的日译中字幕翻译助手。\n"
    "任务：将输入的单行日文字幕翻译为自然、通顺的简体中文。\n"
    "要求：\n"
    "- 只输出译文，不要解释\n"
    "- 不要输出日文原文\n"
    "- 保持简短，符合字幕阅读习惯\n"
)


# ======================
# 数据结构
# ======================

@dataclass
class SubtitleEntry:
    index: int
    start: str
    end: str
    lines: List[str]


class TranslationError(RuntimeError):
    """Raised when the translation endpoint returns an invalid response."""


# ======================
# SRT 读取/写入（健壮版）
# ======================

def read_srt(path: str) -> List[SubtitleEntry]:
    with open(path, "r", encoding="utf-8-sig") as handle:
        raw_lines = handle.read().splitlines()

    entries: List[SubtitleEntry] = []
    i = 0
    n = len(raw_lines)

    while i < n:
        line = raw_lines[i].strip()
        if not line:
            i += 1
            continue

        if not line.isdigit():
            # 容错：跳过异常行
            i += 1
            continue

        index = int(line)
        i += 1
        if i >= n:
            break

        timing_line = raw_lines[i].strip()
        if "-->" not in timing_line:
            # 格式异常：跳过此块
            i += 1
            continue

        start, end = [seg.strip() for seg in timing_line.split("-->", 1)]
        i += 1

        text_lines: List[str] = []
        while i < n and raw_lines[i].strip():
            text_lines.append(raw_lines[i])
            i += 1

        entries.append(SubtitleEntry(index=index, start=start, end=end, lines=text_lines))

        while i < n and not raw_lines[i].strip():
            i += 1

    return entries


def write_srt(entries: Sequence[SubtitleEntry], path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(f"{entry.index}\n")
            handle.write(f"{entry.start} --> {entry.end}\n")
            for line in entry.lines:
                handle.write(f"{line}\n")
            handle.write("\n")


def default_output_path(source_path: str) -> str:
    directory, filename = os.path.split(source_path)
    stem, ext = os.path.splitext(filename)
    if ext.lower() != ".srt":
        ext = ext or ".srt"
    return os.path.join(directory or ".", f"{stem}.chs{ext}")


# ======================
# API 调用（重试 + 校验）
# ======================

def call_chat_completions(system_prompt: str, user_content: str, max_tokens: int) -> str:
    url = API_BASE.rstrip("/") + "/v1/chat/completions"
    payload = {
        "model": MODEL_NAME,
        "temperature": TEMPERATURE,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise TranslationError(f"Unexpected API response shape: {data}") from exc
            return (content or "").strip()
        except (requests.RequestException, TranslationError) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))
                continue
            raise TranslationError(f"API call failed after retries: {exc}") from exc

    raise TranslationError(f"API call failed: {last_exc}")


# ======================
# 翻译逻辑：batch 主路径 + 逐行兜底
# ======================

def should_skip_line(line: str) -> bool:
    t = line.strip()
    if not t:
        return True
    if SKIP_RE.match(t):
        return True
    return False


def translate_line(line: str) -> str:
    if should_skip_line(line):
        return line
    out = call_chat_completions(SYSTEM_PROMPT_LINE, line, MAX_TOKENS_LINE)
    return out if out else line


def translate_batch(lines: List[str]) -> List[str]:
    """
    Batch translate N lines using line tags, ensuring a reliable split back.
    Input:  ["原文1", "原文2", ...]
    Output: ["译文1", "译文2", ...]
    """
    # 只对需要翻译的行做 batch（caller 保证）
    tagged_in = []
    for i, line in enumerate(lines, start=1):
        tagged_in.append(f"{LINE_TAG_FMT.format(i)} {line}")
    user_content = "\n".join(tagged_in)

    raw_out = call_chat_completions(SYSTEM_PROMPT_BATCH, user_content, MAX_TOKENS_BATCH)
    out_lines = [ln.strip() for ln in raw_out.splitlines() if ln.strip()]

    # 校验：行数必须一致
    if len(out_lines) != len(lines):
        raise TranslationError(f"Batch line count mismatch: in={len(lines)} out={len(out_lines)}")

    results: List[str] = []
    for i, out in enumerate(out_lines, start=1):
        prefix = LINE_TAG_FMT.format(i)
        if not out.startswith(prefix):
            raise TranslationError(f"Batch tag mismatch on line {i}: got={out[:20]!r}")
        results.append(out[len(prefix):].strip() or lines[i - 1])

    return results


def translate_file(input_path: str) -> str:
    entries = read_srt(input_path)

    # 收集需要翻译的位置
    positions: List[Tuple[int, int]] = []  # (entry_idx, line_idx)
    source_lines: List[str] = []

    for e_idx, entry in enumerate(entries):
        for l_idx, line in enumerate(entry.lines):
            if should_skip_line(line):
                continue
            positions.append((e_idx, l_idx))
            source_lines.append(line)

    total_lines = len(source_lines)
    translated_lines: List[str] = [""] * total_lines

    def emit_progress(done: int, total: int) -> None:
        print(f"[PROGRESS] {done}/{total}", flush=True)

    emit_progress(0, total_lines)
    done = 0
    i = 0
    while i < total_lines:
        batch_src = source_lines[i:i + BATCH_SIZE]
        try:
            batch_out = translate_batch(batch_src)
            translated_lines[i:i + BATCH_SIZE] = batch_out
            done += len(batch_out)
            emit_progress(done, total_lines)
        except Exception:
            # 兜底：逐行翻译
            for j, line in enumerate(batch_src):
                translated_lines[i + j] = translate_line(line)
                done += 1
                emit_progress(done, total_lines)
        i += BATCH_SIZE

    # 写回 entries
    for (e_idx, l_idx), out in zip(positions, translated_lines):
        entries[e_idx].lines[l_idx] = out

    output_path = default_output_path(input_path)
    write_srt(entries, output_path)

    original_path = os.path.abspath(input_path)
    translated_path = os.path.abspath(output_path)

    if os.path.exists(original_path):
        try:
            os.remove(original_path)
        except OSError as exc:
            raise OSError(f"Failed to remove original subtitle: {original_path}") from exc

    os.replace(translated_path, original_path)
    return original_path


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if not args:
        print("Usage: python translate_srt.py <input.srt>")
        return 1

    input_path = args[0]
    try:
        output_path = translate_file(input_path)
    except (OSError, ValueError, TranslationError, requests.RequestException) as exc:
        print(f"[ERROR] {exc}")
        return 1

    print(f"Saved translated subtitles to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
