"""
SFTP 文件传输对话框
通过已有 SSH 连接进行文件上传/下载
"""
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QProgressBar, QFileDialog, QMessageBox,
    QInputDialog, QHeaderView,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor


class SFTPWorker(QThread):
    """后台 SFTP 操作线程"""
    progress = Signal(int, int)  # current, total
    finished = Signal(bool, str)  # success, message

    def __init__(self, sftp, operation, local_path="", remote_path="", total=0):
        super().__init__()
        self.sftp = sftp
        self.operation = operation  # 'upload', 'download', 'mkdir', 'delete'
        self.local_path = local_path
        self.remote_path = remote_path
        self.total = total
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            if self.operation == "upload":
                self._upload()
            elif self.operation == "download":
                self._download()
            elif self.operation == "mkdir":
                self.sftp.mkdir(self.remote_path)
                self.finished.emit(True, f"已创建目录: {self.remote_path}")
            elif self.operation == "delete":
                try:
                    self.sftp.remove(self.remote_path)
                except Exception:
                    self.sftp.rmdir(self.remote_path)
                self.finished.emit(True, f"已删除: {self.remote_path}")
        except Exception as e:
            self.finished.emit(False, f"操作失败: {e}")

    def _upload(self):
        uploaded = 0

        def callback(bytes_sent, bytes_total):
            nonlocal uploaded
            uploaded = bytes_sent
            self.progress.emit(bytes_sent, bytes_total)

        self.sftp.put(self.local_path, self.remote_path, callback=callback)
        self.finished.emit(True, f"上传完成: {os.path.basename(self.local_path)}")

    def _download(self):
        downloaded = 0

        def callback(bytes_received, bytes_total):
            nonlocal downloaded
            downloaded = bytes_received
            self.progress.emit(bytes_received, bytes_total)

        self.sftp.get(self.remote_path, self.local_path, callback=callback)
        self.finished.emit(True, f"下载完成: {os.path.basename(self.remote_path)}")


