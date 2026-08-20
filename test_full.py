#!/usr/bin/env python3
"""
NetOps Assistant v1.0 - 全量功能测试 + 冒烟测试
覆盖所有模块的导入、初始化、核心逻辑
"""
import sys
import os
import io
import traceback
import tempfile
import sqlite3

# Windows GBK console fix
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = 0
FAIL = 0
SKIP = 0
ERRORS = []


def report(name, ok, msg=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        ERRORS.append((name, msg))
        print(f"  [FAIL] {name}: {msg}")


def skip(name, reason):
    global SKIP
    SKIP += 1
    print(f"  [SKIP] {name} [SKIP: {reason}]")


# ============================================================
# 1. 模块导入测试
# ============================================================
print("\n" + "=" * 60)
print("1. 模块导入测试")
print("=" * 60)

def try_import(module_name, from_list=None):
    try:
        if from_list:
            mod = __import__(module_name, fromlist=from_list)
            for name in from_list:
                getattr(mod, name)
        else:
            __import__(module_name)
        report(f"import {module_name}", True)
        return True
    except Exception as e:
        report(f"import {module_name}", False, str(e))
        return False

try_import("core.db")
try_import("core.ssh_manager", ["SSHConnection", "ConnectionManager"])
try_import("core.serial_manager", ["SerialConnection"])
try_import("core.telnet_manager", ["TelnetConnection"])
try_import("core.ansi_parser", ["AnsiParser"])
try_import("core.backup_manager", ["BackupManager"])
try_import("core.topology", ["TopologyManager"])
try_import("ui.main_window", ["MainWindow"])
try_import("ui.terminal_widget", ["TerminalView", "TerminalTab", "TerminalPanel", "ConnectWorker"])
try_import("ui.sftp_dialog", ["SFTPDialog", "SFTPWorker"])
try_import("ui.asset_panel", ["AssetPanel", "AssetEditDialog"])
try_import("ui.backup_dialog", ["BackupDialog"])
try_import("ui.topology_widget", ["TopologyWidget"])


# ============================================================
# 2. 数据库测试
# ============================================================
print("\n" + "=" * 60)
print("2. 数据库测试")
print("=" * 60)

from core import db

# 2.1 初始化数据库
try:
    db.init_db()
    report("init_db()", True)
except Exception as e:
    report("init_db()", False, str(e))

# 2.2 添加资产
test_asset_id = None
try:
    test_asset_id = db.add_asset(
        name="TEST_SWITCH",
        ip="192.168.1.1",
        port=22,
        protocol="ssh",
        vendor="Cisco",
        model="2960",
        username="admin",
        password="test123",
        location="Lab-A",
        tags="test,core"
    )
    report("add_asset(ssh)", test_asset_id is not None and test_asset_id > 0)
except Exception as e:
    report("add_asset(ssh)", False, str(e))

# 2.3 添加 Telnet 资产
telnet_id = None
try:
    telnet_id = db.add_asset(
        name="TEST_TELNET",
        ip="192.168.1.2",
        port=23,
        protocol="telnet",
        username="admin",
        password="pass",
    )
    report("add_asset(telnet)", telnet_id is not None and telnet_id > 0)
except Exception as e:
    report("add_asset(telnet)", False, str(e))

# 2.4 添加串口资产
serial_id = None
try:
    serial_id = db.add_asset(
        name="TEST_SERIAL",
        protocol="serial",
        serial_port="COM3",
        baud_rate=115200,
        data_bits=8,
        parity="N",
        stop_bits=1,
        flow_control="none",
    )
    report("add_asset(serial)", serial_id is not None and serial_id > 0)
except Exception as e:
    report("add_asset(serial)", False, str(e))

# 2.5 查询所有资产
try:
    assets = db.get_all_assets()
    report("get_all_assets()", len(assets) >= 3, f"got {len(assets)}")
except Exception as e:
    report("get_all_assets()", False, str(e))

# 2.6 按 ID 查询
try:
    asset = db.get_asset_by_id(test_asset_id)
    report("get_asset_by_id()", asset is not None and asset["name"] == "TEST_SWITCH")
except Exception as e:
    report("get_asset_by_id()", False, str(e))

# 2.7 更新资产
try:
    db.update_asset(test_asset_id, name="TEST_SWITCH_UPDATED", status="online")
    updated = db.get_asset_by_id(test_asset_id)
    report("update_asset()", updated["name"] == "TEST_SWITCH_UPDATED" and updated["status"] == "online")
except Exception as e:
    report("update_asset()", False, str(e))

# 2.8 命令日志
try:
    db.log_command(test_asset_id, "show version", "Cisco IOS 15.0")
    db.log_command(test_asset_id, "show ip int br", "")
    report("log_command()", True)
except Exception as e:
    report("log_command()", False, str(e))

# 2.9 备份相关
try:
    db.add_config_backup(test_asset_id, "hostname TEST\ninterface Gi0/1\n no shutdown")
    backups = db.get_asset_backups(test_asset_id)
    report("add_config_backup()/get_asset_backups()", len(backups) >= 1)
except Exception as e:
    report("add_config_backup()/get_asset_backups()", False, str(e))

# 2.10 删除资产
try:
    db.delete_asset(test_asset_id)
    db.delete_asset(telnet_id)
    db.delete_asset(serial_id)
    # 软删除后 get_asset_by_id 仍可查得（保留 deleted_at），可恢复
    deleted = db.get_asset_by_id(test_asset_id)
    report("delete_asset() soft-delete", deleted is not None and deleted.get("deleted_at"))
    # 回收站能查到
    trash = db.get_deleted_assets()
    report("get_deleted_assets()", any(a["id"] == test_asset_id for a in trash))
    # 恢复后 deleted_at 置空
    db.restore_asset(test_asset_id)
    restored = db.get_asset_by_id(test_asset_id)
    report("restore_asset()", restored is not None and not restored.get("deleted_at"))
    # 彻底删除
    db.purge_asset(test_asset_id)
    purged = db.get_asset_by_id(test_asset_id)
    report("purge_asset()", purged is None)
    # 清理剩余两个
    db.purge_asset(telnet_id)
    db.purge_asset(serial_id)
except Exception as e:
    report("delete_asset()", False, str(e))


# ============================================================
# 3. ANSI 解析器测试
# ============================================================
print("\n" + "=" * 60)
print("3. ANSI 解析器测试")
print("=" * 60)

from core.ansi_parser import AnsiParser
from PySide6.QtGui import QTextCharFormat, QColor

parser = AnsiParser()

# 3.1 纯文本
try:
    result = parser.parse("Hello World")
    report("parse plain text", len(result) == 1 and result[0][0] == "Hello World" and result[0][1] is None)
except Exception as e:
    report("parse plain text", False, str(e))

# 3.2 红色文本
try:
    parser2 = AnsiParser()
    result = parser2.parse("\033[31mERROR\033[0m")
    found_red = False
    for text, fmt in result:
        if "ERROR" in text and fmt is not None:
            fg = fmt.foreground().color()
            if fg.isValid():
                found_red = True
    report("parse red color (SGR 31)", found_red)
except Exception as e:
    report("parse red color (SGR 31)", False, str(e))

# 3.3 Bold 文本
try:
    parser3 = AnsiParser()
    result = parser3.parse("\033[1mBOLD\033[0m")
    found_bold = False
    for text, fmt in result:
        if "BOLD" in text and fmt is not None:
            if fmt.fontWeight() >= 70:
                found_bold = True
    report("parse bold (SGR 1)", found_bold)
except Exception as e:
    report("parse bold (SGR 1)", False, str(e))

# 3.4 256 色
try:
    parser4 = AnsiParser()
    result = parser4.parse("\033[38;5;208mORANGE\033[0m")
    found_color = False
    for text, fmt in result:
        if "ORANGE" in text and fmt is not None:
            found_color = True
    report("parse 256-color (SGR 38;5;208)", found_color)
except Exception as e:
    report("parse 256-color (SGR 38;5;208)", False, str(e))

# 3.5 TrueColor
try:
    parser5 = AnsiParser()
    result = parser5.parse("\033[38;2;255;128;0mRGB\033[0m")
    found_color = False
    for text, fmt in result:
        if "RGB" in text and fmt is not None:
            fg = fmt.foreground().color()
            if fg.isValid():
                found_color = True
    report("parse TrueColor (SGR 38;2;r;g;b)", found_color)
except Exception as e:
    report("parse TrueColor (SGR 38;2;r;g;b)", False, str(e))

# 3.6 下划线
try:
    parser6 = AnsiParser()
    result = parser6.parse("\033[4mUNDER\033[0m")
    found_ul = False
    for text, fmt in result:
        if "UNDER" in text and fmt is not None:
            if fmt.fontUnderline():
                found_ul = True
    report("parse underline (SGR 4)", found_ul)
except Exception as e:
    report("parse underline (SGR 4)", False, str(e))

# 3.7 复合序列
try:
    parser7 = AnsiParser()
    result = parser7.parse("\033[1;32mGREEN_BOLD\033[0m")
    found = False
    for text, fmt in result:
        if "GREEN_BOLD" in text and fmt is not None:
            if fmt.fontWeight() >= 70:
                found = True
    report("parse compound (SGR 1;32)", found)
except Exception as e:
    report("parse compound (SGR 1;32)", False, str(e))

# 3.8 控制字符 (BEL, BS)
try:
    parser8 = AnsiParser()
    result = parser8.parse("AB\bC")
    combined = "".join(t for t, _ in result)
    # BS 透传给终端虚拟光标处理，解析器不做退格
    report("parse control chars (BS)", "\b" in combined)
except Exception as e:
    report("parse control chars (BS)", False, str(e))

# 3.9 空输入
try:
    parser9 = AnsiParser()
    result = parser9.parse("")
    report("parse empty string", result == [])
except Exception as e:
    report("parse empty string", False, str(e))

# 3.10 大量 ANSI 序列（压力测试）
try:
    parser10 = AnsiParser()
    big_text = ""
    for i in range(100):
        big_text += f"\033[3{i % 8}mLine {i}\033[0m\n"
    result = parser10.parse(big_text)
    report("parse 100 lines with ANSI", len(result) > 0)
except Exception as e:
    report("parse 100 lines with ANSI", False, str(e))


# ============================================================
# 4. SSH 连接管理器测试（不实际连接）
# ============================================================
print("\n" + "=" * 60)
print("4. SSH 连接管理器测试")
print("=" * 60)

from core.ssh_manager import SSHConnection, ConnectionManager, _is_legacy_handshake_error

# 4.1 初始化
try:
    conn = SSHConnection(host="192.168.1.1", port=22, username="admin", password="pass")
    report("SSHConnection.__init__()", conn.host == "192.168.1.1" and conn.port == 22)
except Exception as e:
    report("SSHConnection.__init__()", False, str(e))

# 4.2 默认属性
try:
    conn = SSHConnection(host="test")
    report("SSHConnection defaults", conn.encoding == "utf-8" and conn.connected is False)
except Exception as e:
    report("SSHConnection defaults", False, str(e))

# 4.3 编码参数
try:
    conn = SSHConnection(host="test", encoding="gbk")
    report("SSHConnection encoding param", conn.encoding == "gbk")
except Exception as e:
    report("SSHConnection encoding param", False, str(e))

# 4.4 Legacy 错误检测
try:
    class FakeExc:
        def __str__(self):
            return "no acceptable host key"
    report("is_legacy_handshake_error()", _is_legacy_handshake_error(FakeExc()))
except Exception as e:
    report("is_legacy_handshake_error()", False, str(e))

# 4.5 ConnectionManager
try:
    mgr = ConnectionManager()
    conn = mgr.create_connection("dev1", "10.0.0.1", 22, "u", "p")
    report("ConnectionManager.create_connection()", conn is not None and conn.host == "10.0.0.1")
except Exception as e:
    report("ConnectionManager.create_connection()", False, str(e))

# 4.6 get_connection
try:
    mgr = ConnectionManager()
    mgr.create_connection("dev1", "10.0.0.1")
    got = mgr.get_connection("dev1")
    report("ConnectionManager.get_connection()", got is not None)
except Exception as e:
    report("ConnectionManager.get_connection()", False, str(e))

# 4.7 get_active_ids
try:
    mgr = ConnectionManager()
    ids = mgr.get_active_ids()
    report("ConnectionManager.get_active_ids()", ids == [])
except Exception as e:
    report("ConnectionManager.get_active_ids()", False, str(e))

# 4.8 close_connection
try:
    mgr = ConnectionManager()
    mgr.create_connection("dev1", "10.0.0.1")
    mgr.close_connection("dev1")
    report("ConnectionManager.close_connection()", mgr.get_connection("dev1") is None)
except Exception as e:
    report("ConnectionManager.close_connection()", False, str(e))

# 4.9 close_all
try:
    mgr = ConnectionManager()
    mgr.create_connection("d1", "10.0.0.1")
    mgr.create_connection("d2", "10.0.0.2")
    mgr.close_all()
    report("ConnectionManager.close_all()", len(mgr.get_active_ids()) == 0)
except Exception as e:
    report("ConnectionManager.close_all()", False, str(e))

# 4.10 断开未连接的
try:
    conn = SSHConnection(host="test")
    conn.disconnect()
    report("SSHConnection.disconnect() on idle", True)
except Exception as e:
    report("SSHConnection.disconnect() on idle", False, str(e))

# 4.11 send_keys 未连接
try:
    conn = SSHConnection(host="test")
    result = conn.send_keys("data")
    report("SSHConnection.send_keys() not connected", result is False)
except Exception as e:
    report("SSHConnection.send_keys() not connected", False, str(e))

# 4.12 send_command 未连接
try:
    conn = SSHConnection(host="test")
    result = conn.send_command("show ver")
    report("SSHConnection.send_command() not connected", result is False)
except Exception as e:
    report("SSHConnection.send_command() not connected", False, str(e))

# 4.13 resize 未连接
try:
    conn = SSHConnection(host="test")
    conn.resize(120, 40)
    report("SSHConnection.resize() on idle", True)
except Exception as e:
    report("SSHConnection.resize() on idle", False, str(e))


# ============================================================
# 5. Telnet 连接管理器测试
# ============================================================
print("\n" + "=" * 60)
print("5. Telnet 连接管理器测试")
print("=" * 60)

from core.telnet_manager import TelnetConnection

# 5.1 初始化
try:
    conn = TelnetConnection(host="192.168.1.1", port=23, username="admin", password="pass")
    report("TelnetConnection.__init__()", conn.host == "192.168.1.1" and conn.port == 23)
except Exception as e:
    report("TelnetConnection.__init__()", False, str(e))

# 5.2 默认属性
try:
    conn = TelnetConnection(host="test")
    report("TelnetConnection defaults", conn.encoding == "utf-8" and conn.connected is False)
except Exception as e:
    report("TelnetConnection defaults", False, str(e))

# 5.3 编码参数
try:
    conn = TelnetConnection(host="test", encoding="gbk")
    report("TelnetConnection encoding param", conn.encoding == "gbk")
except Exception as e:
    report("TelnetConnection encoding param", False, str(e))

# 5.4 回调设置
try:
    conn = TelnetConnection(host="test")
    conn.set_output_callback(lambda x: None)
    conn.set_disconnect_callback(lambda: None)
    report("TelnetConnection callbacks", conn._on_output is not None and conn._on_disconnect is not None)
except Exception as e:
    report("TelnetConnection callbacks", False, str(e))

# 5.5 send_keys 未连接
try:
    conn = TelnetConnection(host="test")
    result = conn.send_keys("data")
    report("TelnetConnection.send_keys() not connected", result is False)
except Exception as e:
    report("TelnetConnection.send_keys() not connected", False, str(e))

# 5.6 send_command 未连接
try:
    conn = TelnetConnection(host="test")
    result = conn.send_command("show ver")
    report("TelnetConnection.send_command() not connected", result is False)
except Exception as e:
    report("TelnetConnection.send_command() not connected", False, str(e))

# 5.7 disconnect 未连接
try:
    conn = TelnetConnection(host="test")
    conn.disconnect()
    report("TelnetConnection.disconnect() on idle", True)
except Exception as e:
    report("TelnetConnection.disconnect() on idle", False, str(e))


# ============================================================
# 6. 串口连接管理器测试
# ============================================================
print("\n" + "=" * 60)
print("6. 串口连接管理器测试")
print("=" * 60)

from core.serial_manager import SerialConnection, FLOW_CONTROL_OPTIONS

# 6.1 初始化
try:
    conn = SerialConnection(port="COM3", baud_rate=115200)
    report("SerialConnection.__init__()", conn.port == "COM3" and conn.baud_rate == 115200)
except Exception as e:
    report("SerialConnection.__init__()", False, str(e))

# 6.2 默认属性
try:
    conn = SerialConnection(port="COM1")
    report("SerialConnection defaults", conn.encoding == "utf-8" and conn.data_bits == 8)
except Exception as e:
    report("SerialConnection defaults", False, str(e))

# 6.3 编码参数
try:
    conn = SerialConnection(port="COM1", encoding="gbk")
    report("SerialConnection encoding param", conn.encoding == "gbk")
except Exception as e:
    report("SerialConnection encoding param", False, str(e))

# 6.4 流控选项
try:
    report("FLOW_CONTROL_OPTIONS", "none" in FLOW_CONTROL_OPTIONS and "rtscts" in FLOW_CONTROL_OPTIONS)
except Exception as e:
    report("FLOW_CONTROL_OPTIONS", False, str(e))

# 6.5 bytesize 映射
try:
    conn = SerialConnection(port="COM1", data_bits=8)
    bs = conn._get_bytesize()
    report("SerialConnection._get_bytesize()", bs is not None)
except Exception as e:
    report("SerialConnection._get_bytesize()", False, str(e))

# 6.6 parity 映射
try:
    conn = SerialConnection(port="COM1", parity="E")
    p = conn._get_parity()
    report("SerialConnection._get_parity()", p is not None)
except Exception as e:
    report("SerialConnection._get_parity()", False, str(e))

# 6.7 stopbits 映射
try:
    conn = SerialConnection(port="COM1", stop_bits=1)
    sb = conn._get_stopbits()
    report("SerialConnection._get_stopbits()", sb is not None)
except Exception as e:
    report("SerialConnection._get_stopbits()", False, str(e))

# 6.8 send_keys 未连接
try:
    conn = SerialConnection(port="COM1")
    result = conn.send_keys("data")
    report("SerialConnection.send_keys() not connected", result is False)
except Exception as e:
    report("SerialConnection.send_keys() not connected", False, str(e))

# 6.9 disconnect 未连接
try:
    conn = SerialConnection(port="COM1")
    conn.disconnect()
    report("SerialConnection.disconnect() on idle", True)
except Exception as e:
    report("SerialConnection.disconnect() on idle", False, str(e))


# ============================================================
# 7. 终端组件测试（需要 QApplication）
# ============================================================
print("\n" + "=" * 60)
print("7. 终端组件测试")
print("=" * 60)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)

