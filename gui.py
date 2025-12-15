"""JAVTransl 应用的 PyQt6 主窗口实现。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


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
        self.file_list = FileListWidget()
        self.video_output = QPlainTextEdit()
        self.subtitle_output = QPlainTextEdit()

        self._configure_widgets()
        self._compose_layout()

    def _configure_widgets(self) -> None:
        """配置控件的基础属性。"""

        self.file_list.setToolTip("拖入视频文件，或后续通过其它入口添加。")
        self.file_list.setMinimumHeight(360)
        self.video_output.setReadOnly(True)
        self.subtitle_output.setReadOnly(True)
        self.video_output.setPlaceholderText("视频输出将在此显示……")
        self.subtitle_output.setPlaceholderText("字幕输出将在此显示……")
        self.video_output.setMinimumHeight(150)
        self.subtitle_output.setMinimumHeight(150)

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
        output_layout.addLayout(self._build_output_panel("视频输出", self.video_output))
        output_layout.addLayout(self._build_output_panel("字幕输出", self.subtitle_output))
        root_layout.addLayout(output_layout, stretch=2)

        self.setCentralWidget(root)

    @staticmethod
    def _build_output_panel(title: str, text_area: QPlainTextEdit) -> QVBoxLayout:
        """构建带标题的输出区域。"""

        layout = QVBoxLayout()
        label = QLabel(title)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(label)
        layout.addWidget(text_area)
        return layout
