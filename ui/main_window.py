"""
主窗口 - 资产管理 + 终端 一体化界面
"""
from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QMenuBar, QMenu, QStatusBar,
    QMessageBox, QToolBar, QLabel, QApplication, QWidget, QVBoxLayout, QDialog,
)
from PySide6.QtCore import Qt, QSize, Signal, QThread
from PySide6.QtGui import QAction, QFont, QIcon

from ui.asset_panel import AssetPanel
from ui.terminal_widget import TerminalPanel, TerminalTab
from ui.backup_dialog import BackupDialog
from ui.topology_widget import TopologyWidget
from ui.serial_quick_dialog import SerialQuickDialog
from core import db


class BatchWorker(QThread):
    """批量命令后台执行线程"""
    progress = Signal(str)   # 单条结果
    finished = Signal(list)  # 所有结果

    def __init__(self, assets, command):
        super().__init__()
        self.assets = assets
        self.command = command

    def run(self):
        from core.ssh_manager import SSHConnection
        results = []
        for a in self.assets:
            try:
                conn = SSHConnection(
                    host=a["ip"], port=a.get("port", 22),
                    username=a.get("username", ""),
                    password=a.get("password", ""),
                )
                success, msg = conn.connect()
                if success:
                    output = conn.send_command(self.command.strip(), wait_time=2)
                    db.log_command(a["id"], self.command.strip(), output)
                    if output.strip():
                        preview = output.strip().splitlines()[-1][:80]
                        results.append(f"✓ {a['name']} ({a['ip']}): {preview}")
                    else:
                        results.append(f"✗ {a['name']}: 未收到命令输出")
                else:
                    results.append(f"✗ {a['name']}: {msg}")
                conn.disconnect()
            except Exception as e:
                results.append(f"✗ {a['name']}: {e}")
            self.progress.emit(results[-1] if results else "")
        self.finished.emit(results)