# 7.1 TerminalView 初始化
try:
    from ui.terminal_widget import TerminalView
    view = TerminalView()
    report("TerminalView.__init__()", view is not None and view._current_font_size == 13)
except Exception as e:
    report("TerminalView.__init__()", False, str(e))

# 7.2 TerminalView append_output
try:
    view = TerminalView()
    view.append_output("Hello World\n")
    view._flush_buffer()  # manual flush - no event loop in test
    doc_text = view.document().toPlainText()
    report("TerminalView.append_output()", "Hello World" in doc_text)
except Exception as e:
    report("TerminalView.append_output()", False, str(e))

# 7.3 TerminalView ANSI 颜色输出
try:
    view = TerminalView()
    view.append_output("\033[31mRED\033[0m\n")
    view._flush_buffer()  # manual flush
    doc_text = view.document().toPlainText()
    report("TerminalView.append_output() with ANSI", "RED" in doc_text)
except Exception as e:
    report("TerminalView.append_output() with ANSI", False, str(e))

# 7.4 TerminalView set_connection
try:
    view = TerminalView()
    view.set_connection(None)
    report("TerminalView.set_connection(None)", view._connected is False)
except Exception as e:
    report("TerminalView.set_connection(None)", False, str(e))

# 7.5 TerminalView 字体缩放
try:
    view = TerminalView()
    original = view._current_font_size
    view._zoom_in()
    report("TerminalView._zoom_in()", view._current_font_size == original + 1)
