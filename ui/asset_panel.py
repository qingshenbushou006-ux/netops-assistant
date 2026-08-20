"""
资产面板 - 左侧设备树
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLineEdit, QPushButton, QMenu, QMessageBox, QDialog, QFormLayout,
    QComboBox, QSpinBox, QTextEdit, QLabel, QInputDialog,
    QGroupBox, QScrollArea, QSizePolicy, QFrame,
)

try:
    from serial.tools import list_ports
except Exception:
    list_ports = None
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QIcon, QColor, QAction

from core import db
from core.scanner import scan_assets_batch


class ScanWorker(QThread):
    """后台扫描线程"""
    device_status = Signal(int, bool)  # asset_id, is_online
    finished = Signal()

    def __init__(self, assets):
        super().__init__()
        self.assets = assets

    def run(self):
        scan_assets_batch(self.assets, callback=lambda aid, ok: self.device_status.emit(aid, ok))
        self.finished.emit()


class AssetEditDialog(QDialog):
    """资产编辑对话框"""

    def __init__(self, parent=None, asset=None, groups=None):
        super().__init__(parent)
        self.asset = asset
        self.groups = groups or []
        self.setWindowTitle("编辑设备" if asset else "添加设备")
        self.setMinimumWidth(480)
        self.setMinimumHeight(500)
        self.setup_ui()

    def setup_ui(self):
        self.setStyleSheet("""
            QDialog { background-color: #1e1e2e; }
            QGroupBox {
                color: #cdd6f4;
                font-weight: 600;
                font-size: 14px;
                border: 1px solid #313244;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 10px;
                padding-bottom: 8px;
                padding-left: 12px;
                padding-right: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }
            QLabel { color: #a6adc8; font-size: 13px; }
            QLineEdit, QComboBox, QSpinBox, QTextEdit {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 6px 8px;
                font-size: 13px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus {
                border: 1px solid #4facfe;
            }
            QPushButton {
                background-color: #4facfe;
                color: #1e1e2e;
                border-radius: 6px;
                padding: 8px 24px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #00f2fe; }
            QPushButton#secondary {
                background-color: #313244;
                color: #cdd6f4;
            }
            QPushButton#secondary:hover { background-color: #45475a; }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        main_layout.addWidget(scroll)

        scroll_content = QWidget()
        scroll.setWidget(scroll_content)
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # ---- 基本信息 ----
        basic_group = QGroupBox("📋 基本信息")
        basic_form = QFormLayout(basic_group)
        basic_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        basic_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        basic_form.setSpacing(10)
        basic_form.setContentsMargins(8, 14, 8, 8)

        self.name_edit = QLineEdit(self.asset.get("name", "") if self.asset else "")
        self.vendor_edit = QLineEdit(self.asset.get("vendor", "") if self.asset else "")
        self.model_edit = QLineEdit(self.asset.get("model", "") if self.asset else "")

        self.group_combo = QComboBox()
        self.group_combo.addItem("未分组", None)
        for g in self.groups:
            self.group_combo.addItem(g["name"], g["id"])
        if self.asset and self.asset.get("group_id"):
            idx = self.group_combo.findData(self.asset["group_id"])
            if idx >= 0:
                self.group_combo.setCurrentIndex(idx)

        self.location_edit = QLineEdit(self.asset.get("location", "") if self.asset else "")
        self.tags_edit = QLineEdit(self.asset.get("tags", "") if self.asset else "")
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(60)
        if self.asset:
            self.notes_edit.setPlainText(self.asset.get("notes", ""))

        basic_form.addRow("设备名称 *", self.name_edit)
        basic_form.addRow("厂商", self.vendor_edit)
        basic_form.addRow("型号", self.model_edit)
        basic_form.addRow("分组", self.group_combo)
        basic_form.addRow("位置", self.location_edit)
        basic_form.addRow("标签", self.tags_edit)
        basic_form.addRow("备注", self.notes_edit)
        content_layout.addWidget(basic_group)

        # ---- 连接信息 ----
        conn_group = QGroupBox("🔌 连接信息")
        conn_form = QFormLayout(conn_group)
        conn_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        conn_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        conn_form.setSpacing(10)
        conn_form.setContentsMargins(8, 14, 8, 8)

        self.proto_combo = QComboBox()
        self.proto_combo.addItems(["ssh", "telnet", "serial"])
        self.proto_combo.currentTextChanged.connect(self._update_protocol_fields)
        if self.asset:
            idx = self.proto_combo.findText(self.asset.get("protocol", "ssh"))
            if idx >= 0:
                self.proto_combo.setCurrentIndex(idx)

        self.ip_edit = QLineEdit(self.asset.get("ip", "") if self.asset else "")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(int(self.asset.get("port", 22)) if self.asset else 22)

        self.username_edit = QLineEdit(self.asset.get("username", "") if self.asset else "")
        self.password_edit = QLineEdit(self.asset.get("password", "") if self.asset else "")
        self.password_edit.setEchoMode(QLineEdit.Password)

        conn_form.addRow("协议", self.proto_combo)
        conn_form.addRow("IP 地址", self.ip_edit)
        conn_form.addRow("SSH 端口", self.port_spin)
        conn_form.addRow("用户名", self.username_edit)
        conn_form.addRow("密码", self.password_edit)
        content_layout.addWidget(conn_group)

        # ---- 串口参数 ----
        self.serial_group = QGroupBox("🔧 串口参数")
        serial_form = QFormLayout(self.serial_group)
        serial_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        serial_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        serial_form.setSpacing(10)
        serial_form.setContentsMargins(8, 14, 8, 8)

        self.serial_port_combo = QComboBox()
        self.serial_port_combo.setEditable(True)
        self.serial_port_combo.setInsertPolicy(QComboBox.NoInsert)
        self._load_serial_ports()
        self.serial_port_combo.setCurrentText(self.asset.get("serial_port", "") if self.asset else "")

        serial_port_widget = QWidget()
        serial_port_layout = QHBoxLayout(serial_port_widget)
        serial_port_layout.setContentsMargins(0, 0, 0, 0)
        serial_port_layout.addWidget(self.serial_port_combo)
        serial_refresh_btn = QPushButton("⟳")
        serial_refresh_btn.setFixedWidth(36)
        serial_refresh_btn.setFixedHeight(32)
        serial_refresh_btn.setToolTip("刷新串口列表")
        serial_refresh_btn.clicked.connect(self._load_serial_ports)
        serial_port_layout.addWidget(serial_refresh_btn)

        self.baud_rate_combo = QComboBox()
        self.baud_rate_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.baud_rate_combo.setEditable(True)
        self.baud_rate_combo.setCurrentText(str(self.asset.get("baud_rate", 9600) if self.asset else 9600))

        self.data_bits_combo = QComboBox()
        self.data_bits_combo.addItems(["5", "6", "7", "8"])
        self.data_bits_combo.setCurrentText(str(self.asset.get("data_bits", 8) if self.asset else 8))

        self.parity_combo = QComboBox()
        self.parity_combo.addItems(["N", "E", "O", "M", "S"])
        self.parity_combo.setCurrentText(str(self.asset.get("parity", "N") if self.asset else "N"))

        self.stop_bits_combo = QComboBox()
        self.stop_bits_combo.addItems(["1", "2"])
        self.stop_bits_combo.setCurrentText(str(self.asset.get("stop_bits", 1) if self.asset else 1))

        self.flow_control_combo = QComboBox()
        self.flow_control_combo.addItems(["none", "xonxoff", "rtscts", "dsrdtr"])
        self.flow_control_combo.setCurrentText(self.asset.get("flow_control", "none") if self.asset else "none")

        serial_form.addRow("串口端口", serial_port_widget)
        serial_form.addRow("波特率", self.baud_rate_combo)
        serial_form.addRow("数据位", self.data_bits_combo)
        serial_form.addRow("校验位", self.parity_combo)
        serial_form.addRow("停止位", self.stop_bits_combo)
        serial_form.addRow("流控", self.flow_control_combo)
        content_layout.addWidget(self.serial_group)

        # ---- Telnet 参数 ----
        self.telnet_group = QGroupBox("📡 Telnet 参数")
        telnet_form = QFormLayout(self.telnet_group)
        telnet_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        telnet_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        telnet_form.setSpacing(10)
        telnet_form.setContentsMargins(8, 14, 8, 8)

        self.telnet_port_spin = QSpinBox()
        self.telnet_port_spin.setRange(1, 65535)
        self.telnet_port_spin.setValue(int(self.asset.get("telnet_port", 23)) if self.asset else 23)
        telnet_form.addRow("Telnet 端口", self.telnet_port_spin)
        content_layout.addWidget(self.telnet_group)

        content_layout.addStretch()

        self._update_protocol_fields(self.proto_combo.currentText())

        # ---- 按钮 ----
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.validate_and_accept)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        main_layout.addLayout(btn_layout)

    def _load_serial_ports(self):
        if list_ports is None:
            return
        current = self.serial_port_combo.currentText() if hasattr(self, "serial_port_combo") else ""
        self.serial_port_combo.clear()
        for port in list_ports.comports():
            self.serial_port_combo.addItem(port.device)
        if current:
            self.serial_port_combo.setCurrentText(current)

    def _update_protocol_fields(self, protocol):
        is_serial = protocol == "serial"
        is_telnet = protocol == "telnet"
        is_ssh = protocol == "ssh"

        # 动态显隐分组
        self.serial_group.setVisible(is_serial)
        self.telnet_group.setVisible(is_telnet)

        if is_serial:
            self.ip_edit.setPlaceholderText("串口资产可留空")
        else:
            self.ip_edit.setPlaceholderText("例如: 192.168.1.1")

        # SSH 默认端口提示
        if is_ssh and not self.asset:
            self.port_spin.setValue(22)
        elif is_telnet and not self.asset:
            self.telnet_port_spin.setValue(23)

    def validate_and_accept(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "提示", "请输入设备名称")
            return
        if self.proto_combo.currentText() == "serial":
            if not self.serial_port_combo.currentText().strip():
                QMessageBox.warning(self, "提示", "请输入串口端口")
                return
        elif not self.ip_edit.text().strip():
            QMessageBox.warning(self, "提示", "请输入 IP 地址")
            return
        self.accept()

    def get_data(self):
        protocol = self.proto_combo.currentText()
        data = {
            "name": self.name_edit.text().strip(),
            "ip": self.ip_edit.text().strip() if protocol != "serial" else "",
            "port": self.port_spin.value(),
            "protocol": protocol,
            "vendor": self.vendor_edit.text().strip(),
            "model": self.model_edit.text().strip(),
            "username": self.username_edit.text().strip(),
            "password": self.password_edit.text(),
            "serial_port": self.serial_port_combo.currentText().strip(),
            "baud_rate": int(self.baud_rate_combo.currentText()),
            "data_bits": int(self.data_bits_combo.currentText()),
            "parity": self.parity_combo.currentText(),
            "stop_bits": int(self.stop_bits_combo.currentText()),
            "flow_control": self.flow_control_combo.currentText(),
            "group_id": self.group_combo.currentData(),
            "location": self.location_edit.text().strip(),
            "tags": self.tags_edit.text().strip(),
            "notes": self.notes_edit.toPlainText().strip(),
        }
        if protocol == "telnet":
            data["port"] = self.telnet_port_spin.value()
        return data


class AssetPanel(QWidget):
    """资产面板 - 左侧设备树"""

    # 信号：双击设备时发射
    connect_requested = Signal(int)  # asset_id
    # 信号：资产变更
    assets_changed = Signal()

    @staticmethod
    def _asset_target(asset):
        return asset.get("serial_port", "") if asset.get("protocol") == "serial" else asset.get("ip", "")

    @staticmethod
    def _asset_name(asset):
        protocol = asset.get("protocol", "ssh")
        if protocol == "serial":
            prefix = "[Serial] "
        elif protocol == "telnet":
            prefix = "[Telnet] "
        else:
            prefix = ""
        return f"{prefix}{asset.get('name', '')}"

    @staticmethod
    def _asset_status_icon(asset):
        protocol = asset.get("protocol")
        if protocol == "serial":
            return "—"
        return "●" if asset.get("status") == "online" else "○"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scan_worker = None
        self.setup_ui()
        self.refresh()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 搜索栏
        search_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 搜索设备...")
        self.search_edit.textChanged.connect(self.on_search)
        search_layout.addWidget(self.search_edit)

        self.btn_refresh = QPushButton("⟳")
        self.btn_refresh.setFixedWidth(36)
        self.btn_refresh.setFixedHeight(32)
        self.btn_refresh.setToolTip("扫描在线状态")
        self.btn_refresh.clicked.connect(self.scan_online_status)
        search_layout.addWidget(self.btn_refresh)

        layout.addLayout(search_layout)

        # 设备树
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["设备", "目标", "状态"])
        self.tree.setColumnWidth(0, 180)
        self.tree.setColumnWidth(1, 120)
        self.tree.setColumnWidth(2, 50)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.tree.setAnimated(True)
        layout.addWidget(self.tree)

        # 底部按钮
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("+ 添加设备")
        self.btn_add_group = QPushButton("+ 添加分组")
        self.btn_add.clicked.connect(self.add_asset)
        self.btn_add_group.clicked.connect(self.add_group)
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_add_group)
        layout.addLayout(btn_layout)

    def refresh(self):
        """刷新设备树"""
        self.tree.clear()
        groups = db.get_all_groups()
        assets = db.get_all_assets()

        # 按分组组织
        group_items = {}
        for g in groups:
            item = QTreeWidgetItem(self.tree, [g["name"], "", ""])
            item.setData(0, Qt.UserRole, {"type": "group", "id": g["id"]})
            item.setExpanded(True)
            group_items[g["id"]] = item

        # 添加设备
        for a in assets:
            gid = a.get("group_id")
            parent = group_items.get(gid) if gid else None

            status_icon = self._asset_status_icon(a)
            item_data = {"type": "asset", "id": a["id"]}
            display_name = self._asset_name(a)
            target = self._asset_target(a)

            if parent:
                item = QTreeWidgetItem(parent, [display_name, target, status_icon])
            else:
                item = QTreeWidgetItem(self.tree, [display_name, target, status_icon])

            item.setData(0, Qt.UserRole, item_data)

            # 颜色标记状态
            if a.get("protocol") == "serial":
                item.setForeground(2, QColor("#9E9E9E"))
            elif a.get("status") == "online":
                item.setForeground(2, QColor("#4CAF50"))
            elif a.get("status") == "offline":
                item.setForeground(2, QColor("#F44336"))
            else:
                item.setForeground(2, QColor("#9E9E9E"))

        self.tree.expandAll()
        self.assets_changed.emit()

    def on_search(self, text):
        """搜索过滤"""
        if not text.strip():
            self.refresh()
            return
        results = db.search_assets(text.strip())
        self.tree.clear()
        for a in results:
            status_icon = self._asset_status_icon(a)
            item = QTreeWidgetItem(
                self.tree,
                [self._asset_name(a), self._asset_target(a), status_icon],
            )
            item.setData(0, Qt.UserRole, {"type": "asset", "id": a["id"]})
        self.tree.expandAll()

    def on_item_double_clicked(self, item, column):
        """双击设备 -> 发起连接"""
        data = item.data(0, Qt.UserRole)
        if data and data.get("type") == "asset":
            self.connect_requested.emit(data["id"])

    def show_context_menu(self, pos):
        """右键菜单"""
        item = self.tree.itemAt(pos)
        if not item:
            return

        data = item.data(0, Qt.UserRole)
        if not data:
            return

        menu = QMenu(self)

        if data["type"] == "asset":
            connect_action = menu.addAction("🔗 连接设备")
            edit_action = menu.addAction("✏️ 编辑")
            delete_action = menu.addAction("🗑️ 删除")
            menu.addSeparator()
            log_action = menu.addAction("📋 查看日志")

            action = menu.exec_(self.tree.viewport().mapToGlobal(pos))

            if action == connect_action:
                self.connect_requested.emit(data["id"])
            elif action == edit_action:
                self.edit_asset(data["id"])
            elif action == delete_action:
                self.delete_asset(data["id"])
            elif action == log_action:
                self.show_logs(data["id"])

        elif data["type"] == "group":
            rename_action = menu.addAction("✏️ 重命名")
            delete_action = menu.addAction("🗑️ 删除分组")

            action = menu.exec_(self.tree.viewport().mapToGlobal(pos))

            if action == rename_action:
                self.rename_group(data["id"])
            elif action == delete_action:
                self.delete_group(data["id"])

    def add_asset(self):
        """添加设备"""
        groups = db.get_all_groups()
        dialog = AssetEditDialog(self, groups=groups)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            db.add_asset(**data)
            self.refresh()

    def edit_asset(self, asset_id):
        """编辑设备"""
        asset = db.get_asset_by_id(asset_id)
        if not asset:
            return
        groups = db.get_all_groups()
        dialog = AssetEditDialog(self, asset=asset, groups=groups)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            db.update_asset(asset_id, **data)
            self.refresh()

    def delete_asset(self, asset_id):
        """删除设备"""
        asset = db.get_asset_by_id(asset_id)
        if not asset:
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除设备 [{asset['name']}] 吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            db.delete_asset(asset_id)
            self.refresh()

    def add_group(self):
        """添加分组"""
        name, ok = QInputDialog.getText(self, "添加分组", "分组名称:")
        if ok and name.strip():
            try:
                db.add_group(name.strip())
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "错误", f"添加失败：{e}")

    def rename_group(self, group_id):
        """重命名分组"""
        groups = db.get_all_groups()
        group = next((g for g in groups if g["id"] == group_id), None)
        if not group:
            return
        name, ok = QInputDialog.getText(self, "重命名分组", "新名称:", text=group["name"])
        if ok and name.strip():
            db.update_group(group_id, name=name.strip())
            self.refresh()

    def delete_group(self, group_id):
        """删除分组"""
        reply = QMessageBox.question(
            self, "确认删除",
            "确定要删除此分组吗？（分组内设备不会被删除）",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            db.delete_group(group_id)
            self.refresh()

    def show_logs(self, asset_id):
        """查看设备操作日志"""
        logs = db.get_asset_logs(asset_id)
        asset = db.get_asset_by_id(asset_id)
        if not logs:
            QMessageBox.information(self, "日志", "暂无操作日志")
            return
        text = f"设备: {asset['name']} ({self._asset_target(asset)})\n"
        text += "=" * 50 + "\n"
        for log in logs:
            text += f"[{log['executed_at']}] {log['command']}\n"
            if log["output"]:
                text += f"  {log['output'][:200]}\n"
            text += "\n"
        QMessageBox.information(self, "操作日志", text)

    def scan_online_status(self):
        """扫描所有设备在线状态"""
        assets = db.get_all_assets()
        if not assets:
            return
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("⏳")

        self._scan_worker = ScanWorker(assets)
        self._scan_worker.device_status.connect(self._on_device_status)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _on_device_status(self, asset_id, is_online):
        if is_online is None:
            return
        status = "online" if is_online else "offline"
        db.update_asset(asset_id, status=status)

    def _on_scan_finished(self):
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("⟳")
        self.refresh()
