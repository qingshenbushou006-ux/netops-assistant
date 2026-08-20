"""
命令模板管理对话框 - 预置厂商命令片段
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QLineEdit, QComboBox, QMessageBox,
    QFormLayout, QTextEdit, QInputDialog, QSplitter, QWidget, QHeaderView,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from core import db


class TemplateEditDialog(QDialog):
    """单个模板编辑对话框"""

    def __init__(self, parent=None, template=None):
        super().__init__(parent)
        self.template = template
        self.setWindowTitle("编辑命令模板" if template else "新建命令模板")
        self.setMinimumWidth(480)
        self.setMinimumHeight(400)
        self._setup_ui()

    def _setup_ui(self):
        layout = QFormLayout(self)

        self.name_edit = QLineEdit(self.template.get("name", "") if self.template else "")
        self.command_edit = QTextEdit(self.template.get("command", "") if self.template else "")
        self.command_edit.setMaximumHeight(80)
        self.command_edit.setFont(QFont("Consolas", 11))

        self.vendor_combo = QComboBox()
        self.vendor_combo.addItems(["通用", "cisco", "huawei", "h3c", "linux", "juniper"])
        if self.template:
            idx = self.vendor_combo.findText(self.template.get("vendor", "通用"))
            if idx >= 0:
                self.vendor_combo.setCurrentIndex(idx)

        self.category_combo = QComboBox()
        self.category_combo.addItems(["基础", "配置", "监控", "发现", "测试", "安全"])
        self.category_combo.setEditable(True)
        if self.template:
            self.category_combo.setCurrentText(self.template.get("category", "基础"))

        self.desc_edit = QLineEdit(self.template.get("description", "") if self.template else "")

        layout.addRow("名称:", self.name_edit)
        layout.addRow("命令:", self.command_edit)
        layout.addRow("厂商:", self.vendor_combo)
        layout.addRow("分类:", self.category_combo)
        layout.addRow("说明:", self.desc_edit)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        cancel_btn = QPushButton("取消")
        save_btn.clicked.connect(self.validate_and_accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

    def validate_and_accept(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "提示", "请输入模板名称")
            return
        if not self.command_edit.toPlainText().strip():
            QMessageBox.warning(self, "提示", "请输入命令内容")
            return
        self.accept()

    def get_data(self):
        return {
            "name": self.name_edit.text().strip(),
            "command": self.command_edit.toPlainText().strip(),
            "vendor": self.vendor_combo.currentText(),
            "category": self.category_combo.currentText(),
            "description": self.desc_edit.text().strip(),
        }


class TemplateDialog(QDialog):
    """命令模板管理主对话框"""

    # 信号：选中命令时发射
    command_selected = Signal(str)

    def __init__(self, parent=None, send_callback=None):
        super().__init__(parent)
        self.setWindowTitle("命令模板")
        self.setMinimumSize(750, 500)
        self._send_callback = send_callback
        self._setup_ui()
        self._load_templates()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 筛选栏
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("厂商:"))
        self.vendor_filter = QComboBox()
        self.vendor_filter.addItem("全部")
        self.vendor_filter.addItems(["通用", "cisco", "huawei", "h3c", "linux", "juniper"])
        self.vendor_filter.currentTextChanged.connect(self._load_templates)
        filter_layout.addWidget(self.vendor_filter)

        filter_layout.addWidget(QLabel("分类:"))
        self.category_filter = QComboBox()
        self.category_filter.addItem("全部")
        self.category_filter.addItems(["基础", "配置", "监控", "发现", "测试", "安全"])
        self.category_filter.currentTextChanged.connect(self._load_templates)
        filter_layout.addWidget(self.category_filter)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索模板...")
        self.search_edit.textChanged.connect(self._load_templates)
        filter_layout.addWidget(self.search_edit)

        layout.addLayout(filter_layout)

        # 模板列表
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["名称", "命令", "厂商", "分类", "说明"])
        self.tree.setColumnWidth(0, 180)
        self.tree.setColumnWidth(1, 250)
        self.tree.setColumnWidth(2, 80)
        self.tree.setColumnWidth(3, 60)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.tree)

        # 按钮栏
        btn_layout = QHBoxLayout()

        btn_send = QPushButton("发送到终端")
        btn_send.setStyleSheet("""
            QPushButton {
                background-color: #89b4fa; color: #1e1e2e;
                font-weight: bold; padding: 8px 16px;
            }
            QPushButton:hover { background-color: #74c7ec; }
        """)
        btn_send.clicked.connect(self._send_selected)
        btn_layout.addWidget(btn_send)

        btn_copy = QPushButton("复制命令")
        btn_copy.clicked.connect(self._copy_selected)
        btn_layout.addWidget(btn_copy)

        btn_layout.addStretch()

        btn_add = QPushButton("+ 新建")
        btn_add.clicked.connect(self._add_template)
        btn_layout.addWidget(btn_add)

        btn_edit = QPushButton("编辑")
        btn_edit.clicked.connect(self._edit_template)
        btn_layout.addWidget(btn_edit)

        btn_delete = QPushButton("删除")
        btn_delete.clicked.connect(self._delete_template)
        btn_layout.addWidget(btn_delete)

        layout.addLayout(btn_layout)

    def _load_templates(self):
        """加载模板列表"""
        vendor = self.vendor_filter.currentText()
        category = self.category_filter.currentText()
        search = self.search_edit.text().strip().lower()

        templates = db.get_all_command_templates(
            vendor=None if vendor == "全部" else vendor,
            category=None if category == "全部" else category,
        )

        self.tree.clear()
        for t in templates:
            if search and search not in t["name"].lower() and search not in t["command"].lower():
                continue
            item = QTreeWidgetItem(self.tree, [
                t["name"],
                t["command"],
                t.get("vendor", ""),
                t.get("category", ""),
                t.get("description", ""),
            ])
            item.setData(0, Qt.UserRole, t)

            # 颜色标记厂商
            vendor_colors = {
                "cisco": "#89b4fa",
                "huawei": "#f38ba8",
                "h3c": "#f9e2af",
                "linux": "#a6e3a1",
                "通用": "#a6adc8",
            }
            color = vendor_colors.get(t.get("vendor", ""), "#a6adc8")
            item.setForeground(2, QColor(color))

        self.tree.expandAll()

    def _get_selected_template(self):
        item = self.tree.currentItem()
        if item:
            return item.data(0, Qt.UserRole)
        return None

    def _on_double_click(self, item, column):
        """双击发送命令"""
        template = item.data(0, Qt.UserRole)
        if template and self._send_callback:
            self._send_callback(template["command"])
            self.accept()

    def _send_selected(self):
        """发送选中的模板命令"""
        template = self._get_selected_template()
        if not template:
            QMessageBox.information(self, "提示", "请先选择一个模板")
            return
        if self._send_callback:
            self._send_callback(template["command"])
            self.accept()
        else:
            self.command_selected.emit(template["command"])
            self.accept()

    def _copy_selected(self):
        """复制命令到剪贴板"""
        template = self._get_selected_template()
        if not template:
            QMessageBox.information(self, "提示", "请先选择一个模板")
            return
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(template["command"])
        QMessageBox.information(self, "已复制", f"已复制到剪贴板:\n{template['command']}")

    def _add_template(self):
        """新建模板"""
        dialog = TemplateEditDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            db.add_command_template(**data)
            self._load_templates()

    def _edit_template(self):
        """编辑模板"""
        template = self._get_selected_template()
        if not template:
            QMessageBox.information(self, "提示", "请先选择一个模板")
            return
        dialog = TemplateEditDialog(self, template=template)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            db.update_command_template(template["id"], **data)
            self._load_templates()

    def _delete_template(self):
        """删除模板"""
        template = self._get_selected_template()
        if not template:
            QMessageBox.information(self, "提示", "请先选择一个模板")
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除模板 [{template['name']}] 吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            db.delete_command_template(template["id"])
            self._load_templates()
