"""
配置备份管理器 - 自动备份网络设备配置
"""
import re
import difflib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

from core import db
from core.ssh_manager import SSHConnection


# 各厂商获取配置的命令
VENDOR_COMMANDS = {
    "huawei": {
        "show_run": "display current-configuration",
        "show_version": "display version",
        "save": "save",
    },
    "cisco": {
        "show_run": "show running-config",
        "show_version": "show version",
        "save": "write memory",
    },
    "h3c": {
        "show_run": "display current-configuration",
        "show_version": "display version",
        "save": "save",
    },
    "linux": {
        "show_run": "cat /etc/network/interfaces; ip addr show; ip route show",
        "show_version": "uname -a",
        "save": "",
    },
    "default": {
        "show_run": "show running-config",
        "show_version": "show version",
        "save": "write memory",
    },
}


def get_vendor_commands(vendor: str) -> dict:
    """获取厂商对应的命令"""
    vendor_lower = vendor.lower() if vendor else ""
    for key in VENDOR_COMMANDS:
        if key in vendor_lower:
            return VENDOR_COMMANDS[key]
    return VENDOR_COMMANDS["default"]


class BackupManager:
    """配置备份管理器"""

    def __init__(self):
        self._progress_callback = None
        self._log_callback = None

    def set_callbacks(self, progress_cb=None, log_cb=None):
        """设置进度和日志回调"""
        self._progress_callback = progress_cb
        self._log_callback = log_cb

    def _report_progress(self, current: int, total: int, message: str):
        """报告进度"""
        if self._progress_callback:
            self._progress_callback(current, total, message)

    def _report_log(self, message: str):
        """报告日志"""
        if self._log_callback:
            self._log_callback(message)

    def backup_single_device(self, asset: dict) -> Tuple[bool, str, Optional[str]]:
        """
        备份单台设备配置
        返回: (成功, 消息, 配置文本)
        """
        asset_id = asset["id"]
        name = asset["name"]
        ip = asset["ip"]

        self._report_log(f"正在连接 {name} ({ip})...")

        # 创建SSH连接
        conn = SSHConnection(
            host=ip,
            port=asset.get("port", 22),
            username=asset.get("username", ""),
            password=asset.get("password", ""),
            enable_password=asset.get("enable_password", ""),
        )

        success, msg = conn.connect()
        if not success:
            self._report_log(f"连接失败: {msg}")
            return False, f"连接失败: {msg}", None

        try:
            # 获取厂商命令
            vendor = asset.get("vendor", "")
            commands = get_vendor_commands(vendor)

            # 如果有enable密码，先进入特权模式
            if asset.get("enable_password"):
                conn.enter_enable_mode(wait_time=1)

            # 获取配置（使用分页感知方法，超时30秒）
            self._report_log(f"正在获取配置...")
            config_text = conn.send_command_paged(commands["show_run"], timeout=30)

            if not config_text or len(config_text) < 50:
                self._report_log(f"配置获取失败或配置为空")
                return False, "配置获取失败", None

            # 保存到数据库
            backup_id = db.add_config_backup(asset_id, config_text, "auto")
            self._report_log(f"备份成功，备份ID: {backup_id}")

            return True, f"备份成功", config_text

        except Exception as e:
            self._report_log(f"备份异常: {e}")
            return False, f"备份异常: {e}", None

        finally:
            conn.disconnect()

    def backup_multiple_devices(self, assets: List[dict]) -> Dict[str, Tuple[bool, str]]:
        """
        批量备份多台设备
        返回: {设备名: (成功, 消息)}
        """
        results = {}
        total = len(assets)

        for i, asset in enumerate(assets):
            self._report_progress(i + 1, total, f"正在备份 {asset['name']}...")
            success, msg, _ = self.backup_single_device(asset)
            results[asset["name"]] = (success, msg)

        return results

    def backup_by_group(self, group_id: int) -> Dict[str, Tuple[bool, str]]:
        """备份指定分组的所有设备"""
        all_assets = db.get_all_assets()
        group_assets = [a for a in all_assets if a.get("group_id") == group_id]
        return self.backup_multiple_devices(group_assets)

    def backup_all_devices(self) -> Dict[str, Tuple[bool, str]]:
        """备份所有设备"""
        assets = db.get_all_assets()
        online_assets = [a for a in assets if a.get("status") == "online"]
        if not online_assets:
            return {"_error": (False, "没有在线设备，请先扫描在线状态")}
        return self.backup_multiple_devices(online_assets)

    @staticmethod
    def compare_configs(old_config: str, new_config: str) -> str:
        """
        比较两份配置的差异
        返回: 差异文本
        """
        if not old_config or not new_config:
            return "无法比较：配置为空"

        old_lines = old_config.splitlines(keepends=True)
        new_lines = new_config.splitlines(keepends=True)

        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile="旧配置", tofile="新配置",
            lineterm=""
        )

        result = "\n".join(diff)
        return result if result else "配置无变化"

    @staticmethod
    def get_config_diff_for_device(asset_id: int) -> Tuple[Optional[str], Optional[str], str]:
        """
        获取设备最近两次备份的差异
        返回: (旧配置时间, 新配置时间, 差异文本)
        """
        backups = db.get_asset_backups(asset_id, limit=2)
        if len(backups) < 2:
            return None, None, "备份记录不足，无法比较"

        new_backup = backups[0]
        old_backup = backups[1]

        diff = BackupManager.compare_configs(
            old_backup["config_text"],
            new_backup["config_text"]
        )

        return old_backup["created_at"], new_backup["created_at"], diff