class SFTPDialog(QDialog):
    """SFTP 文件传输对话框"""

    def __init__(self, ssh_connection, parent=None):
        super().__init__(parent)
        self.ssh = ssh_connection
        self.sftp = None
        self._worker = None
        self._current_path = "/"

        self.setWindowTitle("SFTP 文件传输")
        self.setMinimumSize(850, 550)
        self._setup_ui()
        self._connect_sftp()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 路径栏
        path_layout = QHBoxLayout()
        self.path_label = QLabel("路径: /")
        self.path_label.setStyleSheet("color: #cdd6f4; font-size: 13px;")
        path_layout.addWidget(self.path_label)

        path_layout.addStretch()

        up_btn = QPushButton("⬆ 上级目录")
        up_btn.setFixedHeight(32)
        up_btn.setMinimumWidth(90)
        up_btn.clicked.connect(self._go_up)
        path_layout.addWidget(up_btn)

        refresh_btn = QPushButton("⟳ 刷新")
        refresh_btn.setFixedHeight(32)
        refresh_btn.setMinimumWidth(80)
        refresh_btn.clicked.connect(self._refresh)
        path_layout.addWidget(refresh_btn)

        layout.addLayout(path_layout)

        # 文件树
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["名称", "类型", "大小", "修改时间", "权限"])
        self.tree.setColumnWidth(0, 250)
        self.tree.setColumnWidth(1, 80)
        self.tree.setColumnWidth(2, 100)
        self.tree.setColumnWidth(3, 150)
        self.tree.setColumnWidth(4, 100)
        self.tree.setRootIsDecorated(False)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.tree)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(16)
        layout.addWidget(self.progress_bar)

        # 状态标签
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(self.status_label)

        # 按钮栏
        btn_layout = QHBoxLayout()

        upload_btn = QPushButton("📤 上传文件")
        upload_btn.clicked.connect(self._upload_file)
        btn_layout.addWidget(upload_btn)

        download_btn = QPushButton("📥 下载文件")
        download_btn.clicked.connect(self._download_file)
        btn_layout.addWidget(download_btn)

        mkdir_btn = QPushButton("📁 新建目录")
        mkdir_btn.clicked.connect(self._make_directory)
        btn_layout.addWidget(mkdir_btn)

        delete_btn = QPushButton("🗑️ 删除")
        delete_btn.clicked.connect(self._delete_item)
        btn_layout.addWidget(delete_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def _connect_sftp(self):
        """建立 SFTP 连接"""
        try:
            if self.ssh and self.ssh.client:
                self.sftp = self.ssh.client.open_sftp()
                self._refresh()
                self.status_label.setText("SFTP 连接成功")
            else:
                self.status_label.setText("错误: SSH 连接不可用")
        except Exception as e:
            self.status_label.setText(f"SFTP 连接失败: {e}")

    def _refresh(self):
        """刷新当前目录"""
        if not self.sftp:
            return
        try:
            self.tree.clear()
            entries = self.sftp.listdir_attr(self._current_path)
            # 排序：目录在前，文件在后
            dirs = []
            files = []
            for entry in entries:
                if entry.filename in (".", ".."):
                    continue
                if entry.st_mode and entry.st_mode & 0o170000 == 0o040000:
                    dirs.append(entry)
                else:
                    files.append(entry)

            for entry in sorted(dirs, key=lambda e: e.filename):
                item = QTreeWidgetItem(self.tree)
                item.setText(0, f"📁 {entry.filename}")
                item.setText(1, "目录")
                item.setText(2, "")
                item.setText(3, self._format_time(entry.st_mtime))
                item.setText(4, self._format_mode(entry.st_mode))
                item.setData(0, Qt.UserRole, {
                    "name": entry.filename,
                    "is_dir": True,
                    "mode": entry.st_mode,
                })
                item.setForeground(0, QColor("#89b4fa"))

            for entry in sorted(files, key=lambda e: e.filename):
                item = QTreeWidgetItem(self.tree)
                item.setText(0, f"📄 {entry.filename}")
                item.setText(1, "文件")
                item.setText(2, self._format_size(entry.st_size))
                item.setText(3, self._format_time(entry.st_mtime))
                item.setText(4, self._format_mode(entry.st_mode))
                item.setData(0, Qt.UserRole, {
                    "name": entry.filename,
                    "is_dir": False,
                    "size": entry.st_size,
                })

            self.path_label.setText(f"路径: {self._current_path}")
        except Exception as e:
            self.status_label.setText(f"刷新失败: {e}")

    def _on_item_double_clicked(self, item, column):
        data = item.data(0, Qt.UserRole)
        if data and data.get("is_dir"):
            self._current_path = self._current_path.rstrip("/") + "/" + data["name"]
            self._refresh()

    def _go_up(self):
        if self._current_path == "/":
            return
        parent = "/".join(self._current_path.rstrip("/").split("/")[:-1])
        self._current_path = parent if parent else "/"
        self._refresh()

    def _upload_file(self):
        if not self.sftp:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "选择上传文件")
        if not file_path:
            return
        remote_path = self._current_path.rstrip("/") + "/" + os.path.basename(file_path)
        self._run_operation("upload", local_path=file_path, remote_path=remote_path)

    def _download_file(self):
        if not self.sftp:
            return
        item = self.tree.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先选择要下载的文件")
            return
        data = item.data(0, Qt.UserRole)
        if not data or data.get("is_dir"):
            QMessageBox.information(self, "提示", "请选择文件而非目录")
            return
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存文件", data["name"]
        )
        if not save_path:
            return
        remote_path = self._current_path.rstrip("/") + "/" + data["name"]
        self._run_operation("download", local_path=save_path, remote_path=remote_path)

    def _make_directory(self):
        if not self.sftp:
            return
        name, ok = QInputDialog.getText(self, "新建目录", "目录名称:")
        if not ok or not name.strip():
            return
        remote_path = self._current_path.rstrip("/") + "/" + name.strip()
        self._run_operation("mkdir", remote_path=remote_path)

    def _delete_item(self):
        if not self.sftp:
            return
        item = self.tree.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先选择要删除的项目")
            return
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除 [{data['name']}] 吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        remote_path = self._current_path.rstrip("/") + "/" + data["name"]
        self._run_operation("delete", remote_path=remote_path)

    def _run_operation(self, operation, local_path="", remote_path=""):
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"正在执行: {operation}...")

        self._worker = SFTPWorker(
            self.sftp, operation, local_path, remote_path
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_operation_finished)
        self._worker.start()

    def _on_progress(self, current, total):
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)

    def _on_operation_finished(self, success, message):
        self.progress_bar.setVisible(False)
        self.status_label.setText(message)
        if success:
            self._refresh()

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        if self.sftp:
            try:
                self.sftp.close()
            except Exception:
                pass
        event.accept()

    @staticmethod
    def _format_size(size):
        if size is None:
            return ""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @staticmethod
    def _format_time(mtime):
        if mtime is None:
            return ""
        from datetime import datetime
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _format_mode(mode):
        if mode is None:
            return ""
        perms = ["---", "--x", "-w-", "-wx", "r--", "r-x", "rw-", "rwx"]
        result = ""
        for shift in (6, 3, 0):
            result += perms[(mode >> shift) & 7]
        return result
