"""
串口快速连接对话框 - 无需创建资产即可打开串口终端
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QPushButton, QListWidget, QListWidgetItem,
    QLabel, QMenu, QMessageBox, QWidget,
)

try:
    from serial.tools import list_ports
except Exception:
    list_ports = None

from PySide6.QtCore import Qt
from core import db


class SerialQuickDialog(QDialog):
    """串口快速连接对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("串口快速连接")
        self.setMinimumWidth(460)
        self.setMinimumHeight(420)
        self._result_config = None
        self._setup_ui()
        self._load_sessions()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 参数配置区
        form = QFormLayout()

        # 串口端口
        port_widget = QWidget()
        port_layout = QHBoxLayout(port_widget)
        port_layout.setContentsMargins(0, 0, 0, 0)
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setInsertPolicy(QComboBox.NoInsert)
        self._load_ports()
        port_layout.addWidget(self.port_combo)
        refresh_btn = QPushButton("⟳")
        refresh_btn.setFixedWidth(36)
        refresh_btn.setFixedHeight(32)
        refresh_btn.setToolTip("刷新串口列表")
        refresh_btn.clicked.connect(self._load_ports)
        port_layout.addWidget(refresh_btn)

        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.baud_combo.setEditable(True)
        self.baud_combo.setCurrentText("9600")

        self.data_bits_combo = QComboBox()
        self.data_bits_combo.addItems(["5", "6", "7", "8"])
        self.data_bits_combo.setCurrentText("8")

        self.parity_combo = QComboBox()
        self.parity_combo.addItems(["N", "E", "O", "M", "S"])
        self.parity_combo.setCurrentText("N")

        self.stop_bits_combo = QComboBox()
        self.stop_bits_combo.addItems(["1", "2"])
        self.stop_bits_combo.setCurrentText("1")

        self.flow_combo = QComboBox()
        self.flow_combo.addItems(["none", "xonxoff", "rtscts", "dsrdtr"])
        self.flow_combo.setCurrentText("none")

        form.addRow("串口端口:", port_widget)
        form.addRow("波特率:", self.baud_combo)
        form.addRow("数据位:", self.data_bits_combo)
        form.addRow("校验位:", self.parity_combo)
        form.addRow("停止位:", self.stop_bits_combo)
        form.addRow("流控:", self.flow_combo)
        layout.addLayout(form)

        # 最近使用列表
        layout.addWidget(QLabel("最近使用:"))
        self.session_list = QListWidget()
        self.session_list.setMinimumHeight(140)
        self.session_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self._on_context_menu)
        self.session_list.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.session_list)

        # 按钮
        btn_layout = QHBoxLayout()
        self.connect_btn = QPushButton("连接")
        self.connect_btn.setDefault(True)
        self.connect_btn.clicked.connect(self._on_connect)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.connect_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _load_ports(self):
        if list_ports is None:
            return
        current = self.port_combo.currentText()
        self.port_combo.clear()
        for p in list_ports.comports():
            self.port_combo.addItem(p.device)
        if current:
            self.port_combo.setCurrentText(current)

    def _load_sessions(self):
        self.session_list.clear()
        sessions = db.get_quick_sessions()
        for s in sessions:
            cfg = s["config"]
            port = cfg.get("serial_port", "")
            baud = cfg.get("baud_rate", 9600)
            data_bits = cfg.get("data_bits", 8)
            parity = cfg.get("parity", "N")
            stop_bits = cfg.get("stop_bits", 1)
            params = f"{baud}-{data_bits}{parity}{stop_bits}"
            fav = "★ " if s["is_favorite"] else "  "
            last = s.get("last_used", "")
            text = f"{fav}{port}  {params}    {last}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, s)
            self.session_list.addItem(item)

    def _on_double_click(self, item):
        session = item.data(Qt.UserRole)
        if not session:
            return
        cfg = session["config"]
        self.port_combo.setCurrentText(cfg.get("serial_port", ""))
        self.baud_combo.setCurrentText(str(cfg.get("baud_rate", 9600)))
        self.data_bits_combo.setCurrentText(str(cfg.get("data_bits", 8)))
        self.parity_combo.setCurrentText(cfg.get("parity", "N"))
        self.stop_bits_combo.setCurrentText(str(cfg.get("stop_bits", 1)))
        self.flow_combo.setCurrentText(cfg.get("flow_control", "none"))

    def _on_context_menu(self, pos):
        item = self.session_list.itemAt(pos)
        if not item:
            return
        session = item.data(Qt.UserRole)
        if not session:
            return

        menu = QMenu(self)
        if session["is_favorite"]:
            fav_act = menu.addAction("取消收藏")
        else:
            fav_act = menu.addAction("收藏")
        del_act = menu.addAction("删除")

        action = menu.exec_(self.session_list.viewport().mapToGlobal(pos))
        if action == fav_act:
            db.update_quick_session_favorite(
                session["id"], not session["is_favorite"]
            )
            self._load_sessions()
        elif action == del_act:
            db.delete_quick_session(session["id"])
            self._load_sessions()

    def _on_connect(self):
        port = self.port_combo.currentText().strip()
        if not port:
            QMessageBox.warning(self, "提示", "请选择或输入串口端口")
            return
        try:
            baud = int(self.baud_combo.currentText())
        except ValueError:
            QMessageBox.warning(self, "提示", "波特率必须是数字")
            return
        self._result_config = {
            "serial_port": port,
            "baud_rate": baud,
            "data_bits": int(self.data_bits_combo.currentText()),
            "parity": self.parity_combo.currentText(),
            "stop_bits": int(self.stop_bits_combo.currentText()),
            "flow_control": self.flow_combo.currentText(),
        }
        # 自动保存到最近使用
        db.add_quick_session(
            name=f"Serial-{port}",
            config=self._result_config,
        )
        self.accept()

    def get_config(self):
        return self._result_config