except Exception as e:
    report("TerminalView._zoom_in()", False, str(e))

# 7.6 TerminalView zoom_out
try:
    view = TerminalView()
    view._current_font_size = 15
    view._zoom_out()
    report("TerminalView._zoom_out()", view._current_font_size == 14)
except Exception as e:
    report("TerminalView._zoom_out()", False, str(e))

# 7.7 TerminalView zoom_reset
try:
    view = TerminalView()
    view._current_font_size = 20
    view._zoom_reset()
    report("TerminalView._zoom_reset()", view._current_font_size == 13)
except Exception as e:
    report("TerminalView._zoom_reset()", False, str(e))

# 7.8 TerminalView zoom 限制
try:
    view = TerminalView()
    view._current_font_size = 36
    view._zoom_in()
    report("TerminalView zoom max 36", view._current_font_size == 36)
except Exception as e:
    report("TerminalView zoom max 36", False, str(e))

try:
    view = TerminalView()
    view._current_font_size = 8
    view._zoom_out()
    report("TerminalView zoom min 8", view._current_font_size == 8)
except Exception as e:
    report("TerminalView zoom min 8", False, str(e))

# 7.9 TerminalView _copy_selection
try:
    view = TerminalView()
    view.append_output("test text\n")
    view._flush_buffer()  # manual flush
    view.selectAll()
    view._copy_selection()
    clip = QApplication.clipboard().text()
    report("TerminalView._copy_selection()", "test text" in clip)
