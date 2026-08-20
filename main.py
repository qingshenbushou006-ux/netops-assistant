#!/usr/bin/env python3
"""
NetOps Assistant - 网络运维资产管理工具
主入口
"""
import sys
import os

# 将项目根目录加入 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ui.main_window import MainWindow


def main():
    # 高 DPI 支持 - 使用四舍五入策略避免缩放后控件被截断
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor
    )

    app = QApplication(sys.argv)

    # 全局字体
    font = QFont("Microsoft YaHei", 9)
    font.setStyleHint(QFont.SansSerif)
    app.setFont(font)

    # 创建主窗口
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
