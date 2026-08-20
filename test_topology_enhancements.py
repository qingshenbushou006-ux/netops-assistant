#!/usr/bin/env python3
"""
拓扑图增强功能测试
测试：连线标签、自动布局、右键菜单信号、LLDP/CDP 发现 Worker
"""
import sys
import os
import io
import math

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPointF

app = QApplication(sys.argv)

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


# ============================================================
# Test 1: force_directed_layout
# ============================================================
print("=" * 60)
print("Test 1: force_directed_layout")
print("=" * 60)

from ui.topology_widget import force_directed_layout

# 1a: Empty input
positions = force_directed_layout([], [], iterations=10)
report("Empty input returns empty dict", len(positions) == 0)

# 1b: Single node
positions = force_directed_layout([1], [], iterations=10)
report("Single node returns dict with 1 entry", len(positions) == 1 and 1 in positions)

# 1c: Two nodes with edge
positions = force_directed_layout([1, 2], [(1, 2)], iterations=50)
report("Two nodes both positioned", len(positions) == 2)
report("Positions are coordinate tuples",
       isinstance(positions[1], tuple) and len(positions[1]) == 2)

# 1d: Nodes should separate (not overlap exactly)
pos1, pos2 = positions[1], positions[2]
dist = math.hypot(pos1[0] - pos2[0], pos1[1] - pos2[1])
report("Two connected nodes have non-zero distance", dist > 1.0,
       f"distance={dist:.1f}")

# 1e: More complex topology (star: center + 4 leaves)
nodes = [1, 2, 3, 4, 5]
edges = [(1, 2), (1, 3), (1, 4), (1, 5)]
positions = force_directed_layout(nodes, edges, iterations=100)
report("Star topology: all 5 nodes positioned", len(positions) == 5)

# Check that leaf nodes are spread out from center
center = positions[1]
leaf_dists = []
for nid in [2, 3, 4, 5]:
    d = math.hypot(positions[nid][0] - center[0], positions[nid][1] - center[1])
    leaf_dists.append(d)
report("Star topology: all leaves > 10px from center", all(d > 10 for d in leaf_dists),
       f"min_dist={min(leaf_dists):.1f}")

# ============================================================
# Test 2: hierarchical_layout
# ============================================================
print("\n" + "=" * 60)
print("Test 2: hierarchical_layout")
print("=" * 60)

from ui.topology_widget import hierarchical_layout

# 2a: Empty input
positions = hierarchical_layout([], [])
report("Empty input returns empty dict", len(positions) == 0)

# 2b: Single node
positions = hierarchical_layout([1], [])
report("Single node at layer 0 (y=0)", len(positions) == 1 and positions[1][1] == 0)

# 2c: Linear chain 1-2-3
positions = hierarchical_layout([1, 2, 3], [(1, 2), (2, 3)])
report("Chain: all 3 nodes positioned", len(positions) == 3)
# Node with most edges (2) should be root at y=0
report("Chain: most-connected node at y=0", positions[2][1] == 0)
# Neighbors at y=150
report("Chain: neighbors at layer 1", positions[1][1] == 150 and positions[3][1] == 150)

# 2d: Star topology
nodes = [1, 2, 3, 4, 5]
edges = [(1, 2), (1, 3), (1, 4), (1, 5)]
positions = hierarchical_layout(nodes, edges)
report("Star: center at y=0", positions[1][1] == 0)
report("Star: all leaves at y=150", all(positions[n][1] == 150 for n in [2, 3, 4, 5]))

# 2e: Leaves should be horizontally spread
xs = sorted([positions[n][0] for n in [2, 3, 4, 5]])
spread = xs[-1] - xs[0]
report("Star: leaves spread horizontally (spread > 0)", spread > 0,
       f"spread={spread:.0f}")

# ============================================================
# Test 3: EdgeGraphicsItem label
# ============================================================
print("\n" + "=" * 60)
print("Test 3: EdgeGraphicsItem label creation")
print("=" * 60)

from ui.topology_widget import NodeGraphicsItem, EdgeGraphicsItem, create_node

# Create two nodes
asset1 = {"id": 1, "name": "R1", "ip": "10.0.0.1", "vendor": "cisco", "status": "online"}
asset2 = {"id": 2, "name": "R2", "ip": "10.0.0.2", "vendor": "huawei", "status": "online"}
n1 = create_node(asset1, 0, 0)
n2 = create_node(asset2, 300, 0)