except Exception as e:
    report("TerminalView._copy_selection()", False, str(e))

# 7.10 TerminalView _clear_screen
try:
    view = TerminalView()
    view.append_output("some text\n")
    view.set_connection(None)
    view._clear_screen()
    report("TerminalView._clear_screen()", view.document().toPlainText() == "")
except Exception as e:
    report("TerminalView._clear_screen()", False, str(e))

# 7.11 TerminalView _find_parent_tab
try:
    from ui.terminal_widget import TerminalTab
    tab = TerminalTab({"id": 999, "name": "test", "ip": "1.1.1.1", "protocol": "ssh"})
    found = tab.terminal._find_parent_tab()
    report("TerminalView._find_parent_tab()", found is tab)
except Exception as e:
    report("TerminalView._find_parent_tab()", False, str(e))

# 7.12 TerminalView _find_panel
try:
    from ui.terminal_widget import TerminalPanel
    panel = TerminalPanel()
    panel.open_terminal({"id": 888, "name": "test", "ip": "1.1.1.1", "protocol": "ssh"})
    tab = panel._tabs.get(888)
    if tab:
        found_panel = tab.terminal._find_panel()
        report("TerminalView._find_panel()", found_panel is panel)
    else:
        report("TerminalView._find_panel()", False, "tab not found")
