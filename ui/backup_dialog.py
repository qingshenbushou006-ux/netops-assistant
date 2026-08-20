"""
备份管理对话框 - 配置备份的UI界面
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel,
    QProgressBar, QTextEdit, QComboBox, QCheckBox, QGroupBox,
    QHeaderView, QMessageBox, QFileDialog, QInputDialog,
    QSplitter, QPlainTextEdit, QLineEdit
)
import json

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor

from core import db
from core.backup_manager import (
    BackupManager, BackupScheduler,
    export_backup_to_file, import_backup_from_file
)


class BackupWorker(QThread):
    """备份工作线程"""
    progress = Signal(int, int, str)
    log = Signal(str)
    finished_signal = Signal(dict)

    def __init__(self, backup_manager, task_type, target=None):
        super().__init__()
        self.backup_manager = backup_manager
        self.task_type = task_type
        self.target = target

    def run(self):
        self.backup_manager.set_callbacks(
            progress_cb=lambda c, t, m: self.progress.emit(c, t, m),
            log_cb=lambda m: self.log.emit(m)
        )

        if self.task_type == "single":
            success, msg, config = self.backup_manager.backup_single_device(self.target)
            self.finished_signal.emit({"_single": (success, msg)})
        elif self.task_type == "multiple":
            results = self.backup_manager.backup_multiple_devices(self.target or [])
            self.finished_signal.emit(results)
        elif self.task_type == "group":
            results = self.backup_manager.backup_by_group(self.target)
            self.finished_signal.emit(results)
        elif self.task_type == "all":
            if isinstance(self.target, list):
                results = self.backup_manager.backup_multiple_devices(self.target)
            else:
                results = self.backup_manager.backup_all_devices()
            self.finished_signal.emit(results)


class BackupDialog(QDialog):
    """备份管理主对话框"""

    def __init__(self, assets=None, parent=None):
        if parent is None and assets is not None and not isinstance(assets, list):
            parent = assets
            assets = None

        super().__init__(parent)
        self.setWindowTitle("配置备份管理")
        self.setMinimumSize(900, 600)
        self.backup_manager = BackupManager()
        self.worker = None
        self._initial_assets = assets

        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 标签页
        self.tab_widget = QTabWidget()

        # 备份操作页
        self.tab_widget.addTab(self._create_backup_tab(), "备份操作")
        # 备份历史页
        self.tab_widget.addTab(self._create_history_tab(), "备份历史")
        # 备份计划页
        self.tab_widget.addTab(self._create_schedule_tab(), "备份计划")
        # 配置对比页
        self.tab_widget.addTab(self._create_diff_tab(), "配置对比")

        layout.addWidget(self.tab_widget)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # 日志区
        self.log_text = QPlainTextEdit()
        self.log_text.setMaximumHeight(120)
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e2e;
                color: #a6e3a1;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 12px;
                border: 1px solid #313244;
            }
        """)
        layout.addWidget(QLabel("操作日志:"))
        layout.addWidget(self.log_text)

    def _create_backup_tab(self):
        """创建备份操作页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 设备选择区
        device_group = QGroupBox("选择设备")
        device_layout = QVBoxLayout(device_group)

        # 设备表格
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(5)
        self.device_table.setHorizontalHeaderLabels(["选择", "设备名称", "IP地址", "厂商", "状态"])
        self.device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.device_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.device_table.itemSelectionChanged.connect(self._sync_row_selection_to_checkbox)
        device_layout.addWidget(self.device_table)

        # 全选/反选
        select_layout = QHBoxLayout()
        btn_select_all = QPushButton("全选")
        btn_select_all.clicked.connect(self._select_all_devices)
        btn_deselect_all = QPushButton("取消全选")
        btn_deselect_all.clicked.connect(self._deselect_all_devices)
        btn_select_online = QPushButton("选择在线设备")
        btn_select_online.clicked.connect(self._select_online_devices)
        select_layout.addWidget(btn_select_all)
        select_layout.addWidget(btn_deselect_all)
        select_layout.addWidget(btn_select_online)
        select_layout.addStretch()
        device_layout.addLayout(select_layout)

        layout.addWidget(device_group)

        # 操作按钮
        btn_layout = QHBoxLayout()
        btn_backup_selected = QPushButton("备份选中设备")
        btn_backup_selected.setStyleSheet("""
            QPushButton {
                background-color: #89b4fa;
                color: #1e1e2e;
                font-weight: bold;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #74c7ec;
            }
        """)
        btn_backup_selected.clicked.connect(self._backup_selected)

        btn_backup_all = QPushButton("备份所有在线设备")
        btn_backup_all.clicked.connect(self._backup_all_online)

        btn_import = QPushButton("从文件导入配置")
        btn_import.clicked.connect(self._import_from_file)

        btn_layout.addWidget(btn_backup_selected)
        btn_layout.addWidget(btn_backup_all)
        btn_layout.addWidget(btn_import)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        return widget

    def _create_history_tab(self):
        """创建备份历史页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 设备选择
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("选择设备:"))
        self.history_device_combo = QComboBox()
        self.history_device_combo.currentIndexChanged.connect(self._load_history)
        filter_layout.addWidget(self.history_device_combo)
        filter_layout.addStretch()

        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self._load_history)
        filter_layout.addWidget(btn_refresh)
        layout.addLayout(filter_layout)

        # 备份历史表格
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5)
        self.history_table.setHorizontalHeaderLabels(["ID", "备份时间", "备份类型", "配置哈希", "操作"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.history_table)

        # 配置预览
        layout.addWidget(QLabel("配置预览:"))
        self.config_preview = QPlainTextEdit()
        self.config_preview.setReadOnly(True)
        self.config_preview.setFont(QFont("Consolas", 11))
        self.config_preview.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e2e;
                color: #cdd6f4;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 12px;
            }
        """)
        layout.addWidget(self.config_preview)

        # 操作按钮
        btn_layout = QHBoxLayout()
        btn_export = QPushButton("导出到文件")
        btn_export.clicked.connect(self._export_backup)
        btn_delete = QPushButton("删除备份")
        btn_delete.clicked.connect(self._delete_backup)
        btn_layout.addWidget(btn_export)
        btn_layout.addWidget(btn_delete)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        return widget

    def _create_schedule_tab(self):
        """创建备份计划页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 计划表格
        self.schedule_table = QTableWidget()
        self.schedule_table.setColumnCount(6)
        self.schedule_table.setHorizontalHeaderLabels(["ID", "计划名称", "Cron表达式", "启用", "上次运行", "下次运行"])
        self.schedule_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.schedule_table)

        # 操作按钮
        btn_layout = QHBoxLayout()
        btn_add = QPushButton("新建计划")
        btn_add.clicked.connect(self._add_schedule)
        btn_edit = QPushButton("编辑计划")
        btn_edit.clicked.connect(self._edit_schedule)
        btn_delete = QPushButton("删除计划")
        btn_delete.clicked.connect(self._delete_schedule)
        btn_run = QPushButton("立即执行")
        btn_run.clicked.connect(self._run_schedule)

        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_edit)
        btn_layout.addWidget(btn_delete)
        btn_layout.addWidget(btn_run)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 说明
        help_text = QLabel(
            "Cron表达式格式: 分 时 日 月 周\n"
            "示例: 0 2 * * * = 每天凌晨2点\n"
            "      0 */6 * * * = 每6小时\n"
            "      0 2 * * 1 = 每周一凌晨2点"
        )
        help_text.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(help_text)

        return widget

    def _create_diff_tab(self):
        """创建配置对比页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 设备选择
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("选择设备:"))
        self.diff_device_combo = QComboBox()
        filter_layout.addWidget(self.diff_device_combo)

        btn_compare = QPushButton("对比最近两次备份")
        btn_compare.clicked.connect(self._compare_configs)
        filter_layout.addWidget(btn_compare)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # 差异显示（HTML 渲染，支持 +/- 颜色高亮）
        from PySide6.QtWidgets import QTextEdit
        self.diff_text = QTextEdit()
        self.diff_text.setReadOnly(True)
        self.diff_text.setFont(QFont("Consolas", 11))
        self.diff_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e2e;
                color: #cdd6f4;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 12px;
            }
        """)
        layout.addWidget(self.diff_text)

        return widget

    def _load_data(self):
        """加载数据"""
        # 加载设备列表到表格
        assets = self._initial_assets if self._initial_assets is not None else db.get_all_assets()
        self.device_table.setRowCount(len(assets))
        for i, asset in enumerate(assets):
            # 复选框
            cb = QCheckBox()
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(Qt.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self.device_table.setCellWidget(i, 0, cb_widget)

            self.device_table.setItem(i, 1, QTableWidgetItem(asset["name"]))
            self.device_table.setItem(i, 2, QTableWidgetItem(asset["ip"]))
            self.device_table.setItem(i, 3, QTableWidgetItem(asset.get("vendor", "")))

            status_item = QTableWidgetItem(asset.get("status", "unknown"))
            if asset.get("status") == "online":
                status_item.setForeground(QColor("#a6e3a1"))
            elif asset.get("status") == "offline":
                status_item.setForeground(QColor("#f38ba8"))
            self.device_table.setItem(i, 4, status_item)

            # 存储asset数据
            self.device_table.item(i, 1).setData(Qt.UserRole, asset)

        # 加载设备到下拉框
        self.history_device_combo.clear()
        self.diff_device_combo.clear()
        for asset in assets:
            self.history_device_combo.addItem(f"{asset['name']} ({asset['ip']})", asset["id"])
            self.diff_device_combo.addItem(f"{asset['name']} ({asset['ip']})", asset["id"])

        # 加载备份计划
        self._load_schedules()

    def _load_history(self):
        """加载备份历史"""
        asset_id = self.history_device_combo.currentData()
        if not asset_id:
            return

        backups = db.get_asset_backups(asset_id)
        self.history_table.setRowCount(len(backups))
        for i, backup in enumerate(backups):
            self.history_table.setItem(i, 0, QTableWidgetItem(str(backup["id"])))
            self.history_table.setItem(i, 1, QTableWidgetItem(backup["created_at"]))
            self.history_table.setItem(i, 2, QTableWidgetItem(backup["backup_type"]))
            self.history_table.setItem(i, 3, QTableWidgetItem(backup.get("config_hash", "")[:16]))

            # 预览按钮
            btn_preview = QPushButton("预览")
            btn_preview.clicked.connect(lambda checked, bid=backup["id"]: self._preview_backup(bid))
            self.history_table.setCellWidget(i, 4, btn_preview)

    def _load_schedules(self):
        """加载备份计划"""
        schedules = db.get_all_schedules()
        self.schedule_table.setRowCount(len(schedules))
        for i, schedule in enumerate(schedules):
            self.schedule_table.setItem(i, 0, QTableWidgetItem(str(schedule["id"])))
            self.schedule_table.setItem(i, 1, QTableWidgetItem(schedule["name"]))
            self.schedule_table.setItem(i, 2, QTableWidgetItem(schedule["cron_expr"]))

            cb = QCheckBox()
            cb.setChecked(bool(schedule["enabled"]))
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(Qt.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self.schedule_table.setCellWidget(i, 3, cb_widget)

            self.schedule_table.setItem(i, 4, QTableWidgetItem(schedule.get("last_run", "从未")))
            self.schedule_table.setItem(i, 5, QTableWidgetItem(schedule.get("next_run", "未设置")))

    def _get_selected_assets(self):
        """获取选中的设备"""
        selected = []
        for i in range(self.device_table.rowCount()):
            cb_widget = self.device_table.cellWidget(i, 0)
            cb = cb_widget.findChild(QCheckBox)
            if cb and cb.isChecked():
                asset = self.device_table.item(i, 1).data(Qt.UserRole)
                if asset:
                    selected.append(asset)
        return selected

    def _sync_row_selection_to_checkbox(self):
        """同步行选择到复选框"""
        for i in range(self.device_table.rowCount()):
            cb_widget = self.device_table.cellWidget(i, 0)
            cb = cb_widget.findChild(QCheckBox)
            if cb:
                cb.setChecked(self.device_table.selectionModel().isRowSelected(i, self.device_table.rootIndex()))

    def _select_all_devices(self):
        """全选"""
        for i in range(self.device_table.rowCount()):
            cb_widget = self.device_table.cellWidget(i, 0)
            cb = cb_widget.findChild(QCheckBox)
            if cb:
                cb.setChecked(True)

    def _deselect_all_devices(self):
        """取消全选"""
        for i in range(self.device_table.rowCount()):
            cb_widget = self.device_table.cellWidget(i, 0)
            cb = cb_widget.findChild(QCheckBox)
            if cb:
                cb.setChecked(False)

    def _select_online_devices(self):
        """选择在线设备"""
        for i in range(self.device_table.rowCount()):
            status_item = self.device_table.item(i, 4)
            cb_widget = self.device_table.cellWidget(i, 0)
            cb = cb_widget.findChild(QCheckBox)
            if cb and status_item:
                cb.setChecked(status_item.text() == "online")

    def _backup_selected(self):
        """备份选中设备"""
        assets = self._get_selected_assets()
        if not assets:
            QMessageBox.warning(self, "提示", "请先选择要备份的设备")
            return

        self._start_backup("multiple", assets)

    def _backup_all_online(self):
        """备份所有在线设备"""
        assets = db.get_all_assets()
        online = [a for a in assets if a.get("status") == "online"]
        if not online:
            QMessageBox.warning(self, "提示", "没有在线设备，请先扫描在线状态")
            return

        reply = QMessageBox.question(
            self, "确认",
            f"确定要备份所有 {len(online)} 台在线设备吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._start_backup("all", online)

    def _start_backup(self, task_type, target):
        """开始备份"""
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.log_text.clear()

        self.worker = BackupWorker(self.backup_manager, task_type, target)

        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self._on_log)
        self.worker.finished_signal.connect(self._on_backup_finished)
        self.worker.start()

    def _on_progress(self, current, total, message):
        """更新进度"""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.log_text.appendPlainText(f"[{current}/{total}] {message}")

    def _on_log(self, message):
        """添加日志"""
        self.log_text.appendPlainText(message)

    def _on_backup_finished(self, results):
        """备份完成"""
        self.progress_bar.setVisible(False)

        success_count = sum(1 for v in results.values() if v[0])
        fail_count = sum(1 for v in results.values() if not v[0])

        if "_single" in results:
            success, msg = results["_single"]
            QMessageBox.information(self, "备份完成", msg)
        else:
            QMessageBox.information(
                self, "备份完成",
                f"成功: {success_count} 台\n失败: {fail_count} 台"
            )

        self._load_history()

    def _preview_backup(self, backup_id):
        """预览备份配置"""
        backup = db.get_backup_by_id(backup_id)
        if backup:
            self.config_preview.setPlainText(backup["config_text"])

    def _export_backup(self):
        """导出备份"""
        current_row = self.history_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "提示", "请先选择要导出的备份")
            return

        backup_id = int(self.history_table.item(current_row, 0).text())
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出配置", "config_backup.txt", "Text Files (*.txt)"
        )
        if file_path:
            if export_backup_to_file(backup_id, file_path):
                QMessageBox.information(self, "成功", f"已导出到: {file_path}")
            else:
                QMessageBox.warning(self, "失败", "导出失败")

    def _delete_backup(self):
        """删除备份"""
        current_row = self.history_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "提示", "请先选择要删除的备份")
            return

        backup_id = int(self.history_table.item(current_row, 0).text())
        reply = QMessageBox.question(
            self, "确认", "确定要删除此备份吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            db.delete_backup(backup_id)
            self._load_history()
            QMessageBox.information(self, "成功", "备份已删除")

    def _import_from_file(self):
        """从文件导入配置"""
        # 选择设备
        assets = db.get_all_assets()
        if not assets:
            QMessageBox.warning(self, "提示", "没有设备，请先添加设备")
            return

        items = [f"{a['name']} ({a['ip']})" for a in assets]
        item, ok = QInputDialog.getItem(
            self, "选择设备", "选择要导入配置的设备:", items, 0, False
        )
        if not ok:
            return

        idx = items.index(item)
        asset_id = assets[idx]["id"]

        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择配置文件", "", "Text Files (*.txt);;All Files (*)"
        )
        if file_path:
            success, msg = import_backup_from_file(asset_id, file_path)
            if success:
                QMessageBox.information(self, "成功", msg)
                self._load_history()
            else:
                QMessageBox.warning(self, "失败", msg)

    def _add_schedule(self):
        """添加备份计划"""
        dialog = ScheduleEditDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self._load_schedules()

    def _edit_schedule(self):
        """编辑备份计划"""
        current_row = self.schedule_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "提示", "请先选择要编辑的计划")
            return

        schedule_id = int(self.schedule_table.item(current_row, 0).text())
        dialog = ScheduleEditDialog(self, schedule_id)
        if dialog.exec() == QDialog.Accepted:
            self._load_schedules()

    def _delete_schedule(self):
        """删除备份计划"""
        current_row = self.schedule_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "提示", "请先选择要删除的计划")
            return

        schedule_id = int(self.schedule_table.item(current_row, 0).text())
        reply = QMessageBox.question(
            self, "确认", "确定要删除此计划吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            db.delete_schedule(schedule_id)
            self._load_schedules()

    def _run_schedule(self):
        """立即执行备份计划"""
        current_row = self.schedule_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "提示", "请先选择要执行的计划")
            return

        schedule_id = int(self.schedule_table.item(current_row, 0).text())
        scheduler = BackupScheduler(self.backup_manager)

        self.log_text.appendPlainText(f"正在执行备份计划...")
        results = scheduler.execute_schedule(schedule_id)

        if results:
            success_count = sum(1 for v in results.values() if v[0])
            fail_count = sum(1 for v in results.values() if not v[0])
            self.log_text.appendPlainText(f"执行完成: 成功 {success_count}, 失败 {fail_count}")

    def _compare_configs(self):
        """对比配置（高亮 +/- 行）"""
        asset_id = self.diff_device_combo.currentData()
        if not asset_id:
            return

        old_time, new_time, diff = BackupManager.get_config_diff_for_device(asset_id)

        if old_time and new_time:
            html = self._diff_to_html(diff, old_time, new_time)
            self.diff_text.setHtml(html)
        else:
            self.diff_text.setPlainText(diff)

    @staticmethod
    def _diff_to_html(diff_text, old_time="", new_time=""):
        """将 diff 文本转 HTML，'+' 行绿色、'-' 行红色、'@@' 蓝色"""
        import html as _html
        lines = diff_text.splitlines()
        out = []
        out.append("<div style='font-family: Consolas, monospace; font-size: 12px; line-height: 1.5;'>")
        if old_time or new_time:
            out.append(
                f"<div style='color:#8888a8;background:#252545;padding:6px 10px;margin-bottom:8px;border-radius:4px;'>"
                f"旧配置: {_html.escape(old_time)}<br/>新配置: {_html.escape(new_time)}</div>"
            )
        for line in lines:
            escaped = _html.escape(line)
            if line.startswith("+++") or line.startswith("---"):
                out.append(
                    f"<div style='color:#8888a8;background:#1a1a2e;padding:2px 8px;'>{escaped}</div>"
                )
            elif line.startswith("@@"):
                out.append(
                    f"<div style='color:#4facfe;background:#1a1a2e;padding:2px 8px;font-weight:bold;'>{escaped}</div>"
                )
            elif line.startswith("+"):
                out.append(
                    f"<div style='color:#a6e3a1;background:rgba(166,227,161,0.08);padding:2px 8px;'>{escaped}</div>"
                )
            elif line.startswith("-"):
                out.append(
                    f"<div style='color:#f38ba8;background:rgba(243,139,168,0.08);padding:2px 8px;'>{escaped}</div>"
                )
            else:
                out.append(
                    f"<div style='color:#cdd6f4;padding:2px 8px;'>{escaped}</div>"
                )
        out.append("</div>")
        return "".join(out)


