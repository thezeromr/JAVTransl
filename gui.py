"""JAVTransl 应用的 PyQt6 主窗口实现。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from gen_srt import SubtitleGenerationController


class FileListWidget(QListWidget):
    """支持拖入视频文件的列表组件。"""

    _VIDEO_SUFFIXES = {
        ".mp4",
        ".mkv",
        ".mov",
        ".avi",
        ".wmv",
        ".flv",
        ".ts",
        ".webm",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(self.SelectionMode.ExtendedSelection)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        """当拖拽进入时校验是否包含视频文件。"""

        if self._has_video_file(event.mimeData().urls()):  # type: ignore[attr-defined]
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        """拖拽移动过程中保持同样校验逻辑。"""

        if self._has_video_file(event.mimeData().urls()):  # type: ignore[attr-defined]
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        """拖拽松开时将视频文件添加到列表。"""

        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()  # type: ignore[attr-defined]
            if url.isLocalFile()
        ]
        video_paths = [path for path in paths if self._is_video_file(path)]
        self._append_items(video_paths)
        event.acceptProposedAction()

    def add_file_paths(self, paths: Iterable[Path]) -> None:
        """供外部调用的接口，用于批量添加文件。"""

        video_paths = [path for path in paths if self._is_video_file(path)]
        self._append_items(video_paths)

    def _append_items(self, paths: Iterable[Path]) -> None:
        """将路径列表加入到控件中（避免重复）。"""

        existing = {self.item(idx).text() for idx in range(self.count())}
        for path in paths:
            normalized = str(path)
            if normalized in existing:
                continue
            QListWidgetItem(normalized, self)

    def _has_video_file(self, urls: Iterable) -> bool:
        """检查拖入的 URL 是否包含视频文件。"""

        for url in urls:
            if url.isLocalFile() and self._is_video_file(Path(url.toLocalFile())):
                return True
        return False

    @classmethod
    def _is_video_file(cls, path: Path) -> bool:
        """判断文件后缀是否属于视频。"""

        return path.suffix.lower() in cls._VIDEO_SUFFIXES


class MainWindow(QMainWindow):
    """JAVTransl 的主窗口界面。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("JAVTransl")
        self.setFixedSize(900, 900)

        self.process_button = QPushButton("开始处理")
        self.translate_button = QPushButton("翻译字幕")
        self.model_selector = QComboBox()
        self.file_list = FileListWidget()
        self.video_output = QPlainTextEdit()
        self.subtitle_output = QPlainTextEdit()
        self.whisper_progress = QLabel("识别进度：等待")
        self.translation_progress = QProgressBar()
        self.controller = SubtitleGenerationController(self)
        self.log_path = Path(__file__).resolve().parent / "log.txt"

        self._configure_widgets()
        self._compose_layout()
        self._wire_events()
        self._maybe_resume_from_log()

    def _configure_widgets(self) -> None:
        """配置控件的基础属性。"""

        self.file_list.setToolTip("拖入视频文件，或后续通过其它入口添加。")
        self.file_list.setMinimumHeight(360)
        self.model_selector.addItems(["medium", "large-v3"])
        self.model_selector.setCurrentText("medium")
        self.video_output.setReadOnly(True)
        self.subtitle_output.setReadOnly(True)
        self.video_output.setPlaceholderText("视频输出将在此显示……")
        self.subtitle_output.setPlaceholderText("字幕输出将在此显示……")
        self.video_output.setMinimumHeight(150)
        self.subtitle_output.setMinimumHeight(150)
        self.translation_progress.setRange(0, 1)
        self.translation_progress.setValue(0)
        self.translation_progress.setTextVisible(True)
        self.translation_progress.setFormat("字幕翻译：等待")

    def _compose_layout(self) -> None:
        """组合整体布局。"""

        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(16)

        # 顶部按钮区域
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self.process_button)
        controls_layout.addWidget(self.translate_button)
        controls_layout.addWidget(QLabel("语音模型"))
        controls_layout.addWidget(self.model_selector)
        controls_layout.addStretch(1)
        root_layout.addLayout(controls_layout)

        # 文件列表区域
        file_label = QLabel("视频文件列表")
        file_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        root_layout.addWidget(file_label)
        root_layout.addWidget(self.file_list, stretch=3)

        # 底部输出区域（上下结构）
        output_layout = QVBoxLayout()
        output_layout.setSpacing(12)
        output_layout.addLayout(
            self._build_output_panel("视频", self.video_output, self.whisper_progress)
        )
        output_layout.addLayout(
            self._build_output_panel("字幕", self.subtitle_output, self.translation_progress)
        )
        root_layout.addLayout(output_layout, stretch=2)

        self.setCentralWidget(root)

    @staticmethod
    def _build_output_panel(
        title: str,
        text_area: QPlainTextEdit,
        extra_widget: QWidget | None = None,
    ) -> QVBoxLayout:
        """构建带标题的输出区域。"""

        layout = QVBoxLayout()
        label = QLabel(title)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(label)
        if extra_widget is not None:
            layout.addWidget(extra_widget)
        layout.addWidget(text_area)
        return layout

    def _wire_events(self) -> None:
        """连接按钮及后台控制器。"""

        self.process_button.clicked.connect(self._handle_process_clicked)
        self.translate_button.clicked.connect(self._handle_translate_clicked)
        self.controller.log_message.connect(self._append_video_output)
        self.controller.translation_message.connect(self._append_subtitle_output)
        self.controller.translation_progress.connect(self._update_translation_progress)
        self.controller.processing_progress.connect(self._update_processing_progress)
        self.controller.busy_changed.connect(self._handle_busy_changed)
        self.controller.request_file_list_clear.connect(self.file_list.clear)
        self.controller.file_completed.connect(self._handle_file_completed)

    def _handle_process_clicked(self) -> None:
        """开始执行字幕生成。"""

        items = [Path(self.file_list.item(i).text()) for i in range(self.file_list.count())]
        if items:
            self._write_log(items)
        to_translate = [path for path in items if path.with_suffix(".srt").exists()]
        to_process = [path for path in items if path not in to_translate]
        for path in to_translate:
            self.controller.enqueue_translation_for_video(path)
        model_name = self.model_selector.currentText()
        if to_process:
            self.controller.start_processing(to_process, model_name)

    def _handle_translate_clicked(self) -> None:
        """弹出文件对话框并加入翻译队列。"""

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择字幕文件",
            "",
            "Subtitle Files (*.srt);;All Files (*)",
        )
        if files:
            self.controller.enqueue_manual_translations(Path(path) for path in files)

    def _append_video_output(self, text: str) -> None:
        """写入 faster-whisper 输出。"""

        cursor = self.video_output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self.video_output.setTextCursor(cursor)
        self.video_output.ensureCursorVisible()

    def _append_subtitle_output(self, text: str) -> None:
        """写入字幕翻译输出。"""

        cursor = self.subtitle_output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self.subtitle_output.setTextCursor(cursor)
        self.subtitle_output.ensureCursorVisible()

    def _update_processing_progress(self, text: str) -> None:
        if text:
            self.whisper_progress.setText(f"识别进度：{text}")
        else:
            self.whisper_progress.setText("识别进度：等待")

    def _update_translation_progress(self, current: int, total: int) -> None:
        if total <= 0:
            self.translation_progress.setRange(0, 1)
            self.translation_progress.setValue(0)
            self.translation_progress.setFormat("字幕翻译：等待")
            return
        if self.translation_progress.maximum() != total:
            self.translation_progress.setRange(0, total)
            self.translation_progress.setFormat("字幕翻译：%v/%m")
        self.translation_progress.setValue(min(current, total))
        if current >= total:
            self.translation_progress.setFormat("字幕翻译：完成 %v/%m")

    def _handle_busy_changed(self, busy: bool) -> None:
        """根据后台状态启用/禁用按钮。"""

        enabled = not busy
        self.process_button.setEnabled(enabled)
        self.translate_button.setEnabled(enabled)

    def _maybe_resume_from_log(self) -> None:
        if not self.log_path.exists():
            return
        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        pending = [line.strip() for line in lines if line.strip()]
        if not pending:
            return

        reply = QMessageBox.question(
            self,
            "未完成的任务",
            "log.txt 中有未完成的文件，是否继续上次处理？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.file_list.clear()
            self.file_list.add_file_paths(Path(path) for path in pending)
        else:
            try:
                self.log_path.unlink()
            except OSError:
                pass

    def _write_log(self, items: Iterable[Path]) -> None:
        normalized = [os.path.abspath(str(path)) for path in items]
        if not normalized:
            return
        try:
            self.log_path.write_text("\n".join(normalized) + "\n", encoding="utf-8")
        except OSError:
            pass

    def _handle_file_completed(self, path: str) -> None:
        if not self.log_path.exists():
            return
        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        target = os.path.abspath(path)
        remaining = [line.strip() for line in lines if line.strip() and os.path.abspath(line.strip()) != target]
        if not remaining:
            try:
                self.log_path.unlink()
            except OSError:
                try:
                    self.log_path.write_text("", encoding="utf-8")
                except OSError:
                    pass
            return
        try:
            self.log_path.write_text("\n".join(remaining) + "\n", encoding="utf-8")
        except OSError:
            pass

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        """窗口关闭时停止所有后台进程。"""

        self.controller.shutdown()
        super().closeEvent(event)