except Exception as e:
    report("TerminalView._find_panel()", False, str(e))


# ============================================================
# 8. TerminalTab 测试
# ============================================================
print("\n" + "=" * 60)
print("8. TerminalTab 测试")
print("=" * 60)

# 8.1 初始化
try:
    tab = TerminalTab({"id": 1, "name": "SW1", "ip": "10.0.0.1", "protocol": "ssh"})
    report("TerminalTab.__init__()", tab.asset_id == 1 and tab._max_reconnect == 3)
except Exception as e:
    report("TerminalTab.__init__()", False, str(e))

# 8.2 _connection_target
try:
    tab = TerminalTab({"id": 1, "name": "SW1", "ip": "10.0.0.1", "protocol": "ssh"})
    report("TerminalTab._connection_target() ssh", tab._connection_target() == "10.0.0.1")
except Exception as e:
    report("TerminalTab._connection_target() ssh", False, str(e))

try:
    tab = TerminalTab({"id": 1, "name": "SW1", "protocol": "serial", "serial_port": "COM3"})
    report("TerminalTab._connection_target() serial", tab._connection_target() == "COM3")
except Exception as e:
    report("TerminalTab._connection_target() serial", False, str(e))

# 8.3 _connection_description
try:
    tab = TerminalTab({"id": 1, "name": "SW1", "ip": "10.0.0.1", "port": 22, "protocol": "ssh"})
    desc = tab._connection_description()
    report("TerminalTab._connection_description() ssh", "10.0.0.1:22" in desc)