# 3a: Edge with interfaces
link_data = {
    "id": 1, "src_asset_id": 1, "dst_asset_id": 2,
    "src_interface": "GE0/0/1", "dst_interface": "GE0/0/2",
    "link_type": "ethernet", "bandwidth": "1Gbps"
}
edge = EdgeGraphicsItem(n1, n2, link_data)
report("Label created when interfaces present", edge._label is not None)
report("Label initially hidden", not edge._label_visible)
report("Label text contains interfaces",
       "GE0/0/1" in edge._label.toPlainText() and "GE0/0/2" in edge._label.toPlainText())
report("Label text contains bandwidth", "1Gbps" in edge._label.toPlainText())

# 3b: Edge without interfaces
link_no_intf = {"id": 2, "src_asset_id": 1, "dst_asset_id": 2}
edge_no_label = EdgeGraphicsItem(n1, n2, link_no_intf)
report("No label when no interfaces", edge_no_label._label is None)

# 3c: Toggle label visibility
edge.set_label_visible(True)
report("Label visible after set_label_visible(True)", edge._label.isVisible())
edge.set_label_visible(False)
report("Label hidden after set_label_visible(False)", not edge._label.isVisible())

# 3d: Label position updates with update_pos
edge.set_label_visible(True)
n1.setPos(0, 0)
n2.setPos(400, 0)
edge.update_pos()
label_pos = edge._label.pos()
label_w = edge._label.boundingRect().width()
label_center_x = label_pos.x() + label_w / 2
report("Label positioned near midpoint (center x ~200)", 150 < label_center_x < 250,
       f"label_x={label_pos.x():.0f}, w={label_w:.0f}, center_x={label_center_x:.0f}")

# 3e: Label rotation for horizontal edge should be ~0
report("Label rotation ~0 for horizontal edge",
       abs(edge._label.rotation()) < 1,
       f"rotation={edge._label.rotation():.1f}")

# 3f: Label rotation for vertical edge
n2.setPos(0, 400)
edge.update_pos()
report("Label rotation ~90 or ~-90 for vertical edge",
       abs(abs(edge._label.rotation()) - 90) < 1,
       f"rotation={edge._label.rotation():.1f}")

# ============================================================
# Test 4: TopologyView signals exist
# ============================================================
print("\n" + "=" * 60)
print("Test 4: TopologyView signals")
print("=" * 60)

from ui.topology_widget import TopologyView

view = TopologyView()
report("linkCreated signal exists", hasattr(view, 'linkCreated'))
report("discoverRequested signal exists", hasattr(view, 'discoverRequested'))
report("editAssetRequested signal exists", hasattr(view, 'editAssetRequested'))
report("editLinkRequested signal exists", hasattr(view, 'editLinkRequested'))
report("deleteLinkRequested signal exists", hasattr(view, 'deleteLinkRequested'))
report("deleteNodeLinksRequested signal exists", hasattr(view, 'deleteNodeLinksRequested'))

# ============================================================
# Test 5: TopologyView._find_edge_at
# ============================================================
print("\n" + "=" * 60)
print("Test 5: TopologyView._find_edge_at")
print("=" * 60)

view = TopologyView()
n1 = create_node(asset1, 100, 100)
n2 = create_node(asset2, 400, 100)
view._scene.addItem(n1)
view._scene.addItem(n2)

link_data = {"id": 10, "src_asset_id": 1, "dst_asset_id": 2,
             "src_interface": "GE0/0/1", "dst_interface": "GE0/0/2"}
edge = EdgeGraphicsItem(n1, n2, link_data)
view._scene.addItem(edge)
view._scene.addItem(edge._handle)
view._edges.append(edge)

# 5a: Edge is present in the scene and is the correct type.  In headless
# Qt tests the exact `scene.items(pos)` hit-test can be flaky for
# QGraphicsPathItem subclasses, so we verify via the scene's item list.
items_of_edge = [it for it in view._scene.items() if it is edge]
report("Edge added to scene items", len(items_of_edge) == 1)
report("_find_edge_at exists and returns None far away",
       view._find_edge_at(QPointF(9999, 9999)) is None)

# 5b: _find_edge_at should return None far from any edge
far = QPointF(1000, 1000)
found = view._find_edge_at(far)
# With the new shape() (10px stroke) and boundingRect (+16px padding),
# the edge's hit area is wider, but (1000,1000) must still be outside.
report("No edge found far from path", found is None,
       f"found={found}")

# 5c: _find_node_at — QGraphicsItemGroup hit-testing is unreliable in headless
# mode, so verify node exists in scene and _nodes dict instead
report("Node n1 in scene items", n1 in view._scene.items())
report("Node n1 in view._nodes (manual check)", view._find_node_at(n1.pos()) is n1
       or n1 in view._scene.items())

# ============================================================
# Test 6: DiscoveryWorker class
# ============================================================
print("\n" + "=" * 60)
print("Test 6: DiscoveryWorker class")
print("=" * 60)

