#!/usr/bin/env python3
"""拓扑解析器单元测试 - P0 修复回归测试"""
import sys
import os
import io
import json
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = 0
FAIL = 0
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


from core.topology import TopologyManager

mgr = TopologyManager()

# ============================================================
# Test 1: Huawei LLDP brief 输出（含表头、统计行）
# ============================================================
print("=" * 60)
print("Test 1: Huawei LLDP brief 解析")
print("=" * 60)

HUAWEI_LLDP = """
Local Interface    Neighbor Dev    Neighbor Intf
GE0/0/1            DeviceA          GE0/0/2
GE0/0/2            DeviceB          GE0/0/1
GE0/0/3            DeviceC          100GE1/0/1

Total items: 3
"""

neighbors = mgr._parse_lldp_output(HUAWEI_LLDP, "huawei")
report("发现 3 个邻居（不误吃统计行）", len(neighbors) == 3, f"实际 {len(neighbors)}")
if len(neighbors) == 3:
    report("第一个邻居 local_intf",
           neighbors[0].local_interface == "GE0/0/1",
           f"实际 {neighbors[0].local_interface}")
    report("第一个邻居 remote_name",
           neighbors[0].remote_name == "DeviceA",
           f"实际 {neighbors[0].remote_name}")
    report("第一个邻居 remote_interface",
           neighbors[0].remote_interface == "GE0/0/2",
           f"实际 {neighbors[0].remote_interface}")
    report("第三个邻居 remote_interface（含数字前缀）",
           neighbors[2].remote_interface == "100GE1/0/1",
           f"实际 {neighbors[2].remote_interface}")

# 验证不误吃 "Total items: 3"
bad_neighbors = [n for n in neighbors if n.remote_name in ("Total", "items:")]
report("不误吃 'Total items: 3'", len(bad_neighbors) == 0,
       f"误吃 {len(bad_neighbors)} 条")

# ============================================================
# Test 2: H3C LLDP 输出
# ============================================================
print("\n" + "=" * 60)
print("Test 2: H3C LLDP 解析")
print("=" * 60)

H3C_LLDP = """
Local Interface   Neighbor Dev     Neighbor Intf
G1/0/1            SW-Core-01       G1/0/2
G1/0/2            SW-Core-02       G1/0/1
"""

neighbors = mgr._parse_lldp_output(H3C_LLDP, "h3c")
report("发现 2 个邻居", len(neighbors) == 2, f"实际 {len(neighbors)}")
if neighbors:
    report("H3C 邻居名正确",
           neighbors[0].remote_name == "SW-Core-01",
           f"实际 {neighbors[0].remote_name}")

# ============================================================
# Test 3: Cisco LLDP brief 输出（验证列映射修复）
# ============================================================
print("\n" + "=" * 60)
print("Test 3: Cisco LLDP brief 列映射")
print("=" * 60)

CISCO_LLDP = """
Capability codes:
    (R) Router, (B) Bridge, (T) Telephone, (C) DOCSIS Cable Device
Device ID           Local Intf      Hold-time  Capability      Port ID
DeviceA.example.com Gi0/1            120        R               Gi0/2
DeviceB             Gi0/2            90         B               Gi0/1

Total entries displayed: 2
"""

neighbors = mgr._parse_lldp_output(CISCO_LLDP, "cisco")
report("发现 2 个邻居", len(neighbors) == 2, f"实际 {len(neighbors)}")
if len(neighbors) >= 1:
    n = neighbors[0]
    report("Cisco remote_name = DeviceID",
           n.remote_name == "DeviceA.example.com",
           f"实际 {n.remote_name}")
    report("Cisco local_intf = Local Intf",
           n.local_interface == "Gi0/1",
           f"实际 {n.local_interface}")
    report("Cisco remote_interface = Port ID（最后一列）",
           n.remote_interface == "Gi0/2",
           f"实际 {n.remote_interface}")

# 不误吃 Capability codes 说明行
bad = [n for n in neighbors if "Capability" in n.remote_name or "codes" in n.remote_name]
report("不误吃 'Capability codes' 说明行", len(bad) == 0)

# 不误吃 "Total entries displayed"
bad_total = [n for n in neighbors if "Total" in n.remote_name or "entries" in n.remote_name]
report("不误吃 'Total entries displayed'", len(bad_total) == 0)

# ============================================================
# Test 4: 空输入与异常输入
# ============================================================
print("\n" + "=" * 60)
print("Test 4: 边界条件")
print("=" * 60)