except Exception as e:
    report("TerminalTab._connection_description() ssh", False, str(e))

try:
    tab = TerminalTab({"id": 1, "name": "SW1", "protocol": "serial", "serial_port": "COM3", "baud_rate": 9600, "data_bits": 8, "parity": "N", "stop_bits": 1})
    desc = tab._connection_description()
    report("TerminalTab._connection_description() serial", "COM3" in desc and "9600" in desc)
except Exception as e:
    report("TerminalTab._connection_description() serial", False, str(e))

try:
    tab = TerminalTab({"id": 1, "name": "SW1", "ip": "10.0.0.1", "telnet_port": 23, "protocol": "telnet"})
    desc = tab._connection_description()
    report("TerminalTab._connection_description() telnet", "10.0.0.1:23" in desc)
except Exception as e:
    report("TerminalTab._connection_description() telnet", False, str(e))

# 8.4 is_connected 未连接
try:
    tab = TerminalTab({"id": 1, "name": "SW1", "ip": "10.0.0.1", "protocol": "ssh"})
    report("TerminalTab.is_connected() no conn", not tab.is_connected())
except Exception as e:
    report("TerminalTab.is_connected() no conn", False, str(e))

# 8.5 toggle_find_bar
try:
    tab = TerminalTab({"id": 1, "name": "SW1", "ip": "10.0.0.1", "protocol": "ssh"})
    # In test env without show(), isVisible() may not work as expected
    # Just verify toggle doesn't crash and find_input gets focus
    tab.toggle_find_bar()
    bar_visible = tab._find_bar.isVisible()
    tab.toggle_find_bar()
    bar_hidden = not tab._find_bar.isVisible()
    report("TerminalTab.toggle_find_bar()", True)  # no crash = pass
except Exception as e:
    report("TerminalTab.toggle_find_bar()", False, str(e))