class ScheduleEditDialog(QDialog):
    """备份计划编辑对话框"""

    def __init__(self, parent=None, schedule_id=None):
        super().__init__(parent)
        self.schedule_id = schedule_id
        self.setWindowTitle("编辑备份计划" if schedule_id else "新建备份计划")
        self.setMinimumWidth(500)

        self._setup_ui()
        if schedule_id:
            self._load_schedule()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 计划名称
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("计划名称:"))
        self.name_edit = QInputDialog()
        self.name_input = QLineEdit()
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)

        # Cron表达式
        cron_layout = QHBoxLayout()
        cron_layout.addWidget(QLabel("Cron表达式:"))
        self.cron_input = QLineEdit("0 2 * * *")
        cron_layout.addWidget(self.cron_input)
        layout.addLayout(cron_layout)

        # 预设
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("快速选择:"))
        presets = [
            ("每天凌晨2点", "0 2 * * *"),
            ("每天凌晨3点", "0 3 * * *"),
            ("每6小时", "0 */6 * * *"),
            ("每周一凌晨2点", "0 2 * * 1"),
        ]
        for name, cron in presets:
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked, c=cron: self.cron_input.setText(c))
            preset_layout.addWidget(btn)
        layout.addLayout(preset_layout)

        # 设备选择
        layout.addWidget(QLabel("选择要备份的设备:"))
        self.device_list = QTableWidget()
        self.device_list.setColumnCount(3)
        self.device_list.setHorizontalHeaderLabels(["选择", "设备名称", "IP地址"])
        self.device_list.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        assets = db.get_all_assets()
        self.device_list.setRowCount(len(assets))
        for i, asset in enumerate(assets):
            cb = QCheckBox()
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(Qt.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self.device_list.setCellWidget(i, 0, cb_widget)

            self.device_list.setItem(i, 1, QTableWidgetItem(asset["name"]))
            self.device_list.setItem(i, 2, QTableWidgetItem(asset["ip"]))
            self.device_list.item(i, 1).setData(Qt.UserRole, asset["id"])

        layout.addWidget(self.device_list)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("保存")
        btn_save.clicked.connect(self._save)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def _load_schedule(self):
        """加载已有计划"""
        schedules = db.get_all_schedules()
        schedule = None
        for s in schedules:
            if s["id"] == self.schedule_id:
                schedule = s
                break

        if not schedule:
            return

        self.name_input.setText(schedule["name"])
        self.cron_input.setText(schedule["cron_expr"])

        import json
        asset_ids = json.loads(schedule["asset_ids"])

        for i in range(self.device_list.rowCount()):
            asset_id = self.device_list.item(i, 1).data(Qt.UserRole)
            cb_widget = self.device_list.cellWidget(i, 0)
            cb = cb_widget.findChild(QCheckBox)
            if cb and asset_id in asset_ids:
                cb.setChecked(True)

    def _save(self):
        """保存计划"""
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入计划名称")
            return

        cron = self.cron_input.text().strip()
        if not cron:
            QMessageBox.warning(self, "提示", "请输入Cron表达式")
            return

        # 获取选中的设备ID
        selected_ids = []
        for i in range(self.device_list.rowCount()):
            cb_widget = self.device_list.cellWidget(i, 0)
            cb = cb_widget.findChild(QCheckBox)
            if cb and cb.isChecked():
                asset_id = self.device_list.item(i, 1).data(Qt.UserRole)
                selected_ids.append(asset_id)

        if not selected_ids:
            QMessageBox.warning(self, "提示", "请至少选择一台设备")
            return

        if self.schedule_id:
            db.update_schedule(
                self.schedule_id,
                name=name,
                asset_ids=json.dumps(selected_ids),
                cron_expr=cron
            )
        else:
            db.add_backup_schedule(name, selected_ids, cron)

        self.accept()