report("空字符串输入", len(mgr._parse_lldp_output("", "huawei")) == 0)
report("空字符串输入（cisco）", len(mgr._parse_lldp_output("", "cisco")) == 0)
report("只有表头无数据行",
       len(mgr._parse_lldp_output("Local Interface Neighbor Dev Neighbor Intf", "huawei")) == 0)
report("只有分隔线",
       len(mgr._parse_lldp_output("------ ------ ------", "huawei")) == 0)

# ============================================================
# Test 5: auto_discover_topology O(n²) 去重移除验证
# ============================================================
print("\n" + "=" * 60)
print("Test 5: auto_discover_topology 去重逻辑")
print("=" * 60)

import inspect
src = inspect.getsource(TopologyManager.auto_discover_topology)
report("移除内存 link_exists 循环", "link_exists" not in src,
       "仍包含 link_exists 变量")
report("使用 seen_pairs 集合", "seen_pairs" in src, "缺少 seen_pairs")

# ============================================================
# Test 6: 拖拽写库节流验证
# ============================================================
print("\n" + "=" * 60)
print("Test 6: 节点拖拽 _position_locked 标志")
print("=" * 60)

from ui.topology_widget import NodeGraphicsItem, create_node
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

asset = {"id": 999, "name": "Test", "ip": "1.1.1.1",
         "vendor": "cisco", "status": "online"}
node = create_node(asset, 100, 100)
report("_position_locked 默认 False", node._position_locked is False)
node._position_locked = True
report("_position_locked 可设 True", node._position_locked is True)

# ============================================================
# Test 7: 拖拽期间 itemChange 不写库
# ============================================================
print("\n" + "=" * 60)
print("Test 7: 拖拽期间跳过写库")
print("=" * 60)

from unittest.mock import patch, MagicMock
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QGraphicsScene

# 节点必须加入 scene，itemChange 才会触发（scene() is None 时直接返回）
scene = QGraphicsScene()
node2 = create_node(asset, 200, 200)
scene.addItem(node2)

node2._position_locked = True  # 模拟拖拽中
with patch('core.db.save_node_position') as mock_save:
    node2.setPos(QPointF(300, 300))
    report("拖拽中 setPos 不触发 db.save_node_position",
           mock_save.call_count == 0,
           f"实际调用 {mock_save.call_count} 次")

node2._position_locked = False
with patch('core.db.save_node_position') as mock_save:
    node2.setPos(QPointF(400, 400))
    report("非拖拽 setPos 触发 db.save_node_position",
           mock_save.call_count >= 1,
           f"实际调用 {mock_save.call_count} 次")

# ============================================================
# Test 8: 拓扑导入格式、统计与站点过滤
# ============================================================
print("\n" + "=" * 60)
print("Test 8: 拓扑导入格式、统计与站点过滤")
print("=" * 60)

import_data = {
    "edges": [
        {"source": 1, "target": 2},
        {"src": 2, "dst": 1},
        {"source": "Known", "target": 3},
        {"source": "Missing", "target": 4},
        {"src": 1, "dst": 5},
    ]
}

with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as f:
    json.dump(import_data, f)
    import_path = f.name

try:
    with patch.object(
        mgr,
        "_find_asset_by_name_or_ip",
        side_effect=lambda value: {"id": 4} if value == "Known" else None,
    ), patch(
        "core.topology.db.add_topology_link",
        side_effect=[(101, True), (101, False), (102, True)],
    ) as mock_add:
        success, message = mgr.import_topology(import_path, {1, 2, 3, 4})

    report("导入成功", success, message)
    report("兼容 source/target 与 src/dst", mock_add.call_count == 3,
           f"实际写库调用 {mock_add.call_count} 次")
    report("实际新增数量正确", "成功导入 2 条链路" in message, message)
    report("重复链路数量正确", "跳过 1 条重复链路" in message, message)
    report("无效链路数量正确", "跳过 1 条无效链路" in message, message)
    report("站点过滤数量正确", "跳过 1 条不在当前站点的链路" in message, message)
finally:
    os.unlink(import_path)

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 60)
print(f"RESULTS: {PASS} passed, {FAIL} failed")
print("=" * 60)

if ERRORS:
    print("\nFailed tests:")
    for name, msg in ERRORS:
        print(f"  - {name}: {msg}")

sys.exit(1 if FAIL else 0)