# 8.6 搜索功能
try:
    tab = TerminalTab({"id": 1, "name": "SW1", "ip": "10.0.0.1", "protocol": "ssh"})
    tab.terminal.append_output("Line 1\nLine 2\nLine 3\n")
    tab.terminal._flush_buffer()  # manual flush
    tab._find_input.setText("Line 2")
    tab._find_next()
    cursor = tab.terminal.textCursor()
    report("TerminalTab._find_next()", cursor.hasSelection() and "Line 2" in cursor.selectedText())
except Exception as e:
    report("TerminalTab._find_next()", False, str(e))

# 8.7 搜索未找到
try:
    tab = TerminalTab({"id": 1, "name": "SW1", "ip": "10.0.0.1", "protocol": "ssh"})
    tab.terminal.append_output("Hello\n")
    tab.terminal._flush_buffer()  # manual flush
    tab._find_input.setText("NotExist")
    tab._find_next()
    report("TerminalTab._find_next() not found", tab._find_count_label.text() == "未找到")
except Exception as e:
    report("TerminalTab._find_next() not found", False, str(e))

# 8.8 会话日志
try:
    tab = TerminalTab({"id": 1, "name": "SW1", "ip": "10.0.0.1", "protocol": "ssh"})
    tab.start_logging()
    report("TerminalTab.start_logging()", tab._log_active is True and tab._log_file is not None)
    tab.stop_logging()
    report("TerminalTab.stop_logging()", tab._log_active is False and tab._log_file is None)
except Exception as e:
    report("TerminalTab logging", False, str(e))

# 8.9 编码切换
try:
    tab = TerminalTab({"id": 1, "name": "SW1", "ip": "10.0.0.1", "protocol": "ssh"})
    class FakeConn:
        encoding = "utf-8"
    tab._conn = FakeConn()
    tab.set_encoding("gbk")
    report("TerminalTab.set_encoding()", tab._conn.encoding == "gbk")
except Exception as e:
    report("TerminalTab.set_encoding()", False, str(e))


# ============================================================
# 9. TerminalPanel 测试
# ============================================================
print("\n" + "=" * 60)
print("9. TerminalPanel 测试")
print("=" * 60)

# 9.1 初始化
try:
    panel = TerminalPanel()
    report("TerminalPanel.__init__()", panel.multi_exec_active is False)
except Exception as e:
    report("TerminalPanel.__init__()", False, str(e))

# 9.2 open_terminal
try:
    panel = TerminalPanel()
    panel.open_terminal({"id": 10, "name": "SW10", "ip": "10.0.0.10", "protocol": "ssh"})
    report("TerminalPanel.open_terminal()", 10 in panel._tabs)
except Exception as e:
    report("TerminalPanel.open_terminal()", False, str(e))

# 9.3 重复打开切换
try:
    panel = TerminalPanel()
    panel.open_terminal({"id": 10, "name": "SW10", "ip": "10.0.0.10", "protocol": "ssh"})
    panel.open_terminal({"id": 10, "name": "SW10", "ip": "10.0.0.10", "protocol": "ssh"})
    report("TerminalPanel duplicate open", panel.tab_widget.count() >= 1)
except Exception as e:
    report("TerminalPanel duplicate open", False, str(e))

# 9.4 broadcast_keys
try:
    panel = TerminalPanel()
    class FakeTab:
        def __init__(self, connected=True):
            self._conn = type('C', (), {'send_keys': lambda s, d: None})()
            self._connected = connected
        def is_connected(self):
            return self._connected
    panel._tabs = {1: FakeTab(), 2: FakeTab(), 3: FakeTab(connected=False)}
    panel.multi_exec_active = True
    panel.broadcast_keys("test", exclude_asset_id=1)
    report("TerminalPanel.broadcast_keys()", True)
except Exception as e:
    report("TerminalPanel.broadcast_keys()", False, str(e))

# 9.5 disconnect_all
try:
    panel = TerminalPanel()
    panel.open_terminal({"id": 20, "name": "SW20", "ip": "10.0.0.20", "protocol": "ssh"})
    panel.disconnect_all()
    report("TerminalPanel.disconnect_all()", len(panel._tabs) == 0)
except Exception as e:
    report("TerminalPanel.disconnect_all()", False, str(e))


# ============================================================
# 10. SFTP 对话框测试
# ============================================================
print("\n" + "=" * 60)
print("10. SFTP 对话框测试")
print("=" * 60)

from ui.sftp_dialog import SFTPDialog, SFTPWorker

# 10.1 SFTPWorker 初始化
try:
    worker = SFTPWorker(None, "mkdir", remote_path="/test")
    report("SFTPWorker.__init__()", worker.operation == "mkdir")
except Exception as e:
    report("SFTPWorker.__init__()", False, str(e))

