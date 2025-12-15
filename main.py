"""JAVTransl 图形界面的入口模块。"""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from gui import MainWindow


def main() -> None:
    """启动 Qt 事件循环并展示主窗口。"""

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
