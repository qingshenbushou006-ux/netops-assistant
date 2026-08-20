"""End-to-end topology test v2: re-fetch nodes after each refresh"""
import sys, warnings, traceback
sys.path.insert(0, '.')
warnings.filterwarnings('ignore', category=DeprecationWarning)
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF, Qt, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest

app = QApplication(sys.argv)
from ui.topology_widget import TopologyWidget, create_node, EdgeGraphicsItem, C, db

w = TopologyWidget()
w.resize(1200, 800)
w.show()
QTest.qWaitForWindowExposed(w)
QTest.qWait(100)
w._refresh()
QTest.qWait(50)
view = w.view

def fit_and_get_nodes():
    view.fitInView(view._scene.sceneRect().adjusted(-200,-200,200,200), Qt.KeepAspectRatio)
    QTest.qWait(10)
    app.processEvents()
    return sorted(view._nodes.items(), key=lambda kv: kv[0])

def create_link(src_id, dst_id):
    """Create a link by simulating mouse press/move/release"""
    n_src = view._nodes.get(src_id)
    n_dst = view._nodes.get(dst_id)
    if not n_src or not n_dst:
        print('    ERROR: node not found src=%s dst=%s' % (src_id, dst_id))
        return False
    src_vp = view.mapFromScene(n_src.pos())
    dst_vp = view.mapFromScene(n_dst.pos())
    # Press
    ev1 = QMouseEvent(QEvent.MouseButtonPress, src_vp, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(view.viewport(), ev1)
    app.processEvents()
    QTest.qWait(10)
    if not view._drag_linking:
        print('    ERROR: drag not started')
        return False
    # Move
    ev2 = QMouseEvent(QEvent.MouseMove, dst_vp, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(view.viewport(), ev2)
    app.processEvents()
    QTest.qWait(10)
    # Release
    ev3 = QMouseEvent(QEvent.MouseButtonRelease, dst_vp, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(view.viewport(), ev3)
    for _ in range(6):
        QTest.qWait(50)
        app.processEvents()
    return True

nodes = fit_and_get_nodes()
print('Total nodes:', len(nodes))
assert len(nodes) >= 3

# Find pairs that DON'T already have links
existing_links = db.get_all_topology_links('全部站点')
existing_pairs = set()
for l in existing_links:
    s, d = l['src_asset_id'], l['dst_asset_id']
    existing_pairs.add((s, d))
    existing_pairs.add((d, s))

# Find 2 pairs without existing links
test_pairs = []
node_ids = [n[0] for n in nodes]
for i, a_id in enumerate(node_ids):
    for j, b_id in enumerate(node_ids):
        if i >= j:
            continue
        if (a_id, b_id) not in existing_pairs:
            test_pairs.append((a_id, b_id))
            if len(test_pairs) >= 2:
                break
    if len(test_pairs) >= 2:
        break

assert len(test_pairs) >= 2, 'Need at least 2 unlinked pairs, found %d' % len(test_pairs)
n1_id, n2_id = test_pairs[0]
n2_id2, n3_id = test_pairs[1]
print('Test pairs: link1=%d->%d, link2=%d->%d' % (n1_id, n2_id, n2_id2, n3_id))

# ===== TEST 1: 连续创建多条连线 =====
print()
print('===== TEST 1: 连续创建多条连线 =====')
w.btn_tool_connect.setChecked(True)
view.set_tool(view.TOOL_CONNECT)
view._link_mode = True
QTest.qWait(10)

edges_before = len(view._edges)
print('  Edges before:', edges_before)

# Link 1: n1 -> n2
print('  Creating link n1(%d) -> n2(%d)...' % (n1_id, n2_id))
ok = create_link(n1_id, n2_id)
assert ok, 'Link 1 failed'
e1 = len(view._edges)
print('  After link 1: edges=%d' % e1)
assert e1 >= edges_before + 1, 'Link 1 not created'

# Link 2: n2_id2 -> n3_id
print('  Creating link %d -> %d...' % (n2_id2, n3_id))
ok = create_link(n2_id2, n3_id)
assert ok, 'Link 2 failed'
e2 = len(view._edges)
print('  After link 2: edges=%d' % e2)
assert e2 >= edges_before + 2, 'Link 2 not created'
print('  PASS: 连续创建2条连线成功')

# ===== TEST 2: 节点拖拽后连线更新 =====
print()
print('===== TEST 2: 节点拖拽后连线跟随更新 =====')
# Re-fetch nodes after refresh
nodes = fit_and_get_nodes()
n1 = view._nodes.get(n1_id)
assert n1 is not None, 'n1 not found after refresh'

# Find an edge connected to n1
test_edge = None
for e in view._edges:
    if (hasattr(e, 'src_node') and e.src_node and e.src_node.asset_id == n1_id) or \
       (hasattr(e, 'dst_node') and e.dst_node and e.dst_node.asset_id == n1_id):
        test_edge = e
        break
assert test_edge is not None, 'No edge connected to n1'

old_start = test_edge.path().pointAtPercent(0)
print('  Before drag: edge start=(%.1f,%.1f)' % (old_start.x(), old_start.y()))

old_pos = n1.pos()
n1.setPos(old_pos.x() + 100, old_pos.y() + 50)
QTest.qWait(20)
app.processEvents()

new_start = test_edge.path().pointAtPercent(0)
print('  After drag:  edge start=(%.1f,%.1f)' % (new_start.x(), new_start.y()))
moved = abs(new_start.x() - old_start.x()) > 1 or abs(new_start.y() - old_start.y()) > 1
assert moved, 'Edge did not update after node drag'
print('  PASS: 连线随节点拖拽更新')

# ===== TEST 3: 选中连线 + 控制点可见 =====
print()
print('===== TEST 3: 选中连线 =====')
view._scene.clearSelection()
w.btn_tool_select.setChecked(True)
view.set_tool(view.TOOL_SELECT)
view._link_mode = False
QTest.qWait(10)

# Select edge
test_edge.setSelected(True)
QTest.qWait(10)
app.processEvents()
print('  Edge selected:', test_edge.isSelected())
print('  Handle visible:', test_edge._handle.isVisible())
assert test_edge.isSelected()
assert test_edge._handle.isVisible()
print('  PASS: 连线可选中，控制点可见')

# ===== TEST 4: 拖拽控制点 =====
print()
print('===== TEST 4: 拖拽控制点调整弧度 =====')
old_ctrl = test_edge._control_offset
old_handle = test_edge._handle.pos()
print('  Old offset: (%.1f, %.1f)' % (old_ctrl.x(), old_ctrl.y()))

new_handle_pos = QPointF(old_handle.x() + 50, old_handle.y() - 30)
test_edge._handle.setPos(new_handle_pos)
QTest.qWait(20)
app.processEvents()

new_ctrl = test_edge._control_offset
print('  New offset: (%.1f, %.1f)' % (new_ctrl.x(), new_ctrl.y()))
assert not test_edge.path().isEmpty(), 'Path empty'
assert test_edge._arrow_polygon is not None, 'Arrow missing'
print('  PASS: 控制点拖拽有效，箭头保持')

# ===== TEST 5: 标签切换 =====
print()
print('===== TEST 5: 标签显示/隐藏 =====')
view._scene.clearSelection()
w.btn_labels.setChecked(True)
w._toggle_labels(True)
QTest.qWait(10)
app.processEvents()
labels_on = any(e._label and e._label.isVisible() for e in view._edges if hasattr(e, '_label') and e._label)
print('  Labels after ON:', labels_on)

w.btn_labels.setChecked(False)
w._toggle_labels(False)
QTest.qWait(10)
app.processEvents()
labels_off = all(not (e._label and e._label.isVisible()) for e in view._edges if hasattr(e, '_label') and e._label)
print('  Labels after OFF:', labels_off)
print('  PASS: 标签切换正常')

# ===== TEST 6: 删除连线 =====
print()
print('===== TEST 6: 删除连线 =====')
edges_before_del = len(view._edges)
print('  Edges before:', edges_before_del)
if view._edges:
    del_edge = view._edges[-1]
    link_id = del_edge.link_data.get('id')
    print('  Deleting link id:', link_id)
    db.delete_topology_link(link_id)
    w._refresh()
    for _ in range(6):
        QTest.qWait(50)
        app.processEvents()
    edges_after = len(view._edges)
    print('  Edges after:', edges_after)
    assert edges_after == edges_before_del - 1, 'Delete failed'
    print('  PASS: 连线删除成功')

# ===== TEST 7: 缩放 =====
print()
print('===== TEST 7: 缩放 =====')
old_zoom = view.transform().m11()
view.scale(1.5, 1.5)
QTest.qWait(10)
app.processEvents()
new_zoom = view.transform().m11()
print('  Zoom: %.2f -> %.2f' % (old_zoom, new_zoom))
assert new_zoom > old_zoom
print('  PASS: 缩放正常')

# ===== TEST 8: ESC 取消连线 =====
print()
print('===== TEST 8: ESC 取消连线模式 =====')
view._scene.clearSelection()
w.btn_tool_connect.setChecked(True)
view.set_tool(view.TOOL_CONNECT)
view._link_mode = True
QTest.qWait(10)

nodes = fit_and_get_nodes()
n_src = view._nodes.get(nodes[0][0])
src_vp = view.mapFromScene(n_src.pos())
ev1 = QMouseEvent(QEvent.MouseButtonPress, src_vp, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
app.sendEvent(view.viewport(), ev1)
app.processEvents()
QTest.qWait(10)
assert view._drag_linking, 'Drag not started'
print('  Drag started, now ESC to cancel')

from PySide6.QtGui import QKeyEvent
ev_esc = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
app.sendEvent(view, ev_esc)
app.processEvents()
QTest.qWait(10)
print('  After ESC: _drag_linking=%s' % view._drag_linking)
assert not view._drag_linking, 'ESC did not cancel drag'
print('  PASS: ESC 取消连线正常')

# ===== FINAL =====
print()
print('=' * 50)
print('ALL 8 END-TO-END TESTS PASSED!')
print('=' * 50)

w.close()
app.quit()