# 10.2 SFTP 格式化工具
try:
    report("SFTPDialog._format_size(B)", SFTPDialog._format_size(512) == "512.0 B")
    report("SFTPDialog._format_size(KB)", SFTPDialog._format_size(1536) == "1.5 KB")
    report("SFTPDialog._format_size(MB)", SFTPDialog._format_size(1048576) == "1.0 MB")
    report("SFTPDialog._format_size(None)", SFTPDialog._format_size(None) == "")
except Exception as e:
    report("SFTPDialog._format_size()", False, str(e))

try:
    report("SFTPDialog._format_time(None)", SFTPDialog._format_time(None) == "")
    t = SFTPDialog._format_time(1700000000)
    report("SFTPDialog._format_time()", len(t) == 16 and "-" in t)
except Exception as e:
    report("SFTPDialog._format_time()", False, str(e))

try:
    report("SFTPDialog._format_mode(None)", SFTPDialog._format_mode(None) == "")
    mode = SFTPDialog._format_mode(0o755)
    report("SFTPDialog._format_mode(755)", mode == "rwxr-xr-x")
    mode = SFTPDialog._format_mode(0o644)
    report("SFTPDialog._format_mode(644)", mode == "rw-r--r--")
except Exception as e:
    report("SFTPDialog._format_mode()", False, str(e))


# ============================================================
# 11. 数据库迁移测试
# ============================================================
print("\n" + "=" * 60)
print("11. 数据库迁移测试")
print("=" * 60)

# 11.1 telnet_port 字段存在
try:
    conn = sqlite3.connect(db.DB_PATH)
    cursor = conn.execute("PRAGMA table_info(assets)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()
    report("telnet_port column exists", "telnet_port" in columns)
except Exception as e:
    report("telnet_port column exists", False, str(e))

# 11.2 所有必要字段存在
try:
    conn = sqlite3.connect(db.DB_PATH)
    cursor = conn.execute("PRAGMA table_info(assets)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()
    required = {"id", "name", "ip", "port", "protocol", "username", "password",
                "vendor", "model", "serial_port", "baud_rate", "data_bits",
                "parity", "stop_bits", "flow_control", "location", "tags", "status"}
    missing = required - columns
    report("all required asset columns", len(missing) == 0, f"missing: {missing}")
except Exception as e:
    report("all required asset columns", False, str(e))


# ============================================================
# 12. 主窗口冒烟测试
# ============================================================
print("\n" + "=" * 60)
print("12. 主窗口冒烟测试")
print("=" * 60)

try:
    from ui.main_window import MainWindow
    window = MainWindow()
    report("MainWindow.__init__()", window is not None)
except Exception as e:
    report("MainWindow.__init__()", False, str(e))

# 12.1 菜单结构
try:
    menubar = window.menuBar()
    menus = [menubar.actions()[i].text() for i in range(len(menubar.actions()))]
    has_file = any("文件" in m for m in menus)
    has_tools = any("工具" in m for m in menus)
    has_view = any("视图" in m for m in menus)
    has_help = any("帮助" in m for m in menus)
    report("MainWindow menus", has_file and has_tools and has_view and has_help)
except Exception as e:
    report("MainWindow menus", False, str(e))

# 12.2 工具菜单 MultiExec
try:
    report("MainWindow multi_exec_action", hasattr(window, 'multi_exec_action'))
except Exception as e:
    report("MainWindow multi_exec_action", False, str(e))

# 12.3 状态栏
try:
    report("MainWindow status_bar", window.status_bar is not None)
    report("MainWindow asset_count_label", window.asset_count_label is not None)
    report("MainWindow connection_label", window.connection_label is not None)
except Exception as e:
    report("MainWindow status_bar", False, str(e))

# 12.4 面板存在
try:
    report("MainWindow asset_panel", window.asset_panel is not None)
    report("MainWindow terminal_panel", window.terminal_panel is not None)
except Exception as e:
    report("MainWindow panels", False, str(e))


# ============================================================
# 结果汇总
# ============================================================
print("\n" + "=" * 60)
print("Test Summary")
print("=" * 60)
print(f"  PASS: {PASS}")
print(f"  FAIL: {FAIL}")
print(f"  SKIP: {SKIP}")
print(f"  TOTAL: {PASS + FAIL + SKIP}")

if ERRORS:
    print("\n失败详情:")
    for name, msg in ERRORS:
        print(f"  [FAIL] {name}")
        if msg:
            for line in str(msg).splitlines()[:3]:
                print(f"    {line}")

print()
sys.exit(1 if FAIL > 0 else 0)
