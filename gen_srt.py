"""字幕生成与翻译逻辑，供 gui.py 复用。"""

from __future__ import annotations

import os
import sys
from collections import deque
from pathlib import Path
from typing import Deque, Iterable, List

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal


class SubtitleGenerationController(QObject):
    """封装 faster-whisper 调用与字幕翻译流程的控制器。"""

    log_message = pyqtSignal(str)
    translation_message = pyqtSignal(str)
    translation_progress = pyqtSignal(int, int)
    processing_progress = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)
    request_file_list_clear = pyqtSignal()
    file_completed = pyqtSignal(str)

    IGNORED_BATCH_EXIT_CODES = {-1073740791}
    TRANSLATION_ENQUEUE_DELAY_MS = 3000
    TRANSLATION_FILE_WAIT_MS = 1000
    TRANSLATION_FILE_WAIT_ATTEMPTS = 10

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.batch_process: QProcess | None = None
        self.translation_process: QProcess | None = None
        self.translation_queue: Deque[str] = deque()
        self.current_translation: str | None = None
        self._pending_video_files: Deque[str] = deque()
        self._has_seen_processing_line = False
        self._last_processing_file: str | None = None
        self._stdout_buffer = ""
        self._translation_stdout_buffer = ""
        self._waiting_translation_path: str | None = None
        self._srt_to_video: dict[str, str] = {}
        self._busy = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start_processing(self, video_paths: Iterable[Path | str], model_name: str = "large-v3") -> None:
        """开始调用 faster-whisper 批量生成字幕。"""

        items = []
        for path in video_paths:
            normalized = os.path.abspath(str(path))
            if not os.path.exists(normalized):
                self._emit_log(f"未找到视频文件：{normalized}\n")
                continue
            items.append(normalized)

        if not items:
            self._emit_log("请选择至少一个视频文件后再运行。\n")
            return

        if self.batch_process and self.batch_process.state() != QProcess.ProcessState.NotRunning:
            self._emit_log("已有任务在运行，请等待完成。\n")
            return

        self._emit_log(f"开始处理 {len(items)} 个文件...\n")
        self._pending_video_files = deque(items)
        self._has_seen_processing_line = False
        self._last_processing_file = None
        self._stdout_buffer = ""
        self._run_with_python_module(items, model_name)
        self._update_busy_state()

    def enqueue_manual_translations(self, srt_paths: Iterable[Path | str]) -> None:
        """将外部选择的字幕文件加入翻译队列。"""

        added = 0
        for path in srt_paths:
            normalized = os.path.abspath(str(path))
            if not os.path.exists(normalized):
                self._emit_translation(f"未找到字幕文件：{normalized}\n")
                continue
            self._enqueue_translation_path(normalized)
            added += 1

        if added:
            self._emit_translation(f"已添加 {added} 个字幕到翻译队列。\n")

    def enqueue_translation_for_video(self, video_path: Path | str) -> None:
        """根据视频路径加入翻译队列（用于已存在字幕的情况）。"""

        normalized = os.path.abspath(str(video_path))
        srt_path = self._expected_srt_path(normalized)
        self._srt_to_video[srt_path] = normalized
        self._enqueue_translation_path(srt_path)

    def shutdown(self) -> None:
        """在应用退出时停止所有运行中的子进程。"""

        self._terminate_process(self.batch_process)
        self.batch_process = None
        self._terminate_process(self.translation_process)
        self.translation_progress.emit(0, 0)
        self.translation_process = None
        self.processing_progress.emit("")
        self.translation_queue.clear()
        self.current_translation = None
        self._waiting_translation_path = None
        self._reset_processing_state()
        self._translation_stdout_buffer = ""
        self._update_busy_state()

    # ------------------------------------------------------------------
    # faster-whisper 执行逻辑
    # ------------------------------------------------------------------
    def _handle_process_output(self) -> None:
        if not self.batch_process:
            return
        data = bytes(self.batch_process.readAllStandardOutput()).decode("utf-8", errors="ignore")
        if data:
            self._process_faster_whisper_output(data)

    def _process_faster_whisper_output(self, chunk: str) -> None:
        self._stdout_buffer += chunk
        while True:
            next_cr = self._stdout_buffer.find("\r")
            next_nl = self._stdout_buffer.find("\n")

            if next_cr == -1 and next_nl == -1:
                break

            if next_cr != -1 and next_nl == next_cr + 1:
                line = self._stdout_buffer[:next_cr]
                self._stdout_buffer = self._stdout_buffer[next_nl + 1 :]
                if line:
                    self._emit_log(line + "\n")
                    self._handle_stdout_line(line)
                continue

            if next_cr == -1 or (0 <= next_nl < next_cr):
                line = self._stdout_buffer[:next_nl].rstrip("\r")
                self._stdout_buffer = self._stdout_buffer[next_nl + 1 :]
                if line:
                    self._emit_log(line + "\n")
                    self._handle_stdout_line(line)
                continue

            line = self._stdout_buffer[:next_cr].rstrip("\r")
            self._stdout_buffer = self._stdout_buffer[next_cr + 1 :]
            if line:
                self.processing_progress.emit(line)
            else:
                self.processing_progress.emit("")

    def _process_stdout_chunk(self, chunk: str) -> None:
        """将标准输出拆分成独立的行并匹配状态。"""

        self._stdout_buffer += chunk
        while True:
            newline_index = self._stdout_buffer.find("\n")
            if newline_index == -1:
                break
            line = self._stdout_buffer[:newline_index].rstrip("\r")
            self._stdout_buffer = self._stdout_buffer[newline_index + 1 :]
            if line:
                self._handle_stdout_line(line)

    def _handle_stdout_line(self, line: str) -> None:
        prefix = "starting to process:"
        if not line.lower().startswith(prefix):
            return

        parsed_path = line[len(prefix) :].strip()
        normalized = os.path.abspath(parsed_path) if parsed_path else None

        if self._has_seen_processing_line and self._last_processing_file:
            self._emit_log(f"处理完成：{self._last_processing_file}\n")
            self._schedule_translation_for_video(self._last_processing_file)

        self._has_seen_processing_line = True
        self._last_processing_file = self._dequeue_next_video_file() or normalized
        if self._last_processing_file:
            self._emit_log(f"开始处理：{self._last_processing_file}\n")

    def _schedule_translation_for_video(self, video_path: str) -> None:
        """延迟 3 秒后将字幕路径加入翻译队列。"""

        subtitle_path = self._expected_srt_path(video_path)
        self._srt_to_video[subtitle_path] = video_path

        def enqueue() -> None:
            self._emit_translation(f"已加入翻译队列: {subtitle_path}\n")
            self._enqueue_translation_path(subtitle_path)

        QTimer.singleShot(3000, enqueue)

    def _dequeue_next_video_file(self) -> str | None:
        if self._pending_video_files:
            return self._pending_video_files.popleft()
        return None

    def _flush_last_processed_video(self) -> None:
        if self._has_seen_processing_line and self._last_processing_file:
            self._emit_log(f"处理完成：{self._last_processing_file}\n")
            self._schedule_translation_for_video(self._last_processing_file)
        self._last_processing_file = None
        self._has_seen_processing_line = False
        self._pending_video_files.clear()

    def _reset_processing_state(self) -> None:
        self._pending_video_files.clear()
        self._has_seen_processing_line = False
        self._last_processing_file = None
        self._stdout_buffer = ""
        self.processing_progress.emit("")
        self._waiting_translation_path = None

    def _terminate_process(self, process: QProcess | None) -> None:
        if not process:
            return
        if process.state() == QProcess.ProcessState.NotRunning:
            process.close()
            return
        process.terminate()
        if not process.waitForFinished(3000):
            process.kill()
            process.waitForFinished(3000)

    def _handle_process_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        if exit_code in self.IGNORED_BATCH_EXIT_CODES:
            self._emit_log(
                "任务结束。\n"
            )
        else:
            self._emit_log(f"任务结束，退出码 {exit_code}。\n")

        self.batch_process = None
        self._flush_last_processed_video()
        self._update_busy_state()
        self._request_file_list_clear_if_idle()

    def _handle_process_error(self, error: QProcess.ProcessError) -> None:
        # self._emit_log(f"faster-whisper 进程异常：{error}，尝试继续后续翻译。\n")
        self.batch_process = None
        # 即使 faster-whisper 异常退出，也要把最后一个视频的字幕排队
        self._flush_last_processed_video()
        self._reset_processing_state()
        self._update_busy_state()
        self._request_file_list_clear_if_idle()

    def _run_with_executable(self, items: List[str]) -> None:
        base_dir = Path(__file__).resolve().parent
        exe_path = base_dir / "Faster-Whisper-XXL\\faster-whisper-xxl.exe"
        if not exe_path.exists():
            self._emit_log("未找到 faster-whisper-xxl.exe，无法开始处理。\n")
            self._reset_processing_state()
            self.batch_process = None
            self._update_busy_state()
            self._request_file_list_clear_if_idle()
            return

        arguments = [
            *items,
            "-pp",
            "-o",
            "source",
            "--batch_recursive",
            "--check_files",
            "--standard",
            "-f",
            "srt",
            "-m",
            "medium",
            "--language",
            "ja"
        ]

        self._launch_process(str(exe_path), arguments, str(exe_path.parent))

    def _run_with_python_module(self, items: List[str], model_name: str) -> None:
        base_dir = Path(__file__).resolve().parent
        script_path = base_dir / "faster-whisper.py"
        if not script_path.exists():
            self._emit_log("未找到faster-whisper.py，无法开始处理。\n")
            self._reset_processing_state()
            self.batch_process = None
            self._update_busy_state()
            self._request_file_list_clear_if_idle()
            return

        python_exec = sys.executable or "python"
        arguments = [
            str(script_path),
            *items,
            "--model",
            model_name,
            "--language",
            "ja",
        ]

        self._launch_process(python_exec, arguments, str(base_dir))

    def _launch_process(self, program: str, arguments: List[str], working_dir: str) -> None:
        process = QProcess(self)
        process.setProgram(program)
        process.setArguments(arguments)
        process.setWorkingDirectory(working_dir)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._handle_process_output)
        process.errorOccurred.connect(self._handle_process_error)
        process.finished.connect(self._handle_process_finished)

        self.batch_process = process
        process.start()
        if not process.waitForStarted(5000):
            self._emit_log("进程启动失败，请检查路径或权限。\n")
            self.batch_process = None
            self._reset_processing_state()
            self._update_busy_state()
            self._request_file_list_clear_if_idle()


    # ------------------------------------------------------------------
    # 翻译队列 & 监控逻辑
    # ------------------------------------------------------------------
    def _expected_srt_path(self, video_path: str) -> str:
        base, _ = os.path.splitext(os.path.abspath(video_path))
        return f"{base}.srt"

    def _enqueue_translation_path(self, srt_path: str) -> None:
        if (
            srt_path in self.translation_queue
            or srt_path == self.current_translation
            or srt_path == self._waiting_translation_path
        ):
            return
        self.translation_queue.append(srt_path)
        self._start_next_translation()
        self._update_busy_state()

    def _start_next_translation(self) -> None:
        if self._is_process_running(self.translation_process) or self._waiting_translation_path:
            return

        while self.translation_queue:
            next_srt = self.translation_queue.popleft()
            self._waiting_translation_path = next_srt
            self._update_busy_state()
            self._begin_translation_when_ready(next_srt, attempt=0)
            return

        self._maybe_handle_translation_idle()

    def _begin_translation_when_ready(self, srt_path: str, attempt: int) -> None:
        if os.path.exists(srt_path):
            self._waiting_translation_path = None
            if self._run_translation_process(srt_path):
                self.current_translation = srt_path
                self._emit_translation(f"开始翻译：{srt_path}\n")
                self._update_busy_state()
            else:
                self.current_translation = None
                self._update_busy_state()
                self._start_next_translation()
            return

        if attempt >= self.TRANSLATION_FILE_WAIT_ATTEMPTS:
            self._emit_translation(f"字幕文件尚未生成，跳过：{srt_path}\n")
            self._waiting_translation_path = None
            self._update_busy_state()
            self._start_next_translation()
            return

        QTimer.singleShot(
            self.TRANSLATION_FILE_WAIT_MS,
            lambda path=srt_path, next_attempt=attempt + 1: self._begin_translation_when_ready(path, next_attempt),
        )

    def _maybe_handle_translation_idle(self) -> None:
        if not self.translation_queue and not self._is_process_running(self.translation_process) and not self._waiting_translation_path:
            self._request_file_list_clear_if_idle()
            self._update_busy_state()

    def _run_translation_process(self, srt_path: str) -> bool:
        base_dir = Path(__file__).resolve().parent
        script_path = base_dir / "translate.py"
        if not script_path.exists():
            self._emit_translation("未找到 srt_translate.py，无法进行字幕翻译。\n")
            return False

        python_exec = sys.executable or "python"
        process = QProcess(self)
        process.setProgram(python_exec)
        process.setArguments([str(script_path), srt_path])
        process.setWorkingDirectory(str(base_dir))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._handle_translation_output)
        process.errorOccurred.connect(self._handle_translation_error)
        process.finished.connect(self._handle_translation_finished)

        self.translation_process = process
        process.start()
        if not process.waitForStarted(5000):
            self._emit_translation("字幕翻译进程启动失败。\n")
            self.translation_process = None
            return False
        self.translation_progress.emit(0, 0)
        return True

    def _handle_translation_output(self) -> None:
        if not self.translation_process:
            return
        data = bytes(self.translation_process.readAllStandardOutput()).decode("utf-8", errors="ignore")
        if data:
            self._process_translation_stdout_chunk(data)

    def _process_translation_stdout_chunk(self, chunk: str) -> None:
        self._translation_stdout_buffer += chunk
        while True:
            newline_index = self._translation_stdout_buffer.find("\n")
            if newline_index == -1:
                break
            line = self._translation_stdout_buffer[:newline_index].rstrip("\r")
            self._translation_stdout_buffer = self._translation_stdout_buffer[newline_index + 1 :]
            if line:
                self._handle_translation_stdout_line(line)

    def _handle_translation_stdout_line(self, line: str) -> None:
        prefix = "[PROGRESS]"
        if line.startswith(prefix):
            payload = line[len(prefix) :].strip()
            try:
                current_str, total_str = payload.split("/", 1)
                current = int(current_str.strip())
                total = int(total_str.strip())
            except (ValueError, AttributeError):
                self._emit_translation(line + "\n")
                return
            self.translation_progress.emit(current, total)
            return
        self._emit_translation(line + "\n")

    def _handle_translation_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        filename = self.current_translation or "未知字幕"
        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            self._emit_translation(f"{filename} 翻译完成。\n")
            if self.current_translation:
                video_path = self._srt_to_video.pop(self.current_translation, None)
                if video_path:
                    self._emit_file_completed(video_path)
        else:
            self._emit_translation(f"{filename} 翻译失败，退出码 {exit_code}。\n")
        self.translation_progress.emit(0, 0)
        self.translation_process = None
        self.current_translation = None
        self._start_next_translation()
        self._maybe_handle_translation_idle()
        self._update_busy_state()

    def _handle_translation_error(self, error: QProcess.ProcessError) -> None:
        filename = self.current_translation or "未知字幕"
        self._emit_translation(f"{filename} 翻译进程错误：{error}。\n")
        self.translation_progress.emit(0, 0)
        self.translation_process = None
        self.current_translation = None
        self._start_next_translation()
        self._maybe_handle_translation_idle()
        self._update_busy_state()

    # ------------------------------------------------------------------
    # 状态 & 输出工具
    # ------------------------------------------------------------------
    def _request_file_list_clear_if_idle(self) -> None:
        if (
            not self._is_process_running(self.batch_process)
            and not self._is_process_running(self.translation_process)
            and not self.translation_queue
            and not self._waiting_translation_path
            and not self._pending_video_files
            and not self._has_seen_processing_line
        ):
            self.request_file_list_clear.emit()

    def _update_busy_state(self) -> None:
        busy = self._is_busy()
        if busy != self._busy:
            self._busy = busy
            self.busy_changed.emit(busy)

    def _is_busy(self) -> bool:
        return bool(
            self._is_process_running(self.batch_process)
            or self._is_process_running(self.translation_process)
            or self.translation_queue
            or self._waiting_translation_path
        )

    @staticmethod
    def _is_process_running(process: QProcess | None) -> bool:
        return bool(process and process.state() != QProcess.ProcessState.NotRunning)

    def _emit_log(self, text: str) -> None:
        self.log_message.emit(text)

    def _emit_translation(self, text: str) -> None:
        self.translation_message.emit(text)

    def _emit_file_completed(self, path: str) -> None:
        self.file_completed.emit(path)