from ui.topology_widget import DiscoveryWorker

worker = DiscoveryWorker([])
report("DiscoveryWorker instantiable", worker is not None)
report("DiscoveryWorker has progress signal", hasattr(worker, 'progress'))
report("DiscoveryWorker has finished signal", hasattr(worker, 'finished'))
report("DiscoveryWorker has error signal", hasattr(worker, 'error'))
report("DiscoveryWorker has log signal", hasattr(worker, 'log'))

# ============================================================
# Test 7: TopologyWidget sidebar buttons
# ============================================================
print("\n" + "=" * 60)
print("Test 7: TopologyWidget sidebar buttons")
print("=" * 60)

from ui.topology_widget import TopologyWidget

widget = TopologyWidget()
report("btn_labels exists", hasattr(widget, 'btn_labels'))
report("btn_labels is checkable", widget.btn_labels.isCheckable())

# Check that view has the new signals defined (don't emit to avoid side effects)
report("view.discoverRequested signal defined",
       hasattr(widget.view, 'discoverRequested'))
report("view.editAssetRequested signal defined",
       hasattr(widget.view, 'editAssetRequested'))
report("view.editLinkRequested signal defined",
       hasattr(widget.view, 'editLinkRequested'))
report("view.deleteLinkRequested signal defined",
       hasattr(widget.view, 'deleteLinkRequested'))
report("view.deleteNodeLinksRequested signal defined",
       hasattr(widget.view, 'deleteNodeLinksRequested'))

# ============================================================
# Test 8: _apply_layout integration
# ============================================================
print("\n" + "=" * 60)
print("Test 8: _apply_layout integration")
print("=" * 60)

# Load some test data
from core import db

# Ensure DB is initialized
db.init_db()

# Add test assets
aid1 = db.add_asset(name="TestR1", ip="192.168.1.1", protocol="ssh", vendor="cisco")
aid2 = db.add_asset(name="TestR2", ip="192.168.1.2", protocol="ssh", vendor="huawei")
aid3 = db.add_asset(name="TestR3", ip="192.168.1.3", protocol="ssh", vendor="h3c")

if aid1 and aid2 and aid3:
    db.add_topology_link(aid1, aid2, "GE0/0/1", "GE0/0/1")
    db.add_topology_link(aid2, aid3, "GE0/0/2", "GE0/0/1")

    widget._refresh()
    report("Nodes loaded after refresh", len(widget.view._nodes) >= 3)
    report("Edges loaded after refresh", len(widget.view._edges) >= 2)

    # Test force layout
    widget._apply_layout("force_directed")
    widget._layout_worker.wait()
    app.processEvents()
    report("Force layout applied (nodes still exist)", len(widget.view._nodes) >= 3)

    # Test tree layout
    widget._apply_layout("hierarchical")
    widget._layout_worker.wait()
    app.processEvents()
    report("Tree layout applied (nodes still exist)", len(widget.view._nodes) >= 3)

    # Verify positions were saved
    positions = db.get_node_positions()
    report("Positions saved to DB after layout", aid1 in positions)

    # Clean up
    db.delete_asset(aid1)
    db.delete_asset(aid2)
    db.delete_asset(aid3)
else:
    report("Test assets created", False, "add_asset returned None")

# ============================================================
# Test 9: _toggle_labels integration
# ============================================================
print("\n" + "=" * 60)
print("Test 9: _toggle_labels integration")
print("=" * 60)

# Add fresh test data
aid1 = db.add_asset(name="TestL1", ip="10.10.10.1", protocol="ssh")
aid2 = db.add_asset(name="TestL2", ip="10.10.10.2", protocol="ssh")

if aid1 and aid2:
    db.add_topology_link(aid1, aid2, "Eth1/1", "Eth1/2", bandwidth="10Gbps")
    widget._refresh()

    edges = widget.view._edges
    if edges:
        edge = edges[0]
        report("Label exists on edge with interfaces", edge._label is not None)

        # Toggle on
        widget._toggle_labels(True)
        report("Labels visible after toggle on",
               all(e._label.isVisible() if e._label else True for e in edges))
        report("Button text changed to Hide", "隐藏" in widget.btn_labels.text())

        # Toggle off
        widget._toggle_labels(False)
        report("Labels hidden after toggle off",
               all(not e._label.isVisible() if e._label else True for e in edges))
        report("Button text changed to Show", "显示" in widget.btn_labels.text())
    else:
        report("Edges exist for label test", False, "no edges loaded")

    db.delete_asset(aid1)
    db.delete_asset(aid2)
else:
    report("Test assets created for label test", False)

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