class BackupScheduler:
    """备份调度器（简化版，使用定时器实现）"""

    def __init__(self, backup_manager: BackupManager):
        self.backup_manager = backup_manager
        self._timer = None
        self._running = False

    def parse_cron(self, cron_expr: str) -> dict:
        """解析简单的cron表达式"""
        parts = cron_expr.split()
        if len(parts) != 5:
            return {"minute": "0", "hour": "2", "day": "*", "month": "*", "weekday": "*"}

        return {
            "minute": parts[0],
            "hour": parts[1],
            "day": parts[2],
            "month": parts[3],
            "weekday": parts[4],
        }

    def calculate_next_run(self, cron_expr: str) -> datetime:
        """计算下次运行时间（简化版）"""
        cron = self.parse_cron(cron_expr)
        now = datetime.now()

        # 简化处理：默认每天指定时间运行
        try:
            hour = int(cron["hour"])
            minute = int(cron["minute"])
        except ValueError:
            hour, minute = 2, 0

        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            next_run = next_run + timedelta(days=1)

        return next_run

    def execute_schedule(self, schedule_id: int):
        """执行备份计划"""
        schedules = db.get_all_schedules()
        schedule = None
        for s in schedules:
            if s["id"] == schedule_id:
                schedule = s
                break

        if not schedule:
            return

        import json
        asset_ids = json.loads(schedule["asset_ids"])

        # 获取设备列表
        all_assets = db.get_all_assets()
        target_assets = [a for a in all_assets if a["id"] in asset_ids]

        # 执行备份
        results = self.backup_manager.backup_multiple_devices(target_assets)

        # 更新最后运行时间
        db.update_schedule(
            schedule_id,
            last_run=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            next_run=self.calculate_next_run(schedule["cron_expr"]).strftime("%Y-%m-%d %H:%M:%S")
        )

        return results


def export_backup_to_file(backup_id: int, file_path: str) -> bool:
    """导出备份到文件"""
    backup = db.get_backup_by_id(backup_id)
    if not backup:
        return False

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# 设备ID: {backup['asset_id']}\n")
            f.write(f"# 备份时间: {backup['created_at']}\n")
            f.write(f"# 备份类型: {backup['backup_type']}\n")
            f.write(f"# 配置哈希: {backup['config_hash']}\n")
            f.write("#" + "=" * 60 + "\n\n")
            f.write(backup["config_text"])
        return True
    except Exception:
        return False


def import_backup_from_file(asset_id: int, file_path: str) -> Tuple[bool, str]:
    """从文件导入备份"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 跳过注释头
        lines = content.split("\n")
        config_lines = []
        in_config = False
        for line in lines:
            if line.startswith("#" + "=" * 60):
                in_config = True
                continue
            if in_config or not line.startswith("#"):
                config_lines.append(line)

        config_text = "\n".join(config_lines).strip()
        if not config_text:
            return False, "配置内容为空"

        db.add_config_backup(asset_id, config_text, "import")
        return True, "导入成功"

    except Exception as e:
        return False, f"导入失败: {e}"
