"""
终端 Widget - 嵌入式 SSH 终端
使用 pyte 模拟终端 + QPlainTextEdit 显示
"""
import re
import os
import threading
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QLabel, QPushButton, QTabWidget, QLineEdit, QSplitter,
    QMenu, QApplication,
)
from PySide6.QtCore import Qt, Signal, QTimer, QThread, QEvent
from PySide6.QtGui import QFont, QTextCursor, QColor, QPalette, QKeyEvent, QInputMethodEvent, QShortcut, QKeySequence, QTextDocument, QTextCharFormat

from core.ssh_manager import SSHConnection
from core.serial_manager import SerialConnection
from core.telnet_manager import TelnetConnection
from core.ansi_parser import AnsiParser
from core import db


class ConnectWorker(QThread):
    """后台连接线程"""
    result = Signal(bool, str)  # success, message

    def __init__(self, conn):
        super().__init__()
        self.conn = conn

    def run(self):
        success, msg = self.conn.connect()
        self.result.emit(success, msg)


class TerminalView(QPlainTextEdit):
    """终端显示控件"""

    command_entered = Signal(str)  # 用户输入的命令
    _flush_signal = Signal()  # 内部信号：刷新缓冲区

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(False)
        self.setUndoRedoEnabled(False)

        # 终端样式
        self._current_font_size = 13
        # 字体族列表：用户可在右键菜单切换
        self._available_fonts = [
            "Consolas",          # Windows 默认
            "Cascadia Code",     # Windows Terminal 默认
            "Cascadia Mono",     # Windows 新版
            "JetBrains Mono",    # 跨平台
            "Fira Code",         # 跨平台
            "Source Code Pro",   # 跨平台
            "Menlo",             # macOS
            "Monaco",            # macOS
            "Courier New",       # 通用兜底
        ]
        self._current_font_family = "Consolas"
        self._apply_font()

        # 深色主题
        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: none;
                padding: 8px;
                selection-background-color: #45475a;
            }
        """)

        self._conn = None
        self._connected = False

        # 安装事件过滤器，在 Qt 内部处理之前拦截 Backspace/Delete/Tab
        self.installEventFilter(self)

        # ANSI 颜色解析器（维护跨片段的颜色状态）
        self._ansi_parser = AnsiParser()

        # 输出缓冲区：list of (text, QTextCharFormat) 片段
        self._output_buffer = []  # list[tuple[str, QTextCharFormat]]
        self._buffer_lock = threading.Lock()
        self._cursor_col = 0  # 虚拟光标列位置（用于退格/覆盖写入）
        self._prompt_col = 0  # 提示符结束列（退格不能删到此列之前）
        self._flush_signal.connect(self._flush_buffer, Qt.QueuedConnection)
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(50)
        self._flush_timer.timeout.connect(self._flush_buffer)
        self._flush_timer.start()

        # 限制终端最大行数，防止内存暴涨
        self._max_lines = 5000

    def set_connection(self, conn):
        """绑定终端连接"""
        self._conn = conn
        self._connected = conn is not None

    def append_output(self, text):
        """追加输出（线程安全，缓冲后由主线程刷新）"""
        segments = self._ansi_parser.parse(text)
        if not segments:
            return
        with self._buffer_lock:
            self._output_buffer.extend(segments)
        self._flush_signal.emit()

    def _flush_buffer(self):
        """在主线程中刷新缓冲区到终端，支持退格/回车/覆盖写入"""
        with self._buffer_lock:
            if not self._output_buffer:
                return
            segments = self._output_buffer
            self._output_buffer = []

        doc = self.document()
        cursor = self.textCursor()

        for text, fmt in segments:
            for ch in text:
                if ch == '\b':
                    self._cursor_col = max(0, self._cursor_col - 1)
                elif ch == '\r':
                    self._cursor_col = 0
                elif ch == '\n':
                    self._cursor_col = 0
                    cursor.movePosition(QTextCursor.End)
                    cursor.insertText("\n")
                    self._prompt_col = 0  # 新行，提示符列重置
                elif ch == '\t':
                    self._write_text(cursor, "    ", fmt)
                elif ord(ch) >= 32:
                    self._write_text(cursor, ch, fmt)

        # 检测提示符：当前行以 > # $ ] ) : 结尾时，标记为提示符结束位置
        last_block = doc.lastBlock()
        line = last_block.text().rstrip()
        if line and line[-1] in ('>', '#', '$', ']', ')', ':'):
            self._prompt_col = len(line)

        # 限制行数
        if doc.blockCount() > self._max_lines:
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor,
                                doc.blockCount() - self._max_lines)
            cursor.removeSelectedText()

        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _write_text(self, cursor, text, fmt=None):
        """按虚拟光标位置写入文本，支持覆盖"""
        doc = self.document()
        col = self._cursor_col

        for ch in text:
            last_block = doc.lastBlock()
            line_text = last_block.text()

            if col < len(line_text):
                # 覆盖：选中该位置字符，替换
                pos = last_block.position() + col
                cursor.setPosition(pos)
                cursor.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)
                if fmt:
                    cursor.insertText(ch, fmt)
                else:
                    cursor.insertText(ch)
            else:
                # 追加：先补空格到光标位置，再插入
                cursor.movePosition(QTextCursor.End)
                gap = col - len(line_text)
                if gap > 0:
                    cursor.insertText(" " * gap)
                if fmt:
                    cursor.insertText(ch, fmt)
                else:
                    cursor.insertText(ch)
            col += 1

        self._cursor_col = col

    def _send_and_broadcast(self, data):
        """发送按键到当前连接，并在 MultiExec 模式下广播"""
        # 行尾模式替换
        send_data = data
        parent_tab = self._find_parent_tab()
        if data == "\r" and parent_tab:
            send_data = parent_tab._line_ending
        self._conn.send_keys(send_data)
        self._broadcast_key(send_data)
        # 本地回显
        if parent_tab and parent_tab._local_echo:
            display = "\n" if data == "\r" else data
            self.append_output(display)

    def keyPressEvent(self, event: QKeyEvent):
        """捕获键盘输入，转发到终端连接"""
        if not self._connected or not self._conn:
            super().keyPressEvent(event)
            return

        key = event.key()
        text = event.text()
        modifiers = event.modifiers()

        if key == Qt.Key_Return or key == Qt.Key_Enter:
            self._send_and_broadcast("\r")
            return
        # Backspace/Delete/Tab 已在 event() 中处理，不会到达这里
        # Ctrl+Shift+C/V/A 必须在 Ctrl+C 之前检查
        if key == Qt.Key_C and modifiers & Qt.ControlModifier and modifiers & Qt.ShiftModifier:
            self._copy_selection()
            return
        if key == Qt.Key_V and modifiers & Qt.ControlModifier and modifiers & Qt.ShiftModifier:
            self._paste_to_terminal()
            return
        if key == Qt.Key_A and modifiers & Qt.ControlModifier and modifiers & Qt.ShiftModifier:
            self.selectAll()
            return
        if key == Qt.Key_F and modifiers & Qt.ControlModifier:
            self._request_find()
            return
        if key in (Qt.Key_Plus, Qt.Key_Equal) and modifiers & Qt.ControlModifier:
            self._zoom_in()
            return
        if key == Qt.Key_Minus and modifiers & Qt.ControlModifier:
            self._zoom_out()
            return
        if key == Qt.Key_0 and modifiers & Qt.ControlModifier:
            self._zoom_reset()
            return
        if key == Qt.Key_C and modifiers & Qt.ControlModifier:
            self._send_and_broadcast("\x03")
            return
        if key == Qt.Key_D and modifiers & Qt.ControlModifier:
            self._send_and_broadcast("\x04")
            return
        if key == Qt.Key_Z and modifiers & Qt.ControlModifier:
            self._send_and_broadcast("\x1a")
            return
        if key == Qt.Key_L and modifiers & Qt.ControlModifier:
            self._send_and_broadcast("\x0c")
            return
        if key == Qt.Key_Up:
            self._send_and_broadcast("\x1b[A")
            return
        if key == Qt.Key_Down:
            self._send_and_broadcast("\x1b[B")
            return
        if key == Qt.Key_Left:
            self._send_and_broadcast("\x1b[D")
            return
        if key == Qt.Key_Right:
            self._send_and_broadcast("\x1b[C")
            return
        if key == Qt.Key_Home:
            self._send_and_broadcast("\x1b[H")
            return
        if key == Qt.Key_End:
            self._send_and_broadcast("\x1b[F")
            return
        if key == Qt.Key_PageUp:
            self._send_and_broadcast("\x1b[5~")
            return
        if key == Qt.Key_PageDown:
            self._send_and_broadcast("\x1b[6~")
            return
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            super().keyPressEvent(event)
            return
        if text and text.isprintable() and ord(text[0]) >= 32:
            self._send_and_broadcast(text)
            return
        if text == "\t":
            self._send_and_broadcast(text)
            return
        event.accept()

    def inputMethodEvent(self, event: QInputMethodEvent):
        if not self._connected or not self._conn:
            super().inputMethodEvent(event)
            return

        commit = event.commitString()
        if commit:
            self._send_and_broadcast(commit)
        event.accept()

    def inputMethodQuery(self, query):
        if query == Qt.ImEnabled:
            return True
        return super().inputMethodQuery(query)

    def eventFilter(self, obj, event):
        """在 Qt 内部处理之前拦截按键，确保 Backspace/Delete/Tab 不被 QPlainTextEdit 消耗"""
        if obj is self and getattr(self, '_connected', False) and getattr(self, '_conn', None):
            if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
                key = event.key()
                if key == Qt.Key_Backspace:
                    # 发送退格到远程设备
                    self._send_and_broadcast("\x08")
                    # 本地也处理退格（设备可能不回显退格）
                    self._local_backspace()
                    return True
                if key == Qt.Key_Delete:
                    self._send_and_broadcast("\x1b[3~")
                    return True
                if key == Qt.Key_Tab:
                    self._send_and_broadcast("\t")
                    return True
        return super().eventFilter(obj, event)

    def _local_backspace(self):
        """本地处理退格：删除虚拟光标前一个字符（保护提示符区域）"""
        # 不能删到提示符之前
        if self._cursor_col <= self._prompt_col:
            return

        doc = self.document()
        last_block = doc.lastBlock()
        line_text = last_block.text()

        if self._cursor_col > 0 and len(line_text) > 0:
            del_pos = min(self._cursor_col - 1, len(line_text) - 1)
            abs_pos = last_block.position() + del_pos
            cursor = self.textCursor()
            cursor.setPosition(abs_pos)
            cursor.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)
            cursor.removeSelectedText()
            self._cursor_col = max(0, self._cursor_col - 1)

    def event(self, event):
        if not getattr(self, '_connected', False) or not getattr(self, '_conn', None):
            return super().event(event)
        # 拦截 ShortcutOverride 防止 Qt 将 Backspace/Delete/Tab 当快捷键处理
        if event.type() == QEvent.ShortcutOverride and isinstance(event, QKeyEvent):
            if event.key() in (Qt.Key_Backspace, Qt.Key_Delete, Qt.Key_Tab):
                event.accept()
                return True
        return super().event(event)

    # ── 右键菜单 ──

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        copy_act = menu.addAction("复制 (Ctrl+Shift+C)")
        copy_act.triggered.connect(self._copy_selection)

        paste_act = menu.addAction("粘贴 (Ctrl+Shift+V)")
        paste_act.triggered.connect(self._paste_to_terminal)

        menu.addSeparator()

        select_all_act = menu.addAction("全选 (Ctrl+Shift+A)")
        select_all_act.triggered.connect(self.selectAll)

        find_act = menu.addAction("查找 (Ctrl+F)")
        find_act.triggered.connect(self._request_find)

        menu.addSeparator()

        clear_act = menu.addAction("清屏")
        clear_act.triggered.connect(self._clear_screen)

        # 会话日志
        parent_tab = self._find_parent_tab()
        if parent_tab:
            menu.addSeparator()
            log_act = menu.addAction("停止日志" if parent_tab._log_active else "开始日志")
            log_act.triggered.connect(parent_tab.toggle_logging)

            # 串口信息（仅串口连接）
            if parent_tab.asset.get("protocol") == "serial":
                menu.addSeparator()
                serial_info = (
                    f"串口: {parent_tab.asset.get('serial_port', '')} | "
                    f"{parent_tab.asset.get('baud_rate', 9600)} "
                    f"{parent_tab.asset.get('data_bits', 8)}"
                    f"{parent_tab.asset.get('parity', 'N')}"
                    f"{parent_tab.asset.get('stop_bits', 1)}"
                )
                info_act = menu.addAction(serial_info)
                info_act.setEnabled(False)

                # 可用串口列表
                from core.serial_manager import get_available_ports
                ports = get_available_ports()
                if ports:
                    ports_menu = menu.addMenu("可用串口")
                    for p in ports:
                        port_act = ports_menu.addAction(f"{p['device']} - {p['description']}")
                        port_act.setEnabled(False)

                # 发送 Break 信号
                if parent_tab.is_connected():
                    break_act = menu.addAction("发送 Break 信号")
                    break_act.triggered.connect(lambda: parent_tab._conn.send_break())

                # 行尾模式子菜单
                le_menu = menu.addMenu("行尾模式")
                le_modes = [("CR", "cr"), ("LF", "lf"), ("CRLF", "crlf")]
                current_le = parent_tab._line_ending
                for label, mode in le_modes:
                    act = le_menu.addAction(label)
                    act.setCheckable(True)
                    act.setChecked(
                        (mode == "cr" and current_le == "\r") or
                        (mode == "lf" and current_le == "\n") or
                        (mode == "crlf" and current_le == "\r\n")
                    )
                    act.triggered.connect(lambda checked=False, m=mode: parent_tab.set_line_ending(m))

                # 本地回显
                echo_act = menu.addAction("本地回显")
                echo_act.setCheckable(True)
                echo_act.setChecked(parent_tab._local_echo)
                echo_act.triggered.connect(lambda checked: parent_tab.set_local_echo(checked))

                # 保存为资产（仅快速会话）
                if parent_tab._is_quick_session():
                    save_act = menu.addAction("保存为资产")
                    save_act.triggered.connect(parent_tab.save_as_asset)

            # 编码子菜单
            enc_menu = menu.addMenu("编码")
            for enc in ["UTF-8", "GBK", "Latin-1", "Big5", "EUC-JP"]:
                act = enc_menu.addAction(enc)
                act.triggered.connect(lambda checked=False, e=enc.lower(): parent_tab.set_encoding(e))

            # 字体子菜单
            font_menu = menu.addMenu("字体")
            available_fonts = self.get_available_fonts()
            current_font = self.get_font_family()
            for fname in available_fonts:
                fact = font_menu.addAction(fname)
                fact.setCheckable(True)
                fact.setChecked(fname == current_font)
                fact.triggered.connect(lambda checked=False, f=fname: self.set_font_family(f))
            # 字号
            size_menu = font_menu.addMenu("字号")
            for size in [10, 12, 13, 14, 16, 18, 20, 24]:
                sact = size_menu.addAction(f"{size}pt")
                sact.setCheckable(True)
                sact.setChecked(size == self._current_font_size)
                sact.triggered.connect(lambda checked=False, s=size: self._set_font_size(s))

            # SFTP（仅 SSH 连接可用）
            if parent_tab.is_connected() and hasattr(parent_tab._conn, 'client') and parent_tab._conn.client:
                menu.addSeparator()
                sftp_act = menu.addAction("SFTP 文件传输")
                sftp_act.triggered.connect(lambda: self._open_sftp_from_tab(parent_tab))

        menu.exec_(event.globalPos())

    def _copy_selection(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            QApplication.clipboard().setText(cursor.selectedText())

    def _paste_to_terminal(self):
        text = QApplication.clipboard().text()
        if text and self._conn and self._connected:
            self._conn.send_keys(text)

    def _request_find(self):
        """通知父级 TerminalTab 显示搜索栏"""
        parent = self._find_parent_tab()
        if parent and hasattr(parent, 'toggle_find_bar'):
            parent.toggle_find_bar()

    def _find_parent_tab(self):
        """向上查找父级 TerminalTab"""
        parent = self.parent()
        while parent and not isinstance(parent, TerminalTab):
            parent = parent.parent()
        return parent

    def _find_panel(self):
        """向上查找 TerminalPanel"""
        parent = self.parent()
        while parent:
            if isinstance(parent, TerminalPanel):
                return parent
            parent = parent.parent()
        return None

    def _broadcast_key(self, data):
        """MultiExec 模式下广播按键到其他标签"""
        panel = self._find_panel()
        if panel and panel.multi_exec_active:
            tab = self._find_parent_tab()
            exclude_id = tab.asset_id if tab else None
            panel.broadcast_keys(data, exclude_asset_id=exclude_id)

    def _clear_screen(self):
        self.clear()
        if self._conn and self._connected:
            self._conn.send_keys("\x0c")

    def _open_sftp_from_tab(self, tab):
        """从右键菜单打开 SFTP 对话框"""
        from ui.sftp_dialog import SFTPDialog
        dialog = SFTPDialog(tab._conn, self.window())
        dialog.exec()

    # ── 字体缩放 ──

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self._zoom_in()
            else:
                self._zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def _zoom_in(self):
        if self._current_font_size < 36:
            self._current_font_size += 1
            self._apply_font_size()

    def _zoom_out(self):
        if self._current_font_size > 8:
            self._current_font_size -= 1
            self._apply_font_size()

    def _zoom_reset(self):
        self._current_font_size = 13
        self._apply_font_size()

    def _apply_font_size(self):
        self._apply_font()

    def _apply_font(self):
        """应用当前字体族与大小"""
        font = QFont(self._current_font_family, self._current_font_size)
        font.setStyleHint(QFont.Monospace)
        self.setFont(font)

    def get_available_fonts(self):
        """返回当前系统已安装的字体列表"""
        from PySide6.QtGui import QFontDatabase
        installed = set(QFontDatabase.families())
        available = [f for f in self._available_fonts if f in installed]
        if not available:
            available = [self._current_font_family]
        return available

    def set_font_family(self, family):
        """切换字体族"""
        if family and family != self._current_font_family:
            self._current_font_family = family
            self._apply_font()

    def get_font_family(self):
        return self._current_font_family

    def _set_font_size(self, size):
        """直接设置字号（用于菜单）"""
        size = max(8, min(36, size))
        self._current_font_size = size
        self._apply_font()


class TerminalTab(QWidget):
    """单个终端标签页"""

    closed = Signal(int)  # asset_id
    _disconnect_signal = Signal()  # 线程安全：后台线程断开时触发

    def __init__(self, asset_data, parent=None):
        super().__init__(parent)
        self.asset = asset_data
        self.asset_id = asset_data["id"]
        self._conn = None
        self._worker = None
        self._destroyed = False
        # 自动重连
        self._reconnect_attempts = 0
        self._max_reconnect = 3
        # 会话日志
        self._log_file = None
        self._log_active = False
        # 串口增强
        self._line_ending = "\r"
        self._local_echo = False
        self._log_lock = threading.Lock()
        self._disconnect_signal.connect(self._handle_disconnect, Qt.QueuedConnection)
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._try_reconnect)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 状态栏
        self.status_bar = QWidget()
        self.status_bar.setFixedHeight(32)
        self.status_bar.setStyleSheet(
            "background-color: #181825; border-bottom: 1px solid #313244;"
        )
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(8, 4, 8, 4)

        self.status_label = QLabel(
            f"🔗 连接中... {self.asset['name']} ({self._connection_target()})"
        )
        self.status_label.setStyleSheet("color: #f9e2af; font-size: 12px;")
        status_layout.addWidget(self.status_label)

        status_layout.addStretch()

        disconnect_btn = QPushButton("✕ 断开")
        disconnect_btn.setFixedHeight(24)
        disconnect_btn.setMinimumWidth(70)
        disconnect_btn.setStyleSheet("""
            QPushButton {
                background-color: #45475a; color: #cdd6f4;
                border: none; border-radius: 3px; font-size: 11px;
                padding: 2px 8px;
            }
            QPushButton:hover { background-color: #f38ba8; }
        """)
        disconnect_btn.clicked.connect(self.disconnect)
        status_layout.addWidget(disconnect_btn)

        layout.addWidget(self.status_bar)

        # 搜索栏（默认隐藏）
        self._find_bar = QWidget()
        self._find_bar.setFixedHeight(36)
        self._find_bar.setStyleSheet(
            "background-color: #181825; border-bottom: 1px solid #313244;"
        )
        find_layout = QHBoxLayout(self._find_bar)
        find_layout.setContentsMargins(4, 4, 4, 4)
        find_layout.setSpacing(6)

        self._find_input = QLineEdit()
        self._find_input.setPlaceholderText("查找...")
        self._find_input.setFixedHeight(28)
        self._find_input.setStyleSheet("""
            QLineEdit {
                background-color: #313244; color: #cdd6f4;
                border: 1px solid #45475a; border-radius: 3px;
                padding: 4px 8px; font-size: 12px;
            }
        """)
        self._find_input.returnPressed.connect(self._find_next)
        find_layout.addWidget(self._find_input)

        find_prev_btn = QPushButton("▲")
        find_prev_btn.setFixedSize(28, 28)
        find_prev_btn.setStyleSheet("""
            QPushButton {
                background-color: #45475a; color: #cdd6f4;
                border: none; border-radius: 3px; font-size: 12px;
            }
            QPushButton:hover { background-color: #585b70; }
        """)
        find_prev_btn.clicked.connect(self._find_prev)
        find_layout.addWidget(find_prev_btn)

        find_next_btn = QPushButton("▼")
        find_next_btn.setFixedSize(28, 28)
        find_next_btn.setStyleSheet("""
            QPushButton {
                background-color: #45475a; color: #cdd6f4;
                border: none; border-radius: 3px; font-size: 12px;
            }
            QPushButton:hover { background-color: #585b70; }
        """)
        find_next_btn.clicked.connect(self._find_next)
        find_layout.addWidget(find_next_btn)

        self._find_count_label = QLabel("")
        self._find_count_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        find_layout.addWidget(self._find_count_label)

        find_close_btn = QPushButton("✕")
        find_close_btn.setFixedSize(28, 28)
        find_close_btn.setStyleSheet("""
            QPushButton {
                background-color: #45475a; color: #cdd6f4;
                border: none; border-radius: 3px; font-size: 12px;
            }
            QPushButton:hover { background-color: #f38ba8; }
        """)
        find_close_btn.clicked.connect(lambda: self._find_bar.setVisible(False))
        find_layout.addWidget(find_close_btn)

        self._find_bar.setVisible(False)
        layout.addWidget(self._find_bar)

        # 终端
        self.terminal = TerminalView()
        layout.addWidget(self.terminal)

        # 快捷命令栏
        cmd_layout = QHBoxLayout()
        cmd_layout.setContentsMargins(4, 2, 4, 2)

        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("输入命令后回车直接发送...")
        self.cmd_input.setFixedHeight(30)
        self.cmd_input.setStyleSheet("""
            QLineEdit {
                background-color: #313244; color: #cdd6f4;
                border: 1px solid #45475a; border-radius: 3px;
                padding: 4px 8px; font-size: 12px;
            }
        """)
        self.cmd_input.installEventFilter(self)
        self.cmd_input.returnPressed.connect(self._send_from_input)
        cmd_layout.addWidget(self.cmd_input)

        # 快捷按钮（左键填入命令，右键编辑）
        self._quick_btns = []
        self._quick_cmds = [
            ("Show Run", "show run"),
            ("Show IP", "show ip int br"),
            ("Config T", "conf t"),
            ("Exit", "exit"),
        ]
        # 命令模板按钮
        tpl_btn = QPushButton("模板")
        tpl_btn.setFixedHeight(26)
        tpl_btn.setMinimumWidth(50)
        tpl_btn.setToolTip("打开命令模板库")
        tpl_btn.setStyleSheet("""
            QPushButton {
                background-color: #585b70; color: #89b4fa;
                border: none; border-radius: 3px; font-size: 11px; font-weight: bold;
                padding: 2px 8px;
            }
            QPushButton:hover { background-color: #45475a; }
        """)
        tpl_btn.clicked.connect(self._open_template_dialog)
        cmd_layout.addWidget(tpl_btn)
        for label, cmd in self._quick_cmds:
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.setMinimumWidth(60)
            btn.setToolTip(f"左键: 填入命令\n右键: 编辑\n{cmd}")
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #45475a; color: #cdd6f4;
                    border: none; border-radius: 3px; font-size: 11px;
                    padding: 2px 8px;
                }
                QPushButton:hover { background-color: #585b70; }
            """)
            btn.clicked.connect(lambda checked=False, b=btn: self._fill_quick_cmd(b))
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda pos, b=btn: self._edit_quick_cmd(b))
            cmd_layout.addWidget(btn)
            self._quick_btns.append(btn)

        layout.addLayout(cmd_layout)

        # 自动连接
        QTimer.singleShot(100, self.connect_to_device)

    def _connection_target(self):
        if self.asset.get("protocol") == "serial":
            return self.asset.get("serial_port", "未配置串口")
        return self.asset.get("ip", "")

    def _connection_description(self):
        if self.asset.get("protocol") == "serial":
            return (
                f"{self.asset.get('serial_port', '')} | "
                f"{self.asset.get('baud_rate', 9600)} "
                f"{self.asset.get('data_bits', 8)}"
                f"{self.asset.get('parity', 'N')}"
                f"{self.asset.get('stop_bits', 1)}"
            )
        if self.asset.get("protocol") == "telnet":
            return f"{self.asset.get('ip', '')}:{self.asset.get('telnet_port', 23)}"
        return f"{self.asset.get('ip', '')}:{self.asset.get('port', 22)}"

    def connect_to_device(self):
        """建立终端连接"""
        if self._destroyed:
            return
        if self._conn and self._conn.connected:
            return

        protocol = self.asset.get("protocol", "ssh")
        if protocol == "serial":
            self._conn = SerialConnection(
                port=self.asset.get("serial_port", ""),
                baud_rate=self.asset.get("baud_rate", 9600),
                data_bits=self.asset.get("data_bits", 8),
                parity=self.asset.get("parity", "N"),
                stop_bits=self.asset.get("stop_bits", 1),
                flow_control=self.asset.get("flow_control", "none"),
            )
            self._conn.line_ending = self._line_ending
        elif protocol == "ssh":
            self._conn = SSHConnection(
                host=self.asset["ip"],
                port=self.asset.get("port", 22),
                username=self.asset.get("username", ""),
                password=self.asset.get("password", ""),
            )
        elif protocol == "telnet":
            self._conn = TelnetConnection(
                host=self.asset["ip"],
                port=self.asset.get("telnet_port", 23),
                username=self.asset.get("username", ""),
                password=self.asset.get("password", ""),
            )
        else:
            self._conn = None
            self.status_label.setText(f"🟡 暂不支持 {self.asset['name']} ({protocol})")
            self.status_label.setStyleSheet("color: #f9e2af; font-size: 12px;")
            self.terminal.set_connection(None)
            self.terminal.append_output(f"✗ 暂未实现 {protocol.upper()} 终端连接\n")
            db.log_command(self.asset_id, "[LOGIN_UNSUPPORTED]", f"{protocol}未实现")
            return

        self._conn.set_output_callback(self._on_output)
        self._conn.set_disconnect_callback(self._on_disconnect)

        self.status_label.setText(
            f"🔗 连接中... {self.asset['name']} ({self._connection_target()})"
        )
        self.status_label.setStyleSheet("color: #f9e2af; font-size: 12px;")
        self.terminal.append_output(
            f"正在连接 {self._connection_description()} ...\n"
        )

        self._worker = ConnectWorker(self._conn)
        self._worker.result.connect(self._on_connected)
        self._worker.start()

    def _on_connected(self, success, msg):
        if self._destroyed:
            return
        protocol = self.asset.get("protocol", "ssh").upper()
        if success:
            self._reconnect_attempts = 0
            status_text = f"🟢 已连接 {self.asset['name']} ({self._connection_target()})"
            if self.asset.get("protocol") == "serial":
                status_text += f" [{self.asset.get('baud_rate', 9600)}-{self.asset.get('data_bits', 8)}{self.asset.get('parity', 'N')}{self.asset.get('stop_bits', 1)}]"
            self.status_label.setText(status_text)
            self.status_label.setStyleSheet("color: #a6e3a1; font-size: 12px;")
            self.terminal.set_connection(self._conn)
            self.terminal.append_output("✓ 连接成功\n")
            db.log_command(self.asset_id, "[LOGIN]", f"{protocol}连接成功")
            db.update_asset(self.asset_id, status="online")
        else:
            self._conn = None
            self.status_label.setText(
                f"🔴 连接失败 {self.asset['name']}"
            )
            self.status_label.setStyleSheet("color: #f38ba8; font-size: 12px;")
            self.terminal.set_connection(None)
            self.terminal.append_output(f"✗ 连接失败: {msg}\n")
            db.log_command(self.asset_id, "[LOGIN_FAIL]", msg)
            db.update_asset(self.asset_id, status="offline")

    def _on_output(self, text):
        self.terminal.append_output(text)
        with self._log_lock:
            if self._log_file:
                try:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    self._log_file.write(f"[{timestamp}] {text}")
                    self._log_file.flush()
                except Exception:
                    pass

    def _on_disconnect(self):
        """后台线程调用 - 仅触发信号，不操作 GUI"""
        self._disconnect_signal.emit()

    def _handle_disconnect(self):
        """主线程处理断开事件"""
        if self._destroyed:
            return
        self.terminal.set_connection(None)
        self._log_active = False
        with self._log_lock:
            if self._log_file:
                try:
                    self._log_file.close()
                except Exception:
                    pass
                self._log_file = None

        # 清理旧连接，避免重连时状态残留
        old_conn = self._conn
        self._conn = None
        if old_conn:
            try:
                old_conn.disconnect()
            except Exception:
                pass

        # 尝试自动重连
        if self._reconnect_attempts < self._max_reconnect:
            self._reconnect_attempts += 1
            delay = 2 ** self._reconnect_attempts
            self.status_label.setText(
                f"🟡 {delay}秒后重连... ({self._reconnect_attempts}/{self._max_reconnect}) {self.asset['name']}"
            )
            self.status_label.setStyleSheet("color: #f9e2af; font-size: 12px;")
            self.terminal.append_output(f"\n--- 连接断开，{delay}秒后尝试重连 ({self._reconnect_attempts}/{self._max_reconnect}) ---\n")
            self._reconnect_timer.start(delay * 1000)
        else:
            self.terminal.append_output("\n--- 连接已断开 ---\n")
            self.status_label.setText(
                f"🔴 已断开 {self.asset['name']}"
            )
            self.status_label.setStyleSheet("color: #f38ba8; font-size: 12px;")
            db.log_command(self.asset_id, "[DISCONNECT]", "连接断开")
            db.update_asset(self.asset_id, status="offline")

    def _try_reconnect(self):
        """尝试重连"""
        if self._destroyed or self._conn is None:
            return
        self.status_label.setText(
            f"🟡 正在重连... {self.asset['name']}"
        )
        self.status_label.setStyleSheet("color: #f9e2af; font-size: 12px;")
        self.connect_to_device()

    def _on_reconnected(self):
        """重连成功"""
        self._reconnect_attempts = 0
        self.status_label.setText(
            f"🟢 已重连 {self.asset['name']} ({self._connection_target()})"
        )
        self.status_label.setStyleSheet("color: #a6e3a1; font-size: 12px;")
        self.terminal.append_output("✓ 重连成功\n")

    def _send_from_input(self):
        """从底部输入框发送命令"""
        cmd = self.cmd_input.text().strip()
        if cmd and self._conn and self._conn.connected:
            self._conn.send_command(cmd)
            db.log_command(self.asset_id, cmd)
            self.cmd_input.clear()

    def eventFilter(self, obj, event):
        """拦截 cmd_input 回车键，发送命令到远程设备"""
        if obj is self.cmd_input and event.type() == QEvent.KeyPress:
            if self._conn and self._conn.connected:
                key = event.key()
                # 回车：发送命令文本 + 回车到远程，清空输入框
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    cmd = self.cmd_input.text()
                    if cmd:
                        self._conn.send_keys(cmd)
                        try:
                            db.log_command(self.asset_id, cmd)
                        except Exception:
                            pass
                    self._conn.send_keys(self._line_ending)
                    self.cmd_input.clear()
                    return True
        return super().eventFilter(obj, event)

    def _fill_quick_cmd(self, btn):
        """左键点击：直接发送命令到远程设备"""
        idx = self._quick_btns.index(btn)
        _, cmd = self._quick_cmds[idx]
        if cmd and self._conn and self._conn.connected:
            self._conn.send_keys(cmd + self._line_ending)
            try:
                db.log_command(self.asset_id, cmd)
            except Exception:
                pass

    def _edit_quick_cmd(self, btn):
        """右键点击：编辑按钮标签和命令"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QDialogButtonBox
        idx = self._quick_btns.index(btn)
        old_label, old_cmd = self._quick_cmds[idx]

        dlg = QDialog(self)
        dlg.setWindowTitle("编辑快捷按钮")
        dlg.setMinimumWidth(300)

        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel("按钮名称:"))
        label_edit = QLineEdit(old_label)
        layout.addWidget(label_edit)

        layout.addWidget(QLabel("发送命令:"))
        cmd_edit = QLineEdit(old_cmd)
        layout.addWidget(cmd_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() == QDialog.Accepted:
            new_label = label_edit.text().strip()
            new_cmd = cmd_edit.text()
            if new_label:
                self._quick_cmds[idx] = (new_label, new_cmd)
                btn.setText(new_label)
                btn.setToolTip(f"左键: 直接发送\n右键: 编辑\n{new_cmd}")

    def _send_quick_cmd(self, cmd):
        """发送快捷命令"""
        if self._conn and self._conn.connected:
            self._conn.send_command(cmd)
            db.log_command(self.asset_id, cmd)

    def _open_template_dialog(self):
        """打开命令模板对话框"""
        from ui.template_dialog import TemplateDialog
        def send_cmd(cmd):
            if self._conn and self._conn.connected:
                self._conn.send_keys(cmd + self._line_ending)
                try:
                    db.log_command(self.asset_id, cmd)
                except Exception:
                    pass
        dialog = TemplateDialog(self, send_callback=send_cmd)
        dialog.exec()

    def disconnect(self):
        """手动断开"""
        self._destroyed = True
        self._reconnect_timer.stop()
        self.stop_logging()
        if self._conn and self._conn.connected:
            self._conn.disconnect()
        elif self._conn:
            self._handle_disconnect()

    def is_connected(self):
        return self._conn and self._conn.connected

    def _is_quick_session(self):
        return self.asset_id < 0

    # ── 搜索栏 ──

    def toggle_find_bar(self):
        visible = not self._find_bar.isVisible()
        self._find_bar.setVisible(visible)
        if visible:
            self._find_input.setFocus()
            self._find_input.selectAll()

    def _find_next(self):
        keyword = self._find_input.text()
        if not keyword:
            return
        doc = self.terminal.document()
        cursor = self.terminal.textCursor()
        # 从当前位置往后找
        found = doc.find(keyword, cursor)
        if found.isNull():
            # 从头开始找
            found = doc.find(keyword, 0)
        if not found.isNull():
            self.terminal.setTextCursor(found)
            self._find_count_label.setText("")
        else:
            self._find_count_label.setText("未找到")

    def _find_prev(self):
        keyword = self._find_input.text()
        if not keyword:
            return
        doc = self.terminal.document()
        cursor = self.terminal.textCursor()
        # 从当前位置往前找
        found = doc.find(keyword, cursor, QTextDocument.FindBackward)
        if found.isNull():
            # 从末尾开始找
            cursor.movePosition(QTextCursor.End)
            found = doc.find(keyword, cursor, QTextDocument.FindBackward)
        if not found.isNull():
            self.terminal.setTextCursor(found)
            self._find_count_label.setText("")
        else:
            self._find_count_label.setText("未找到")

    # ── 会话日志 ──

    def toggle_logging(self):
        """切换会话日志记录"""
        if self._log_active:
            self.stop_logging()
        else:
            self.start_logging()

    def start_logging(self):
        """开始记录会话日志"""
        if self._log_active:
            return
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
        os.makedirs(log_dir, exist_ok=True)
        target = self._connection_target().replace(":", "_").replace("\\", "_").replace("/", "_")
        filename = f"{target}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        filepath = os.path.join(log_dir, filename)
        try:
            self._log_file = open(filepath, "w", encoding="utf-8")
            self._log_active = True
            self.terminal.append_output(f"[日志] 开始记录到 {filepath}\n")
        except Exception as e:
            self.terminal.append_output(f"[日志] 无法创建日志文件: {e}\n")

    def stop_logging(self):
        """停止记录会话日志"""
        if not self._log_active:
            return
        self._log_active = False
        with self._log_lock:
            if self._log_file:
                try:
                    self._log_file.close()
                except Exception:
                    pass
                self._log_file = None
        self.terminal.append_output("[日志] 已停止记录\n")

    # ── 编码切换 ──

    def set_encoding(self, encoding):
        """切换终端编码"""
        if self._conn:
            self._conn.encoding = encoding
            self.terminal.append_output(f"[编码] 已切换到 {encoding}\n")

    def set_line_ending(self, mode):
        """切换行尾模式: cr, lf, crlf"""
        mapping = {"cr": "\r", "lf": "\n", "crlf": "\r\n"}
        self._line_ending = mapping.get(mode, "\r")
        if self._conn and hasattr(self._conn, 'line_ending'):
            self._conn.line_ending = self._line_ending
        labels = {"cr": "CR", "lf": "LF", "crlf": "CRLF"}
        self.terminal.append_output(f"[行尾] 已切换到 {labels.get(mode, 'CR')}\n")

    def set_local_echo(self, enabled):
        """切换本地回显"""
        self._local_echo = enabled
        state = "开启" if enabled else "关闭"
        self.terminal.append_output(f"[回显] 本地回显已{state}\n")

    def save_as_asset(self):
        """将快速会话保存为资产"""
        if not self._is_quick_session():
            return
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "保存为资产", "设备名称:",
            text=self.asset.get("name", "")
        )
        if not ok or not name.strip():
            return
        asset_data = {
            "name": name.strip(),
            "group_id": 1,
            "protocol": "serial",
            "serial_port": self.asset.get("serial_port", ""),
            "baud_rate": self.asset.get("baud_rate", 9600),
            "data_bits": self.asset.get("data_bits", 8),
            "parity": self.asset.get("parity", "N"),
            "stop_bits": self.asset.get("stop_bits", 1),
            "flow_control": self.asset.get("flow_control", "none"),
        }
        new_id = db.add_asset(**asset_data)
        if new_id:
            self.asset_id = new_id
            self.asset["id"] = new_id
            self.asset["name"] = name.strip()
            self.terminal.append_output(f"[资产] 已保存为 \"{name.strip()}\" (ID: {new_id})\n")


class TerminalPanel(QWidget):
    """终端面板 - 右侧多标签终端"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tabs = {}  # asset_id -> TerminalTab
        self.multi_exec_active = False
        self._quick_session_counter = 0  # 负数 ID 计数器
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)

        # 欢迎页
        self.welcome = QLabel(
            "  ┌───────────────────────────────────────────────┐\n"
            "  │           NetOps Assistant v1.0               │\n"
            "  │                                               │\n"
            "  │   双击左侧设备即可自动连接                     │\n"
            "  │   支持 SSH / Telnet / Serial                  │\n"
            "  │   支持 Cisco / Huawei / H3C / Linux           │\n"
            "  │                                               │\n"
            "  │   快捷键:                                     │\n"
            "  │     Ctrl+C        中断                        │\n"
            "  │     Ctrl+D        退出                        │\n"
            "  │     Ctrl+L        清屏                        │\n"
            "  │     Ctrl+F        搜索                        │\n"
            "  │     Ctrl+滚轮     字体缩放                    │\n"
            "  │     Ctrl+Shift+C  复制                        │\n"
            "  │     Ctrl+Shift+V  粘贴                        │\n"
            "  │     Ctrl+Shift+M  多会话广播                  │\n"
            "  │     ↑/↓           命令历史                    │\n"
            "  │     Tab           自动补全                    │\n"
            "  └───────────────────────────────────────────────┘\n"
        )
        self.welcome.setStyleSheet("""
            color: #a6adc8; font-family: Consolas, monospace;
            font-size: 13px; padding: 40px;
        """)
        self.welcome.setAlignment(Qt.AlignCenter)

        self.tab_widget.addTab(self.welcome, "欢迎")
        layout.addWidget(self.tab_widget)

    def open_terminal(self, asset_data):
        """打开设备终端（如已打开则切换）"""
        asset_id = asset_data["id"]

        # 如果已有标签，切换过去
        if asset_id in self._tabs:
            tab = self._tabs[asset_id]
            idx = self.tab_widget.indexOf(tab)
            if idx >= 0:
                self.tab_widget.setCurrentIndex(idx)
                # 如果已断开，重新连接
                if not tab.is_connected():
                    tab.connect_to_device()
            return

        # 移除欢迎页
        if self.welcome:
            self.tab_widget.removeTab(0)
            self.welcome = None

        # 创建新标签
        tab = TerminalTab(asset_data)
        self._tabs[asset_id] = tab

        # 标签名：设备名
        name = asset_data["name"]
        if len(name) > 15:
            name = name[:12] + "..."

        prefix = "🔌" if asset_data.get("protocol") == "serial" else "🖥"
        idx = self.tab_widget.addTab(tab, f"{prefix} {name}")
        self.tab_widget.setCurrentIndex(idx)
        tooltip = asset_data.get("serial_port") if asset_data.get("protocol") == "serial" else asset_data.get("ip")
        self.tab_widget.setTabToolTip(
            idx, f"{asset_data['name']} ({tooltip})"
        )

    def open_quick_terminal(self, config):
        """打开串口快速会话（无需创建资产）"""
        self._quick_session_counter -= 1
        neg_id = self._quick_session_counter
        port = config.get("serial_port", "")
        asset_data = {
            "id": neg_id,
            "name": f"Serial-{port}",
            "protocol": "serial",
            "serial_port": port,
            "baud_rate": config.get("baud_rate", 9600),
            "data_bits": config.get("data_bits", 8),
            "parity": config.get("parity", "N"),
            "stop_bits": config.get("stop_bits", 1),
            "flow_control": config.get("flow_control", "none"),
        }
        self.open_terminal(asset_data)

    def _close_tab(self, index):
        """关闭标签"""
        widget = self.tab_widget.widget(index)
        if isinstance(widget, TerminalTab):
            widget.disconnect()
            if widget.asset_id in self._tabs:
                del self._tabs[widget.asset_id]
        self.tab_widget.removeTab(index)

        # 没有标签时显示欢迎页
        if self.tab_widget.count() == 0:
            self._show_welcome()

    def _show_welcome(self):
        self.welcome = QLabel(
            "  ┌─────────────────────────────────────────┐\n"
            "  │         双击左侧设备开始连接             │\n"
            "  └─────────────────────────────────────────┘\n"
        )
        self.welcome.setStyleSheet("""
            color: #a6adc8; font-family: Consolas, monospace;
            font-size: 13px; padding: 40px;
        """)
        self.welcome.setAlignment(Qt.AlignCenter)
        self.tab_widget.addTab(self.welcome, "欢迎")

    def disconnect_all(self):
        """断开所有连接"""
        for tab in self._tabs.values():
            tab.disconnect()
        self._tabs.clear()

    def broadcast_keys(self, data, exclude_asset_id=None):
        """向所有已连接标签广播按键（MultiExec 模式）"""
        for asset_id, tab in self._tabs.items():
            if asset_id != exclude_asset_id and tab.is_connected():
                tab._conn.send_keys(data)