class MainWindow(QMainWindow):
    """NetOps Assistant 主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("NetOps Assistant - 网络运维资产管理工具")
        self.setMinimumSize(1000, 600)
        self.resize(1400, 800)

        self._setup_dark_theme()
        self._setup_ui()
        self._setup_menu()
        self._setup_statusbar()

    def _setup_dark_theme(self):
        """Catppuccin Mocha - Modern Dark Theme"""
        self.setStyleSheet("""
            /* Main Window */
            QMainWindow {
                background-color: #1e1e2e;
            }
            
            /* Menu Bar */
            QMenuBar {
                background-color: #181825;
                color: #cdd6f4;
                border-bottom: 1px solid #313244;
                padding: 4px 8px;
                font-size: 13px;
            }
            QMenuBar::item {
                padding: 6px 12px;
                border-radius: 6px;
            }
            QMenuBar::item:selected {
                background-color: #45475a;
            }
            
            /* Menus */
            QMenu {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 24px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #585b70;
            }
            QMenu::separator {
                height: 1px;
                background-color: #45475a;
                margin: 4px 12px;
            }
            
            /* Splitter */
            QSplitter::handle {
                background-color: #313244;
                width: 2px;
            }
            QSplitter::handle:hover {
                background-color: #89b4fa;
            }
            
            /* Status Bar */
            QStatusBar {
                background-color: #181825;
                color: #a6adc8;
                border-top: 1px solid #313244;
                font-size: 12px;
                padding: 4px;
            }
            
            /* Tree Widget */
            QTreeWidget {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: none;
                outline: none;
                font-size: 13px;
            }
            QTreeWidget::item {
                padding: 6px 4px;
                border-radius: 6px;
            }
            QTreeWidget::item:selected {
                background-color: #45475a;
            }
            QTreeWidget::item:hover {
                background-color: #313244;
            }
            
            /* Headers */
            QHeaderView::section {
                background-color: #181825;
                color: #a6adc8;
                border: none;
                border-bottom: 1px solid #313244;
                padding: 8px 12px;
                font-size: 12px;
                font-weight: bold;
            }
            
            /* Tab Widget */
            QTabWidget::pane {
                border: none;
                background-color: #1e1e2e;
            }
            QTabBar::tab {
                background-color: #181825;
                color: #a6adc8;
                padding: 8px 20px;
                border: none;
                border-bottom: 3px solid transparent;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border-bottom: 3px solid #89b4fa;
            }
            QTabBar::tab:hover {
                background-color: #313244;
                color: #cdd6f4;
            }
            
            /* Buttons */
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45475a;
                border-color: #585b70;
            }
            QPushButton:pressed {
                background-color: #585b70;
            }
            
            /* Input Fields */
            QLineEdit {
                background-color: #313244;
                color: #cdd6f4;
                border: 2px solid #45475a;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #89b4fa;
            }
            
            /* Combo Box */
            QComboBox {
                background-color: #313244;
                color: #cdd6f4;
                border: 2px solid #45475a;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QComboBox:focus {
                border-color: #89b4fa;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 8px;
                selection-background-color: #45475a;
            }
            
            /* Spin Box */
            QSpinBox {
                background-color: #313244;
                color: #cdd6f4;
                border: 2px solid #45475a;
                border-radius: 8px;
                padding: 8px;
            }
            
            /* Text Areas */
            QTextEdit, QPlainTextEdit {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 8px;
                font-family: Consolas, 'Courier New', monospace;
            }
            
            /* Labels */
            QLabel {
                color: #cdd6f4;
            }
            
            /* Toolbar */
            QToolBar {
                background-color: #181825;
                border-bottom: 1px solid #313244;
                spacing: 6px;
                padding: 4px;
            }
            
            /* Tooltips */
            QToolTip {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
            }
            
            /* Scroll Bars */
            QScrollBar:vertical {
                background-color: #1e1e2e;
                width: 12px;
                border: none;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #45475a;
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #585b70;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar:horizontal {
                background-color: #1e1e2e;
                height: 12px;
                border: none;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background-color: #45475a;
                border-radius: 6px;
                min-width: 30px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #585b70;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }
            
            /* Group Box */
            QGroupBox {
                border: 1px solid #313244;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 16px;
                font-weight: bold;
                color: #89b4fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            
            /* Dialog */
            QDialog {
                background-color: #1e1e2e;
            }
            
            /* Message Box */
            QMessageBox {
                background-color: #1e1e2e;
            }
            QMessageBox QLabel {
                color: #cdd6f4;
            }
            QMessageBox QPushButton {
                min-width: 80px;
            }
        """)

    def _setup_ui(self):
        """布局：左侧资产树 + 右侧终端"""
        central = QSplitter(Qt.Horizontal)
        central.setHandleWidth(3)

        # 左侧资产面板
        self.asset_panel = AssetPanel()
        self.asset_panel.setMinimumWidth(260)
        self.asset_panel.setMaximumWidth(500)

        # 右侧终端面板
        self.terminal_panel = TerminalPanel()
        self.terminal_panel.setMinimumWidth(400)

        central.addWidget(self.asset_panel)
        central.addWidget(self.terminal_panel)
        central.setStretchFactor(0, 1)
        central.setStretchFactor(1, 3)

        self.setCentralWidget(central)

        # 连接信号：双击资产 -> 打开终端
        self.asset_panel.connect_requested.connect(self._on_connect)

    def _setup_menu(self):
        """菜单栏"""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")

        add_action = QAction("添加设备(&A)", self)
        add_action.setShortcut("Ctrl+N")
        add_action.triggered.connect(self.asset_panel.add_asset)
        file_menu.addAction(add_action)

        file_menu.addSeparator()

        import_action = QAction("导入资产(&I)", self)
        import_action.triggered.connect(self._import_assets)
        file_menu.addAction(import_action)

        export_action = QAction("导出资产(&E)", self)
        export_action.triggered.connect(self._export_assets)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        quit_action = QAction("退出(&Q)", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # 工具菜单
        tool_menu = menubar.addMenu("工具(&T)")

        scan_action = QAction("扫描在线状态(&S)", self)
        scan_action.setShortcut("F5")
        scan_action.triggered.connect(self.asset_panel.scan_online_status)
        tool_menu.addAction(scan_action)

        tool_menu.addSeparator()

        batch_action = QAction("批量命令(&B)", self)
        batch_action.triggered.connect(self._batch_command)
        tool_menu.addAction(batch_action)

        tool_menu.addSeparator()

        backup_action = QAction("配置备份管理(&C)", self)
        backup_action.setShortcut("Ctrl+B")
        backup_action.triggered.connect(self._show_backup_dialog)
        tool_menu.addAction(backup_action)

        topology_action = QAction("网络拓扑图(&T)", self)
        topology_action.setShortcut("Ctrl+T")
        topology_action.triggered.connect(self._show_topology)
        tool_menu.addAction(topology_action)

        tool_menu.addSeparator()

        serial_quick_action = QAction("新建串口会话(&R)", self)
        serial_quick_action.setShortcut("Ctrl+Shift+R")
        serial_quick_action.triggered.connect(self._open_serial_quick)
        tool_menu.addAction(serial_quick_action)

        tool_menu.addSeparator()

        self.multi_exec_action = QAction("多会话广播模式(&M)", self)
        self.multi_exec_action.setShortcut("Ctrl+Shift+M")
        self.multi_exec_action.setCheckable(True)
        self.multi_exec_action.triggered.connect(self._toggle_multi_exec)
        tool_menu.addAction(self.multi_exec_action)

        tool_menu.addSeparator()

        sftp_action = QAction("SFTP 文件传输(&F)", self)
        sftp_action.setShortcut("Ctrl+Shift+F")
        sftp_action.triggered.connect(self._open_sftp)
        tool_menu.addAction(sftp_action)

        tool_menu.addSeparator()

        template_action = QAction("命令模板库(&P)", self)
        template_action.setShortcut("Ctrl+P")
        template_action.triggered.connect(self._show_templates)
        tool_menu.addAction(template_action)

        # 视图菜单
        view_menu = menubar.addMenu("视图(&V)")

        close_tab_action = QAction("关闭当前标签", self)
        close_tab_action.setShortcut("Ctrl+W")
        close_tab_action.triggered.connect(self._close_current_tab)
        view_menu.addAction(close_tab_action)

        close_all_action = QAction("关闭所有标签", self)
        close_all_action.triggered.connect(self.terminal_panel.disconnect_all)
        view_menu.addAction(close_all_action)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        help_menu.addSeparator()

        uninstall_action = QAction("卸载软件(&U)", self)
        uninstall_action.triggered.connect(self._uninstall)
        help_menu.addAction(uninstall_action)

    def _setup_statusbar(self):
        """状态栏"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.asset_count_label = QLabel("设备: 0")
        self.status_bar.addWidget(self.asset_count_label)

        self.connection_label = QLabel("连接: 0")
        self.status_bar.addPermanentWidget(self.connection_label)

        self.status_bar.showMessage("就绪")

        # 初始刷新
        self._refresh_status()

    def _refresh_status(self):
        assets = db.get_all_assets()
        self.asset_count_label.setText(f"设备: {len(assets)}")
        connection_count = self.terminal_panel.tab_widget.count()
        self.connection_label.setText(f"连接: {connection_count}")
        if self.terminal_panel.multi_exec_active:
            self.status_bar.showMessage("多会话广播模式已开启")

    def _toggle_multi_exec(self, checked):
        """切换多会话广播模式"""
        self.terminal_panel.multi_exec_active = checked
        if checked:
            self.status_bar.showMessage("多会话广播模式已开启 - 输入将发送到所有终端")
        else:
            self.status_bar.showMessage("多会话广播模式已关闭")

    def _open_sftp(self):
        """打开 SFTP 文件传输对话框"""
        idx = self.terminal_panel.tab_widget.currentIndex()
        if idx < 0:
            QMessageBox.information(self, "提示", "请先打开一个终端连接")
            return
        widget = self.terminal_panel.tab_widget.widget(idx)
        if not isinstance(widget, TerminalTab) or not widget.is_connected():
            QMessageBox.information(self, "提示", "当前终端未连接，请先连接设备")
            return
        if not hasattr(widget._conn, 'client') or widget._conn.client is None:
            QMessageBox.information(self, "提示", "SFTP 仅支持 SSH 连接")
            return
        from ui.sftp_dialog import SFTPDialog
        dialog = SFTPDialog(widget._conn, self)
        dialog.exec()

    def _open_serial_quick(self):
        """打开串口快速连接对话框"""
        dialog = SerialQuickDialog(self)
        if dialog.exec() == QDialog.Accepted:
            config = dialog.get_config()
            if config:
                port = config.get("serial_port", "")
                self.status_bar.showMessage(f"正在打开串口终端 {port}...")
                self.terminal_panel.open_quick_terminal(config)
                self._refresh_status()
                self.status_bar.showMessage(f"已打开串口终端 {port}")

    def _on_connect(self, asset_id):
        """双击资产 -> 打开终端"""
        asset = db.get_asset_by_id(asset_id)
        if not asset:
            QMessageBox.warning(self, "错误", "设备数据不存在")
            return

        target = asset.get("serial_port") if asset.get("protocol") == "serial" else asset.get("ip")
        terminal_type = "串口终端" if asset.get("protocol") == "serial" else "终端"
        self.status_bar.showMessage(
            f"正在打开 {asset['name']} ({target}) {terminal_type}..."
        )
        self.terminal_panel.open_terminal(asset)
        self._refresh_status()
        self.status_bar.showMessage(f"已打开 {asset['name']} {terminal_type}")

    def _close_current_tab(self):
        idx = self.terminal_panel.tab_widget.currentIndex()
        if idx >= 0:
            self.terminal_panel._close_tab(idx)

    def _import_assets(self):
        """导入资产（CSV）"""
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入资产", "", "CSV Files (*.csv);;All Files (*)"
        )
        if not file_path:
            return

        import csv
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                count = 0
                skipped = 0
                for row_num, row in enumerate(reader, start=2):
                    try:
                        protocol = row.get("protocol", row.get("协议", "ssh")).strip() or "ssh"
                        port_value = row.get("port", row.get("端口", "22")).strip() or "22"
                        baud_rate_value = row.get("baud_rate", row.get("波特率", "9600")).strip() or "9600"
                        data_bits_value = row.get("data_bits", row.get("数据位", "8")).strip() or "8"
                        stop_bits_value = row.get("stop_bits", row.get("停止位", "1")).strip() or "1"
                        group_id_raw = row.get("group_id", row.get("分组ID", "")).strip()
                        db.add_asset(
                            name=row.get("name", row.get("设备名称", "")),
                            ip=row.get("ip", row.get("IP", "")) if protocol != "serial" else "",
                            port=int(port_value),
                            protocol=protocol,
                            vendor=row.get("vendor", row.get("厂商", "")),
                            model=row.get("model", row.get("型号", "")),
                            username=row.get("username", row.get("用户名", "")) if protocol != "serial" else "",
                            password=row.get("password", row.get("密码", "")) if protocol != "serial" else "",
                            enable_password=row.get("enable_password", row.get("特权密码", "")),
                            serial_port=row.get("serial_port", row.get("串口端口", "")),
                            baud_rate=int(baud_rate_value),
                            data_bits=int(data_bits_value),
                            parity=row.get("parity", row.get("校验位", "N")) or "N",
                            stop_bits=int(stop_bits_value),
                            flow_control=row.get("flow_control", row.get("流控", "none")) or "none",
                            group_id=int(group_id_raw) if group_id_raw else None,
                            location=row.get("location", row.get("位置", "")),
                            tags=row.get("tags", row.get("标签", "")),
                            notes=row.get("notes", row.get("备注", "")),
                        )
                        count += 1
                    except (ValueError, TypeError) as e:
                        skipped += 1
                        continue
                self.asset_panel.refresh()
                self._refresh_status()
                msg = f"成功导入 {count} 台设备"
                if skipped:
                    msg += f"，跳过 {skipped} 行（数据格式错误）"
                QMessageBox.information(self, "导入成功", msg)
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"错误: {e}")

    def _export_assets(self):
        """导出资产（CSV）"""
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出资产", "assets.csv", "CSV Files (*.csv)"
        )
        if not file_path:
            return

        import csv
        try:
            assets = db.get_all_assets()
            with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "name", "ip", "port", "protocol", "vendor", "model",
                    "username", "password", "enable_password",
                    "location", "tags", "notes", "status",
                    "serial_port", "baud_rate", "data_bits", "parity",
                    "stop_bits", "flow_control", "group_id"
                ])
                writer.writeheader()
                for a in assets:
                    writer.writerow({
                        "name": a["name"], "ip": a["ip"],
                        "port": a["port"], "protocol": a["protocol"],
                        "vendor": a["vendor"], "model": a["model"],
                        "username": a["username"],
                        "password": a.get("password", ""),
                        "enable_password": a.get("enable_password", ""),
                        "location": a["location"],
                        "tags": a["tags"], "notes": a.get("notes", ""),
                        "status": a["status"],
                        "serial_port": a.get("serial_port", ""),
                        "baud_rate": a.get("baud_rate", 9600),
                        "data_bits": a.get("data_bits", 8),
                        "parity": a.get("parity", "N"),
                        "stop_bits": a.get("stop_bits", 1),
                        "flow_control": a.get("flow_control", "none"),
                        "group_id": a.get("group_id", ""),
                    })
            QMessageBox.information(self, "导出成功", f"已导出 {len(assets)} 台设备")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", f"错误: {e}")

    def _batch_command(self):
        """批量命令（含 dry-run 预览）"""
        from PySide6.QtWidgets import QInputDialog, QProgressDialog
        assets = db.get_all_assets()
        online = [a for a in assets if a.get("status") == "online"]
        if not online:
            QMessageBox.information(self, "提示", "没有在线设备，请先扫描状态")
            return

        cmd, ok = QInputDialog.getText(
            self, "批量命令",
            f"将对 {len(online)} 台在线设备执行命令:"
        )
        if not ok or not cmd.strip():
            return

        # Dry-run 预览窗口
        preview = self._show_dry_run_preview(online, cmd.strip())
        if not preview:
            return  # 用户取消

        # 后台执行，不阻塞 UI
        self._batch_progress = QProgressDialog("正在批量执行命令...", "取消", 0, len(online), self)
        self._batch_progress.setWindowTitle("批量命令")
        self._batch_progress.setMinimumDuration(0)
        self._batch_progress.setValue(0)

        self._batch_worker = BatchWorker(online, cmd.strip())
        self._batch_worker.progress.connect(
            lambda _: self._batch_progress.setValue(self._batch_progress.value() + 1)
        )
        self._batch_worker.finished.connect(self._on_batch_finished)
        self._batch_progress.canceled.connect(self._batch_worker.terminate)
        self._batch_worker.start()

    def _show_dry_run_preview(self, assets, command):
        """显示 dry-run 预览窗口，返回 True 确认执行，False 取消"""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel
        )
        dialog = QDialog(self)
        dialog.setWindowTitle("Dry-Run 预览")
        dialog.resize(700, 500)
        layout = QVBoxLayout(dialog)

        warning = QLabel(
            f"⚠️ 将对 <b>{len(assets)}</b> 台在线设备执行以下命令，"
            f"请仔细核对目标后再确认执行。"
        )
        warning.setStyleSheet("color:#f38ba8;padding:8px;background:rgba(243,139,168,0.1);border-radius:4px;")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        cmd_label = QLabel("执行命令：")
        cmd_label.setStyleSheet("color:#8888a8;padding:4px 0;")
        layout.addWidget(cmd_label)

        cmd_box = QTextEdit()
        cmd_box.setReadOnly(True)
        cmd_box.setMaximumHeight(100)
        cmd_box.setStyleSheet(
            "QTextEdit{background:#1a1a2e;color:#a6e3a1;font-family:Consolas,monospace;"
            "font-size:13px;padding:8px;border:1px solid #252545;border-radius:4px;}"
        )
        cmd_box.setPlainText(command)
        layout.addWidget(cmd_box)

        target_label = QLabel(f"目标设备 ({len(assets)} 台)：")
        target_label.setStyleSheet("color:#8888a8;padding:4px 0;")
        layout.addWidget(target_label)

        target_box = QTextEdit()
        target_box.setReadOnly(True)
        target_box.setStyleSheet(
            "QTextEdit{background:#1a1a2e;color:#cdd6f4;font-family:Consolas,monospace;"
            "font-size:12px;padding:8px;border:1px solid #252545;border-radius:4px;}"
        )
        target_lines = []
        for i, a in enumerate(assets, 1):
            target_lines.append(
                f"{i:3d}. {a.get('name','?'):24s} {a.get('ip',''):16s} "
                f"{a.get('protocol',''):8s} {a.get('vendor','')} {a.get('location','')}"
            )
        target_box.setPlainText("\n".join(target_lines))
        layout.addWidget(target_box)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(
            "QPushButton{background:#313244;color:#cdd6f4;padding:8px 20px;border-radius:4px;}"
            "QPushButton:hover{background:#45475a;}"
        )
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        confirm_btn = QPushButton(f"确认执行（{len(assets)} 台）")
        confirm_btn.setStyleSheet(
            "QPushButton{background:#4facfe;color:#1e1e2e;font-weight:600;padding:8px 20px;border-radius:4px;}"
            "QPushButton:hover{background:#00f2fe;}"
        )
        confirm_btn.setDefault(True)
        confirm_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(confirm_btn)
        layout.addLayout(btn_layout)

        return dialog.exec() == QDialog.Accepted

    def _on_batch_finished(self, results):
        self._batch_progress.close()
        QMessageBox.information(
            self, "批量执行结果", "\n".join(results)
        )

    def _show_about(self):
        QMessageBox.about(
            self, "关于 NetOps Assistant",
            "<h3>NetOps Assistant v1.0</h3>"
            "<p>网络运维资产管理工具</p>"
            "<p>功能特性:</p>"
            "<ul>"
            "<li>资产管理 - 添加/删除/分类/搜索</li>"
            "<li>SSH/Telnet/Serial 终端 - 嵌入式交互</li>"
            "<li>ANSI 颜色渲染 - 16色/256色/TrueColor</li>"
            "<li>多厂商支持 - Cisco/Huawei/H3C/Linux</li>"
            "<li>批量命令 - 一键下发配置</li>"
            "<li>多会话广播 - 同时输入到所有终端</li>"
            "<li>SFTP 文件传输 - 上传/下载/浏览</li>"
            "<li>终端搜索 - Ctrl+F 查找内容</li>"
            "<li>字体缩放 - Ctrl+滚轮/Ctrl++/-</li>"
            "<li>会话日志 - 记录终端输出到文件</li>"
            "<li>自动重连 - 断线后指数退避重连</li>"
            "<li>编码切换 - UTF-8/GBK/Big5等</li>"
            "<li>配置备份 - 自动/手动备份设备配置</li>"
            "<li>网络拓扑 - LLDP自动发现/手动编辑</li>"
            "<li>CSV 导入导出</li>"
            "</ul>"
            "<p>技术栈: Python + PySide6 + Paramiko + Pyte</p>"
        )

    def _show_backup_dialog(self):
        """显示配置备份对话框"""
        dialog = BackupDialog(self)
        dialog.exec()

    def _show_topology(self):
        """显示网络拓扑图"""
        # 如果已有窗口，复用并前置
        if hasattr(self, '_topology_window') and self._topology_window is not None:
            try:
                if self._topology_window.isVisible():
                    self._topology_window.raise_()
                    self._topology_window.activateWindow()
                    return
            except RuntimeError:
                pass
        # 创建拓扑图窗口
        self._topology_window = QWidget()
        self._topology_window.setWindowTitle("网络拓扑图")
        self._topology_window.setMinimumSize(1000, 700)
        self._topology_window.setAttribute(Qt.WA_DeleteOnClose)

        layout = QVBoxLayout(self._topology_window)
        self._topology_widget = TopologyWidget()
        layout.addWidget(self._topology_widget)
        # 双击拓扑节点 -> 连接设备
        self._topology_widget.view.connectRequested.connect(self._on_connect)

        self._topology_window.show()

    def _show_templates(self):
        """显示命令模板库"""
        from ui.template_dialog import TemplateDialog

        def send_to_active_terminal(cmd):
            idx = self.terminal_panel.tab_widget.currentIndex()
            if idx < 0:
                QMessageBox.information(self, "提示", "请先打开一个终端连接")
                return
            widget = self.terminal_panel.tab_widget.widget(idx)
            if isinstance(widget, TerminalTab) and widget.is_connected():
                widget._conn.send_keys(cmd + '\r')
                try:
                    db.log_command(widget.asset_id, cmd)
                except Exception:
                    pass
            else:
                QMessageBox.information(self, "提示", "当前终端未连接")

        dialog = TemplateDialog(self, send_callback=send_to_active_terminal)
        dialog.exec()

    def _uninstall(self):
        """卸载软件"""
        import os
        import shutil
        
        reply = QMessageBox.question(
            self, "确认卸载",
            "确定要卸载 NetOps Assistant 吗？\n\n"
            "这将删除：\n"
            "- 所有程序文件\n"
            "- 数据库和配置\n"
            "- 虚拟环境\n\n"
            "此操作不可撤销！",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # 二次确认
        reply2 = QMessageBox.question(
            self, "最终确认",
            "真的要删除所有文件吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply2 != QMessageBox.Yes:
            return
        
        # 获取程序目录
        app_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(app_dir)
        
        # 创建卸载脚本
        uninstall_script = os.path.join(parent_dir, "_uninstall.bat")
        with open(uninstall_script, "w") as f:
            f.write(f'''@echo off
chcp 65001 >nul 2>&1
echo.
echo ============================================
echo   NetOps Assistant - Uninstalling...
echo ============================================
echo.
timeout /t 2 >nul
rmdir /s /q "{app_dir}"
del /f /q "{uninstall_script}" 2>nul
echo.
echo Uninstall complete!
echo.
pause
''')
        
        QMessageBox.information(
            self, "卸载",
            f"卸载脚本已创建：\n{uninstall_script}\n\n"
            "程序将关闭，请运行卸载脚本完成删除。"
        )
        
        # 关闭程序
        QApplication.quit()
        os.system(f'start "" "{uninstall_script}"')

    def closeEvent(self, event):
        """关闭窗口时清理"""
        self.terminal_panel.disconnect_all()
        self._refresh_status()
        event.accept()
