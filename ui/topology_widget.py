"""
Topology Widget - Optimized UI with uninstall feature
"""
import math
import json
import os
import shutil
import threading
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGraphicsScene, QGraphicsView, QGraphicsEllipseItem,
    QGraphicsLineItem, QGraphicsPathItem, QGraphicsTextItem,
    QGraphicsItemGroup, QGraphicsItem, QFileDialog, QInputDialog,
    QMessageBox, QFrame, QComboBox, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox, QMenu, QProgressDialog
)
from PySide6.QtCore import Qt, QPointF, Signal, QSize, QThread, QRectF, QTimer
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QRadialGradient,
    QIcon, QPixmap, QPainterPath, QPainterPathStroker, QCursor, QKeySequence, QShortcut,
    QPolygonF
)


# Catppuccin Mocha Theme Colors
C = {
    "bg": "#1e1e2e",
    "bg2": "#181825",
    "bg3": "#313244",
    "surface": "#45475a",
    "overlay": "#585b70",
    "text": "#cdd6f4",
    "text2": "#a6adc8",
    "text3": "#585b70",
    "blue": "#89b4fa",
    "lavender": "#b4befe",
    "sapphire": "#74c7ec",
    "green": "#a6e3a1",
    "yellow": "#f9e2af",
    "peach": "#fab387",
    "red": "#f38ba8",
    "mauve": "#cba6f7",
    "pink": "#f5c2e7",
}


class NodeGraphicsItem(QGraphicsItemGroup):
    """Stylish network node"""

    def __init__(self, asset_id, name, ip, vendor, status, x, y, group_name=""):
        super().__init__()
        self.asset_id = asset_id
        self._display_name = name
        self._ip = ip
        self.group_name = group_name  # 用于分组折叠
        self._connected_edges = []
        self._destroyed = False
        self._position_locked = False  # 拖拽中置 True，暂停 itemChange 写库
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)

        self._hovered = False
        self._r = 28

        # Status color
        if status == "online":
            self._color = QColor(C["green"])
        elif status == "offline":
            self._color = QColor(C["red"])
        else:
            self._color = QColor(C["blue"])

        # Vendor icon mapping
        vendor_icons = {
            "huawei": "H", "cisco": "C", "h3c": "H",
            "linux": "L", "juniper": "J"
        }
        self._icon = vendor_icons.get(vendor.lower()[:3] if vendor else "", "S")

        # IMPORTANT: build child items BEFORE setPos, so addToGroup maps
        # child pos(0,0) to group-local coords instead of reverse-offset.
        self._create_graphics()
        self.setPos(x, y)
    
    def _create_graphics(self):
        # Shadow
        shadow = QGraphicsEllipseItem(-self._r+3, -self._r+3, self._r*2, self._r*2)
        shadow.setBrush(QBrush(QColor(0, 0, 0, 40)))
        shadow.setPen(Qt.NoPen)
        self.addToGroup(shadow)
        
        # Main circle
        self._circle = QGraphicsEllipseItem(-self._r, -self._r, self._r*2, self._r*2)
        self._update_style()
        self.addToGroup(self._circle)
        
        # Vendor icon text
        icon = QGraphicsTextItem(self._icon)
        icon.setDefaultTextColor(QColor(C["bg"]))
        icon.setFont(QFont("Arial", 14, QFont.Bold))
        ir = icon.boundingRect()
        icon.setPos(-ir.width()/2, -ir.height()/2-2)
        self.addToGroup(icon)
        
        # Name label
        name = QGraphicsTextItem(self._name_short())
        name.setDefaultTextColor(QColor(C["text"]))
        name.setFont(QFont("Segoe UI", 9, QFont.Bold))
        nr = name.boundingRect()
        name.setPos(-nr.width()/2, self._r+5)
        self.addToGroup(name)
        
        # IP label
        ip = QGraphicsTextItem(self._ip if hasattr(self, '_ip') else "")
        ip.setDefaultTextColor(QColor(C["text2"]))
        ip.setFont(QFont("Consolas", 8))
        ir2 = ip.boundingRect()
        ip.setPos(-ir2.width()/2, self._r+22)
        self.addToGroup(ip)
    
    def _name_short(self):
        # This will be set in __init__ via asset_data
        return getattr(self, '_display_name', 'Node')
    
    def _update_style(self):
        if self._hovered:
            color = self._color.lighter(120)
            border = self._color.lighter(140)
        else:
            color = self._color
            border = self._color.darker(120)
        
        gradient = QRadialGradient(0, -5, self._r)
        gradient.setColorAt(0, color.lighter(105))
        gradient.setColorAt(1, color)
        self._circle.setBrush(QBrush(gradient))
        self._circle.setPen(QPen(border, 2))
    
    def hoverEnterEvent(self, event):
        self._hovered = True
        self._update_style()
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        self._hovered = False
        self._update_style()
        super().hoverLeaveEvent(event)

    def add_edge(self, edge):
        self._connected_edges.append(edge)

    def remove_edge(self, edge):
        if edge in self._connected_edges:
            self._connected_edges.remove(edge)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            if getattr(self, '_destroyed', False):
                return super().itemChange(change, value)
            if self.scene() is None:
                return super().itemChange(change, value)
            for edge in list(self._connected_edges):
                try:
                    if edge.scene() is not None and getattr(edge, 'src_node', None) is not None and getattr(edge, 'dst_node', None) is not None:
                        edge.update_pos()
                except (RuntimeError, ReferenceError, Exception):
                    pass
            if not getattr(self, '_position_locked', False):
                try:
                    db.save_node_position(self.asset_id, self.pos().x(), self.pos().y())
                except Exception:
                    pass
        return super().itemChange(change, value)


def create_node(asset, x, y):
    """Factory function to create a node"""
    node = NodeGraphicsItem(
        asset["id"], asset["name"], asset["ip"],
        asset.get("vendor", ""), asset.get("status", "unknown"),
        x, y, group_name=asset.get("group_name") or asset.get("location") or "默认"
    )
    return node


def force_directed_layout(nodes, edges, iterations=100):
    """Force-directed layout: Coulomb repulsion + Hooke spring attraction.

    纯 float 计算（{nid: (x, y)}），可在后台线程安全执行，UI 线程再转 QPointF。
    """
    import random
    positions = {nid: (random.uniform(-200, 200), random.uniform(-200, 200)) for nid in nodes}
    velocities = {nid: [0.0, 0.0] for nid in nodes}

    k_repulse = 5000.0
    k_attract = 0.005
    rest_length = 150.0
    k_gravity = 0.01
    damping = 0.85

    edge_pairs = [(s, d) for s, d in edges if s in positions and d in positions]

    for _ in range(iterations):
        forces = {nid: [0.0, 0.0] for nid in positions}

        # Coulomb repulsion between all pairs
        nids = list(positions.keys())
        for i in range(len(nids)):
            for j in range(i + 1, len(nids)):
                a, b = nids[i], nids[j]
                ax, ay = positions[a]
                bx, by = positions[b]
                dx = ax - bx
                dy = ay - by
                dist = max(math.hypot(dx, dy), 1.0)
                f = k_repulse / (dist * dist * dist)
                forces[a][0] += f * dx
                forces[a][1] += f * dy
                forces[b][0] -= f * dx
                forces[b][1] -= f * dy

        # Hooke spring attraction along edges
        for s, d in edge_pairs:
            sx, sy = positions[s]
            dx = positions[d][0] - sx
            dy = positions[d][1] - sy
            dist = max(math.hypot(dx, dy), 1.0)
            f = k_attract * (dist - rest_length) / dist
            forces[s][0] += f * dx
            forces[s][1] += f * dy
            forces[d][0] -= f * dx
            forces[d][1] -= f * dy

        # Weak gravity toward origin
        for nid in positions:
            forces[nid][0] -= k_gravity * positions[nid][0]
            forces[nid][1] -= k_gravity * positions[nid][1]

        # Update velocities and positions
        for nid in positions:
            vx = (velocities[nid][0] + forces[nid][0]) * damping
            vy = (velocities[nid][1] + forces[nid][1]) * damping
            velocities[nid][0] = vx
            velocities[nid][1] = vy
            positions[nid] = (positions[nid][0] + vx, positions[nid][1] + vy)

    return positions


def hierarchical_layout(nodes, edges):
    """Hierarchical/tree layout via BFS from the most-connected node."""
    if not nodes:
        return {}

    # Build adjacency
    adj = {nid: set() for nid in nodes}
    for s, d in edges:
        if s in adj and d in adj:
            adj[s].add(d)
            adj[d].add(s)

    # BFS from node with most edges
    root = max(nodes, key=lambda n: len(adj[n]))
    layers = {}
    visited = {root}
    queue = [root]
    layers[root] = 0
    while queue:
        next_queue = []
        for node in queue:
            for neighbor in adj[node]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    layers[neighbor] = layers[node] + 1
                    next_queue.append(neighbor)
        queue = next_queue

    # Unvisited nodes get layer 0
    for nid in nodes:
        if nid not in layers:
            layers[nid] = 0

    # Group by layer
    by_layer = {}
    for nid, layer in layers.items():
        by_layer.setdefault(layer, []).append(nid)

    # Position
    node_spacing = 200
    layer_spacing = 150
    positions = {}
    for layer, nids in by_layer.items():
        total_width = (len(nids) - 1) * node_spacing
        for i, nid in enumerate(nids):
            x = i * node_spacing - total_width / 2
            y = layer * layer_spacing
            positions[nid] = (x, y)

    return positions


class DiscoveryWorker(QThread):
    """Background thread for LLDP/CDP topology discovery"""
    progress = Signal(int, int, str)
    log = Signal(str)
    finished = Signal(list)
    error = Signal(str)
    canceled = Signal()

    def __init__(self, assets, parent=None):
        super().__init__(parent)
        self.assets = assets
        self._cancel_event = threading.Event()

    def cancel(self):
        """协作式取消：置位事件，等待 run() 自然退出"""
        self._cancel_event.set()

    def run(self):
        try:
            from core.topology import TopologyManager
            mgr = TopologyManager()
            mgr.set_callbacks(
                progress_cb=lambda c, t, m: self.progress.emit(c, t, m),
                log_cb=lambda m: self.log.emit(m),
            )
            links = mgr.auto_discover_topology(
                self.assets, cancel_event=self._cancel_event
            )
            if self._cancel_event.is_set():
                self.canceled.emit()
            else:
                self.finished.emit(links)
        except Exception as e:
            self.error.emit(str(e))


class LayoutWorker(QThread):
    """后台线程计算布局，避免大拓扑阻塞 UI"""
    done = Signal(object)  # {nid: (x, y)}
    error = Signal(str)

    def __init__(self, algorithm, node_ids, edge_pairs, parent=None):
        super().__init__(parent)
        self.algorithm = algorithm
        self.node_ids = node_ids
        self.edge_pairs = edge_pairs

    def run(self):
        try:
            if self.algorithm == "force_directed":
                positions = force_directed_layout(self.node_ids, self.edge_pairs, iterations=100)
            else:
                positions = hierarchical_layout(self.node_ids, self.edge_pairs)
            self.done.emit(positions)
        except Exception as e:
            self.error.emit(str(e))


class ControlHandleItem(QGraphicsEllipseItem):
    """Draggable control point for adjusting edge curves"""

    def __init__(self, edge):
        r = 6
        super().__init__(-r, -r, r * 2, r * 2)
        self.edge = edge
        self.setBrush(QBrush(QColor(C["peach"])))
        self.setPen(QPen(QColor(C["peach"]).darker(140), 1.5))
        self.setZValue(5)
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setCursor(Qt.PointingHandCursor)
        self.setVisible(False)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            if getattr(self, 'edge', None) is None or self.scene() is None:
                return super().itemChange(change, value)
            if self.edge.scene() is None:
                return super().itemChange(change, value)
            if not getattr(self.edge, '_updating_handle', False):
                try:
                    self.edge._on_handle_moved(self.pos())
                except (RuntimeError, ReferenceError, Exception):
                    pass
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.edge._save_control_point()


class EdgeGraphicsItem(QGraphicsPathItem):
    """Network edge with arrow, endpoint offset and Bezier curve control."""

    ARROW_SIZE = 12
    NODE_RADIUS = 28

    def __init__(self, src_node, dst_node, link_data=None, control_offset=None):
        super().__init__()
        self.src_node = src_node
        self.dst_node = dst_node
        self.link_data = link_data or {}
        self.link_type = self.link_data.get("link_type", "ethernet")
        self._control_offset = (
            QPointF(*control_offset)
            if control_offset
            else QPointF(0, 0)
        )
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setZValue(-1)
        self._hovered = False
        self._arrow_color = QColor(C["text3"])
        self._arrow_polygon = None
        self._updating_handle = False
        self._handle = ControlHandleItem(self)
        self._label = None
        self._label_visible = False
        self._create_label()
        self._update_pen()
        self.update_pos()
        src_node.add_edge(self)
        dst_node.add_edge(self)

    def _update_pen(self):
        if self.isSelected():
            color = QColor(C["yellow"])
            width = 3.5
        elif self._hovered:
            color = QColor(C["lavender"])
            width = 3
        else:
            color = QColor(C["text3"])
            width = 2
        pen = QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        self.setPen(pen)
        self._arrow_color = color

    def _create_label(self):
        src_intf = self.link_data.get("src_interface", "")
        dst_intf = self.link_data.get("dst_interface", "")
        bw = self.link_data.get("bandwidth", "")
        if not src_intf and not dst_intf:
            return
        text = f"{src_intf} ↔ {dst_intf}"
        if bw:
            text += f"  ({bw})"
        self._label = QGraphicsTextItem(text, self)
        self._label.setDefaultTextColor(QColor(C["text2"]))
        self._label.setFont(QFont("Consolas", 7))
        self._label.setVisible(self._label_visible)
        self._label.setZValue(2)

    def set_label_visible(self, visible):
        self._label_visible = visible
        if self._label:
            self._label.setVisible(visible)
            if visible:
                self._position_label()

    @classmethod
    def _node_radius(cls, node):
        return getattr(node, "_r", cls.NODE_RADIUS)

    def _compute_curve_path(self, src_pos, dst_pos):
        src_r = self._node_radius(self.src_node)
        dst_r = self._node_radius(self.dst_node)
        dx = dst_pos.x() - src_pos.x()
        dy = dst_pos.y() - src_pos.y()
        dist = math.hypot(dx, dy)

        if dist < 1:
            p = QPainterPath()
            p.moveTo(src_pos)
            p.lineTo(dst_pos)
            return p

        ux, uy = dx / dist, dy / dist
        shrink_src = src_r + 2
        shrink_dst = dst_r + self.ARROW_SIZE + 2
        total_shrink = shrink_src + shrink_dst

        if dist < total_shrink:
            min_gap = 4.0
            ratio = (dist - min_gap) / total_shrink
            ratio = max(0.0, min(1.0, ratio))
            s = QPointF(src_pos.x() + ux * shrink_src * ratio,
                        src_pos.y() + uy * shrink_src * ratio)
            e = QPointF(dst_pos.x() - ux * shrink_dst * ratio,
                        dst_pos.y() - uy * shrink_dst * ratio)
            p = QPainterPath()
            p.moveTo(s)
            p.lineTo(e)
            return p

        s = QPointF(src_pos.x() + ux * shrink_src,
                    src_pos.y() + uy * shrink_src)
        e = QPointF(dst_pos.x() - ux * shrink_dst,
                    dst_pos.y() - uy * shrink_dst)

        mid = QPointF((s.x() + e.x()) / 2, (s.y() + e.y()) / 2)

        if self._control_offset != QPointF(0, 0):
            ctrl = mid + self._control_offset
        else:
            n_x, n_y = -uy, ux
            curvature = min(90.0, max(18.0, dist * 0.25))
            ctrl = QPointF(mid.x() + n_x * curvature * 0.6,
                           mid.y() + n_y * curvature * 0.6)

        path = QPainterPath()
        path.moveTo(s)
        path.quadTo(ctrl, e)
        return path

    def _compute_arrow_polygon(self, path):
        if path.length() < 1:
            return None
        back = min(8.0, max(1.0, path.length() * 0.15))
        percent = max(0.0, path.percentAtLength(max(0.0, path.length() - back)))
        pt_before = path.pointAtPercent(percent)
        pt_end = path.pointAtPercent(1.0)
        # Direction vector of the path at the endpoint
        dx = pt_end.x() - pt_before.x()
        dy = pt_end.y() - pt_before.y()
        angle = math.atan2(dy, dx)
        size = float(self.ARROW_SIZE)
        half = math.pi * 0.85
        # Tip of the arrow
        tip = pt_end
        # Base center is 'size' distance behind the tip along the path direction
        base_center = QPointF(
            tip.x() - size * math.cos(angle),
            tip.y() - size * math.sin(angle)
        )
        # Normal vector (perpendicular to path direction)
        nx = -math.sin(angle)
        ny = math.cos(angle)
        # Offset from base_center to the two base corners
        offset = size * math.sin(half)
        p1 = tip
        p2 = QPointF(base_center.x() + nx * offset,
                     base_center.y() + ny * offset)
        p3 = QPointF(base_center.x() - nx * offset,
                     base_center.y() - ny * offset)
        poly = QPolygonF()
        poly.append(p1)
        poly.append(p2)
        poly.append(p3)
        return poly

    def update_pos(self):
        try:
            if self.src_node is None or self.dst_node is None:
                return
            if self.scene() is None and getattr(self._handle, 'scene', lambda: None)() is None:
                pass
        except (RuntimeError, ReferenceError, Exception):
            return
        try:
            src = self.src_node.pos()
            dst = self.dst_node.pos()
            path = self._compute_curve_path(src, dst)
            self.setPath(path)
            self._arrow_polygon = self._compute_arrow_polygon(path)
            self._updating_handle = True
            try:
                if self._handle.scene() is not None:
                    ctrl_found = False
                    for i in range(path.elementCount()):
                        el = path.elementAt(i)
                        if el.type == QPainterPath.ElementType.CurveToElement:
                            self._handle.setPos(el.x, el.y)
                            ctrl_found = True
                            break
                    if not ctrl_found:
                        mid = path.pointAtPercent(0.5)
                        self._handle.setPos(mid)
            except (RuntimeError, IndexError, ReferenceError, Exception):
                pass
            finally:
                self._updating_handle = False
            if self._label and self._label_visible:
                try:
                    self._position_label()
                except (RuntimeError, IndexError, ReferenceError, Exception):
                    pass
        except (RuntimeError, ReferenceError, Exception):
            try:
                self._updating_handle = False
            except Exception:
                pass

    def _position_label(self):
        src = self.src_node.pos()
        dst = self.dst_node.pos()
        mid = QPointF((src.x() + dst.x()) / 2, (src.y() + dst.y()) / 2)
        ctrl = mid + self._control_offset
        t = 0.5
        lx = (1 - t) ** 2 * src.x() + 2 * (1 - t) * t * ctrl.x() + t ** 2 * dst.x()
        ly = (1 - t) ** 2 * src.y() + 2 * (1 - t) * t * ctrl.y() + t ** 2 * dst.y()
        dx = dst.x() - src.x()
        dy = dst.y() - src.y()
        angle = math.degrees(math.atan2(dy, dx))
        if angle > 90:
            angle -= 180
        elif angle < -90:
            angle += 180
        br = self._label.boundingRect()
        self._label.setPos(lx - br.width() / 2, ly - br.height() / 2)
        self._label.setRotation(-angle)

    def _on_handle_moved(self, new_pos):
        s = self.src_node.pos()
        e = self.dst_node.pos()
        mid = QPointF((s.x() + e.x()) / 2, (s.y() + e.y()) / 2)
        self._control_offset = new_pos - mid
        self.update_pos()

    def _save_control_point(self):
        link_id = self.link_data.get("id")
        if link_id is not None:
            db.save_edge_control_point(
                link_id, self._control_offset.x(), self._control_offset.y()
            )

    def _set_handle_visible(self, visible):
        self._handle.setVisible(visible)

    def hoverEnterEvent(self, event):
        self._hovered = True
        try:
            self._update_pen()
            self._set_handle_visible(True)
            self.update()
        except (RuntimeError, ReferenceError, Exception):
            pass
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered = False
        try:
            self._update_pen()
            if not self.isSelected():
                self._set_handle_visible(False)
            self.update()
        except (RuntimeError, ReferenceError, Exception):
            pass
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedChange:
            try:
                self._update_pen()
                self._set_handle_visible(bool(value))
                self.update()
            except (RuntimeError, ReferenceError, Exception):
                pass
        return super().itemChange(change, value)

    def shape(self):
        p = QPainterPathStroker()
        p.setWidth(10)
        return p.createStroke(self.path())

    def boundingRect(self):
        return self.path().boundingRect().adjusted(-16, -16, 16, 16)

    def paint(self, painter, option, widget):
        if self.isSelected() or self._hovered:
            halo_color = QColor(C["yellow"] if self.isSelected() else C["lavender"])
            halo_pen = QPen(halo_color, self.pen().width() + 6, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(halo_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self.path())

        painter.setPen(self.pen())
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path())

        if self._arrow_polygon:
            painter.setBrush(QBrush(self._arrow_color))
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(self._arrow_polygon)


class TopologyView(QGraphicsView):
    """Topology graphics view with Visio-like interactions"""

    linkCreated = Signal(int, int)
    discoverRequested = Signal(int)
    editAssetRequested = Signal(int)
    editLinkRequested = Signal(dict)
    deleteLinkRequested = Signal(dict)
    deleteNodeLinksRequested = Signal(int)
    connectRequested = Signal(int)

    COLLAPSE_THRESHOLD = 200
    GRID_SIZE = 20

    TOOL_SELECT = 0
    TOOL_CONNECT = 1
    TOOL_PAN = 2

    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene()
        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor(C["bg"])))
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setCacheMode(QGraphicsView.CacheBackground)
        self._scene.setItemIndexMethod(QGraphicsScene.BspTreeIndex)

        self._nodes = {}
        self._edges = []
        self._collapsed_groups = set()

        self._tool = self.TOOL_SELECT
        self._panning = False
        self._pan_start = QPointF()
        # 连线模式：拖拽创建连线（eNSP 风格）
        self._link_mode = False          # 是否处于连线工具模式
        self._drag_linking = False       # 正在拖拽连线
        self._drag_link_src = None      # 拖拽连线起点节点
        self._drag_link_line = None     # 预览虚线 item
        self._hover_node = None          # 当前悬停的目标节点
        self._drag_nodes = []
        self._drag_offsets = {}
        self._marquee_start = None
        self._marquee_rect_item = None
        self._snap_to_grid = True
        self._show_grid = True

        self._install_shortcuts()
        self._rebuild_grid_pen()

    def _install_shortcuts(self):
        from PySide6.QtGui import QShortcut
        QShortcut(QKeySequence("Escape"), self, activated=self._escape_handler)
        QShortcut(QKeySequence("F2"), self, activated=lambda: self._set_tool_and_sync(self.TOOL_SELECT))
        QShortcut(QKeySequence("F3"), self, activated=lambda: self._set_tool_and_sync(self.TOOL_CONNECT))
        QShortcut(QKeySequence("F4"), self, activated=lambda: self._set_tool_and_sync(self.TOOL_PAN))
        QShortcut(QKeySequence("Delete"), self, activated=self._delete_selection)
        QShortcut(QKeySequence("Ctrl+A"), self, activated=self._select_all)
        QShortcut(QKeySequence("Ctrl+Shift+A"), self, activated=self._clear_selection)
        QShortcut(QKeySequence("Ctrl+1"), self, activated=self.fit_to_view)
        QShortcut(QKeySequence("Ctrl+H"), self, activated=self.toggle_grid)
        QShortcut(QKeySequence("Ctrl+G"), self, activated=self.toggle_snap)
        QShortcut(QKeySequence("Alt+Left"), self, activated=lambda: self.align("left"))
        QShortcut(QKeySequence("Alt+Right"), self, activated=lambda: self.align("right"))
        QShortcut(QKeySequence("Alt+Top"), self, activated=lambda: self.align("top"))
        QShortcut(QKeySequence("Alt+Bottom"), self, activated=lambda: self.align("bottom"))
        QShortcut(QKeySequence("Alt+H"), self, activated=lambda: self.align("hcenter"))
        QShortcut(QKeySequence("Alt+V"), self, activated=lambda: self.align("vcenter"))

    def _set_tool_and_sync(self, tool):
        self._tool = tool
        self.set_tool(tool)
        self.parent()._update_tool_buttons(
            "select" if tool == self.TOOL_SELECT else
            "connect" if tool == self.TOOL_CONNECT else "pan"
        )
        if tool == self.TOOL_CONNECT:
            self._link_mode = True
        else:
            self._link_mode = False
            self._cleanup_drag_link()
        self._update_status()

    def _update_status(self):
        """更新父控件状态栏提示"""
        parent = self.parent()
        if parent and hasattr(parent, 'stats_label'):
            if self._tool == self.TOOL_CONNECT:
                parent.stats_label.setText(
                    "🔗 连线模式：从节点边缘按下，拖到另一节点释放即可创建连线\n"
                    "按 F2 切回选择模式 · 按 F4 切换平移模式"
                )
            elif self._tool == self.TOOL_PAN:
                parent.stats_label.setText("✋ 平移模式：拖拽画布移动视图")
            else:
                parent.stats_label.setText(
                    "✋ 选择模式：拖拽节点移动 · 框选多个节点\n"
                    "F3 进入连线模式 · 中键拖拽平移 · 滚轮缩放"
                )

    def _escape_handler(self):
        if self._drag_linking:
            self._cleanup_drag_link()
        self._scene.clearSelection()
        self._clear_marquee()

    def _cleanup_drag_link(self):
        """清理拖拽连线状态和预览线"""
        if self._drag_link_line is not None:
            try:
                # 仅在预览线仍属于当前 scene 时才移除，避免 load_data 清场后的 scene 不匹配崩溃
                if self._drag_link_line.scene() is self._scene:
                    self._scene.removeItem(self._drag_link_line)
            except (RuntimeError, ReferenceError):
                pass
            self._drag_link_line = None
        self._drag_linking = False
        self._drag_link_src = None
        if self._hover_node:
            self._hover_node._hovered = False
            try:
                self._hover_node._update_style()
            except RuntimeError:
                pass
            self._hover_node = None

    def start_linking(self):
        """进入连线模式（eNSP 风格：拖拽创建连线）"""
        self._tool = self.TOOL_CONNECT
        self._link_mode = True
        self.setCursor(Qt.CrossCursor)
        self._update_status()

    def cancel_linking(self):
        """退出连线模式"""
        self._cleanup_drag_link()
        self._link_mode = False
        self._tool = self.TOOL_SELECT
        self.setCursor(Qt.ArrowCursor)
        self._update_status()

    def _delete_selection(self):
        for node in self._scene.selectedItems():
            if isinstance(node, NodeGraphicsItem):
                self.deleteNodeLinksRequested.emit(node.asset_id)
        for edge in self._scene.selectedItems():
            if isinstance(edge, EdgeGraphicsItem):
                self.deleteLinkRequested.emit(edge.link_data)

    def _select_all(self):
        for n in self._nodes.values():
            n.setSelected(True)

    def _clear_selection(self):
        self._scene.clearSelection()

    def fit_to_view(self):
        if self._nodes:
            rect = self._scene.itemsBoundingRect().adjusted(-200, -200, 200, 200)
            self.fitInView(rect, Qt.KeepAspectRatio)

    def toggle_grid(self):
        self._show_grid = not self._show_grid
        self._rebuild_grid_pen()
        self.viewport().update()

    def toggle_snap(self):
        self._snap_to_grid = not self._snap_to_grid

    def _rebuild_grid_pen(self):
        self._grid_pen_minor = QPen(QColor(C["bg3"]), 1)
        self._grid_pen_major = QPen(QColor(C["surface"]), 1)

    def set_tool(self, tool):
        self._tool = tool
        if tool == self.TOOL_SELECT:
            self.setCursor(Qt.ArrowCursor)
        elif tool == self.TOOL_CONNECT:
            self.setCursor(Qt.CrossCursor)
        elif tool == self.TOOL_PAN:
            self.setCursor(Qt.OpenHandCursor)

    def snap(self, value):
        if self._snap_to_grid:
            return round(value / self.GRID_SIZE) * self.GRID_SIZE
        return value

    def is_collapsing_enabled(self):
        return len(self._nodes) > self.COLLAPSE_THRESHOLD

    def toggle_group_collapse(self, group_name):
        if group_name in self._collapsed_groups:
            self._collapsed_groups.remove(group_name)
        else:
            self._collapsed_groups.add(group_name)
        self._apply_collapse_visibility()

    def _apply_collapse_visibility(self):
        for node in self._nodes.values():
            if node.group_name in self._collapsed_groups:
                node.setVisible(False)
                for edge in self._edges:
                    if edge.src_node == node or edge.dst_node == node:
                        edge.setVisible(False)
            else:
                node.setVisible(True)
                for edge in self._edges:
                    if edge.src_node.isVisible() and edge.dst_node.isVisible():
                        edge.setVisible(True)
        self._scene.update()

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        if not self._show_grid:
            return
        gs = self.GRID_SIZE
        left = int(rect.left()) - (int(rect.left()) % gs)
        top = int(rect.top()) - (int(rect.top()) % gs)
        right = int(rect.right()) + gs
        bottom = int(rect.bottom()) + gs

        painter.setPen(self._grid_pen_minor)
        lines = []
        for x in range(left, right, gs):
            lines.append(QPointF(x, rect.top()))
            lines.append(QPointF(x, rect.bottom()))
        for y in range(top, bottom, gs):
            lines.append(QPointF(rect.left(), y))
            lines.append(QPointF(rect.right(), y))
        if lines:
            painter.drawLines(lines)

        painter.setPen(self._grid_pen_major)
        gs5 = gs * 5
        left5 = int(rect.left()) - (int(rect.left()) % gs5)
        top5 = int(rect.top()) - (int(rect.top()) % gs5)
        lines = []
        for x in range(left5, right, gs5):
            lines.append(QPointF(x, rect.top()))
            lines.append(QPointF(x, rect.bottom()))
        for y in range(top5, bottom, gs5):
            lines.append(QPointF(rect.left(), y))
            lines.append(QPointF(rect.right(), y))
        if lines:
            painter.drawLines(lines)

    def wheelEvent(self, event):
        f = 1.12 if event.angleDelta().y() > 0 else 1/1.12
        self.scale(f, f)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self._drag_linking:
                self._cleanup_drag_link()
            elif self._link_mode:
                self.cancel_linking()
            elif self._marquee_rect_item is not None:
                self._clear_marquee()
            self._scene.clearSelection()
            return
        super().keyPressEvent(event)

    def _clear_marquee(self):
        if self._marquee_rect_item is not None:
            self._scene.removeItem(self._marquee_rect_item)
            self._marquee_rect_item = None
        self._marquee_start = None

    def mouseDoubleClickEvent(self, event):
        """双击节点 -> 连接设备"""
        if event.button() != Qt.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        scene_pos = self.mapToScene(event.pos())
        node = self._find_node_at(scene_pos)
        if node is not None:
            self.connectRequested.emit(node.asset_id)
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        scene_pos = self.mapToScene(event.pos())

        # 中键平移 或 平移工具模式
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and self._tool == self.TOOL_PAN
        ):
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            return

        # 右键：取消拖拽连线，并退出平移 / 连线模式
        if event.button() == Qt.RightButton:
            if self._drag_linking:
                self._cleanup_drag_link()
            if self._tool in (self.TOOL_CONNECT, self.TOOL_PAN):
                self._set_tool_and_sync(self.TOOL_SELECT)
            return

        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        node = self._find_node_at(scene_pos)

        # 点击连线：选中它，不进入框选/拖拽，避免整个拓扑跟随鼠标
        if node is None and not self._link_mode:
            edge = self._find_edge_at(scene_pos)
            if edge is not None:
                self._scene.clearSelection()
                edge.setSelected(True)
                return

        # 连线模式：在节点上按下 → 开始拖拽连线
        if self._link_mode and node is not None:
            self._drag_linking = True
            self._drag_link_src = node
            r = getattr(node, "_r", 28)
            src_pos = node.pos()
            dx = scene_pos.x() - src_pos.x()
            dy = scene_pos.y() - src_pos.y()
            dist = math.hypot(dx, dy) or 1
            ux, uy = dx / dist, dy / dist
            start = QPointF(src_pos.x() + ux * (r + 2),
                            src_pos.y() + uy * (r + 2))
            self._drag_link_line = self._scene.addLine(
                start.x(), start.y(), scene_pos.x(), scene_pos.y(),
                QPen(QColor(C["yellow"]), 2, Qt.DashLine)
            )
            self._drag_link_line.setZValue(10000)
            self._drag_link_start = start
            self._drag_link_dir = QPointF(ux, uy)
            return

        # 空白处拖拽 → 框选（仅选择模式）
        if node is None and self._tool == self.TOOL_SELECT:
            self._scene.clearSelection()
            self._marquee_start = scene_pos
            path = QPainterPath()
            path.addRect(QRectF(scene_pos, scene_pos))
            self._marquee_rect_item = self._scene.addPath(
                path, QPen(QColor(C["blue"]), 1.5, Qt.DashLine), QBrush(QColor(137, 180, 250, 40))
            )
            self._marquee_rect_item.setZValue(10000)
            return

        # 选择模式：点击节点 → 拖拽移动
        if node is not None:
            if not node.isSelected():
                if not (event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
                    self._scene.clearSelection()
                node.setSelected(True)
            self._start_drag(node, scene_pos)
            return

        super().mousePressEvent(event)

    def _start_drag(self, node, scene_pos):
        self._drag_nodes = []
        self._drag_offsets = {}
        if node.isSelected():
            for selected in self._scene.selectedItems():
                if isinstance(selected, NodeGraphicsItem):
                    self._drag_nodes.append(selected)
                    self._drag_offsets[selected.asset_id] = (
                        scene_pos - selected.pos()
                    )
        else:
            self._drag_nodes.append(node)
            self._drag_offsets[node.asset_id] = scene_pos - node.pos()
        # 拖拽期间暂停 itemChange 写库，改为 mouseReleaseEvent 一次性写入
        for n in self._drag_nodes:
            n._position_locked = True

    def mouseMoveEvent(self, event):
        if self._panning:
            d = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
        elif self._drag_linking and self._drag_link_line is not None:
            scene_pos = self.mapToScene(event.pos())
            src = self._drag_link_src.pos()
            # 实时检测目标节点并高亮
            target_node = self._find_node_at(scene_pos)
            if target_node is not self._hover_node:
                if self._hover_node:
                    self._hover_node._hovered = False
                    try:
                        self._hover_node._update_style()
                    except RuntimeError:
                        pass
                self._hover_node = target_node if (target_node and target_node is not self._drag_link_src) else None
                if self._hover_node:
                    self._hover_node._hovered = True
                    try:
                        self._hover_node._update_style()
                    except RuntimeError:
                        pass

            # 计算连线起点（从源节点边缘出发）和目标点（可能在目标节点边缘）
            r_src = getattr(self._drag_link_src, "_r", 28)
            dx = scene_pos.x() - src.x()
            dy = scene_pos.y() - src.y()
            dist = math.hypot(dx, dy) or 1
            ux, uy = dx / dist, dy / dist
            start = QPointF(src.x() + ux * (r_src + 2),
                            src.y() + uy * (r_src + 2))
            if self._hover_node is not None:
                r_dst = getattr(self._hover_node, "_r", 28)
                end = QPointF(scene_pos.x() - ux * (r_dst + 2),
                              scene_pos.y() - uy * (r_dst + 2))
                pen = QPen(QColor(C["green"]), 3, Qt.DashLine)
            else:
                end = scene_pos
                pen = QPen(QColor(C["yellow"]), 2, Qt.DashLine)
            self._drag_link_line.setLine(start.x(), start.y(), end.x(), end.y())
            self._drag_link_line.setPen(pen)
        elif self._drag_nodes:
            scene_pos = self.mapToScene(event.pos())
            for n in self._drag_nodes:
                offset = self._drag_offsets.get(n.asset_id, QPointF())
                new_pos = scene_pos - offset
                if self._snap_to_grid:
                    new_pos.setX(self.snap(new_pos.x()))
                    new_pos.setY(self.snap(new_pos.y()))
                n.setPos(new_pos)
        elif self._marquee_start is not None and self._marquee_rect_item is not None:
            scene_pos = self.mapToScene(event.pos())
            rect = QRectF(self._marquee_start, scene_pos).normalized()
            path = QPainterPath()
            path.addRect(rect)
            self._marquee_rect_item.setPath(path)
            self._marquee_rect_item._rect = rect
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = False
            self.setCursor(
                Qt.OpenHandCursor if self._tool == self.TOOL_PAN else Qt.ArrowCursor
            )
            return

        # 拖拽连线释放
        if self._drag_linking and event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            target_node = self._find_node_at(scene_pos)

            # 创建连线（释放到有效目标节点）
            if target_node and target_node is not self._drag_link_src:
                src_id = self._drag_link_src.asset_id
                dst_id = target_node.asset_id
                self.linkCreated.emit(src_id, dst_id)

            # 创建连线成功 -> 自动切回选择模式，便于立即拖拽节点
            if target_node and target_node is not self._drag_link_src:
                self._cleanup_drag_link()
                self._set_tool_and_sync(self.TOOL_SELECT)
                return

            # 清理预览，保持在连线模式（可连续连线）
            self._cleanup_drag_link()
            # 仍处于连线模式，光标恢复十字
            if self._link_mode:
                self.setCursor(Qt.CrossCursor)
            return

        if self._drag_nodes:
            for n in self._drag_nodes:
                n._position_locked = False
                db.save_node_position(n.asset_id, n.pos().x(), n.pos().y())
            self._drag_nodes = []
            self._drag_offsets = {}
            return

        if self._marquee_rect_item is not None:
            rect = getattr(self._marquee_rect_item, "_rect", None)
            if rect and rect.width() > 3 and rect.height() > 3:
                for node in self._nodes.values():
                    if rect.intersects(node.sceneBoundingRect()):
                        node.setSelected(True)
            self._clear_marquee()
            return

        super().mouseReleaseEvent(event)

    def _find_node_at(self, scene_pos):
        for item in self._scene.items(scene_pos):
            if isinstance(item, NodeGraphicsItem):
                return item
            parent = item.parentItem()
            while parent:
                if isinstance(parent, NodeGraphicsItem):
                    return parent
                parent = parent.parentItem()
        return None

    def _find_edge_at(self, scene_pos):
        for item in self._scene.items(scene_pos):
            if isinstance(item, EdgeGraphicsItem):
                return item
        return None

    def align(self, mode):
        selected = [n for n in self._scene.selectedItems() if isinstance(n, NodeGraphicsItem)]
        if len(selected) < 2:
            QMessageBox.information(self, "对齐", "请选择至少 2 个节点")
            return
        rects = [n.sceneBoundingRect() for n in selected]
        positions = [(n.pos(), n) for n in selected]

        if mode == "left":
            target = min(r.left() for r in rects)
            for n in selected:
                n.setPos(target + (n.pos().x() - n.sceneBoundingRect().left()), n.pos().y())
        elif mode == "right":
            target = max(r.right() for r in rects)
            for n in selected:
                n.setPos(target - (n.sceneBoundingRect().right() - n.pos().x()), n.pos().y())
        elif mode == "top":
            target = min(r.top() for r in rects)
            for n in selected:
                n.setPos(n.pos().x(), target + (n.pos().y() - n.sceneBoundingRect().top()))
        elif mode == "bottom":
            target = max(r.bottom() for r in rects)
            for n in selected:
                n.setPos(n.pos().x(), target - (n.sceneBoundingRect().bottom() - n.pos().y()))
        elif mode == "hcenter":
            centers = [(r.left() + r.right()) / 2 for r in rects]
            target = sum(centers) / len(centers)
            for n in selected:
                cx = n.sceneBoundingRect().center().x()
                n.setPos(n.pos().x() + (target - cx), n.pos().y())
        elif mode == "vcenter":
            centers = [(r.top() + r.bottom()) / 2 for r in rects]
            target = sum(centers) / len(centers)
            for n in selected:
                cy = n.sceneBoundingRect().center().y()
                n.setPos(n.pos().x(), n.pos().y() + (target - cy))

        for n in selected:
            db.save_node_position(n.asset_id, n.pos().x(), n.pos().y())

    def contextMenuEvent(self, event):
        scene_pos = self.mapToScene(event.pos())
        node = self._find_node_at(scene_pos)

        if node:
            if not node.isSelected():
                self._scene.clearSelection()
                node.setSelected(True)
            menu = QMenu(self)
            edit_act = menu.addAction("编辑资产")
            edit_act.triggered.connect(lambda: self.editAssetRequested.emit(node.asset_id))

            neighbor_act = menu.addAction("查看邻居")
            neighbor_act.triggered.connect(lambda: self._highlight_neighbors(node))

            discover_act = menu.addAction("从此设备发现")
            discover_act.triggered.connect(lambda: self.discoverRequested.emit(node.asset_id))

            menu.addSeparator()

            if self._scene.selectedItems():
                align_menu = menu.addMenu("对齐")
                for label, mode in [
                    ("左对齐", "left"), ("右对齐", "right"),
                    ("顶部对齐", "top"), ("底部对齐", "bottom"),
                    ("水平居中", "hcenter"), ("垂直居中", "vcenter"),
                ]:
                    act = align_menu.addAction(label)
                    act.triggered.connect(lambda _=False, m=mode: self.align(m))

                grid_act = menu.addAction("吸附到网格")
                grid_act.setCheckable(True)
                grid_act.setChecked(self._snap_to_grid)
                grid_act.triggered.connect(self.toggle_snap)

            menu.addSeparator()
            del_links_act = menu.addAction("删除该节点所有连线")
            del_links_act.triggered.connect(lambda: self.deleteNodeLinksRequested.emit(node.asset_id))

            menu.exec_(event.globalPos())
            return

        edge = self._find_edge_at(scene_pos)
        if edge:
            menu = QMenu(self)
            edit_act = menu.addAction("编辑链路")
            edit_act.triggered.connect(lambda: self.editLinkRequested.emit(edge.link_data))

            del_act = menu.addAction("删除链路")
            del_act.triggered.connect(lambda: self.deleteLinkRequested.emit(edge.link_data))

            menu.addSeparator()
            detail_act = menu.addAction("链路详情")
            detail_act.triggered.connect(lambda: self._show_link_detail(edge))

            menu.exec_(event.globalPos())
            return

        menu = QMenu(self)
        tool_menu = menu.addMenu("工具")
        for label, t in [("选择 (F2)", self.TOOL_SELECT), ("连线 (F3)", self.TOOL_CONNECT), ("平移 (F4)", self.TOOL_PAN)]:
            act = tool_menu.addAction(label)
            act.triggered.connect(lambda _=False, x=t: self.set_tool(x))

        menu.addSeparator()
        grid_act = menu.addAction("显示网格")
        grid_act.setCheckable(True)
        grid_act.setChecked(self._show_grid)
        grid_act.triggered.connect(self.toggle_grid)

        snap_act = menu.addAction("吸附到网格")
        snap_act.setCheckable(True)
        snap_act.setChecked(self._snap_to_grid)
        snap_act.triggered.connect(self.toggle_snap)

        menu.addSeparator()
        fit_act = menu.addAction("适应窗口 (Ctrl+1)")
        fit_act.triggered.connect(self.fit_to_view)

        menu.exec_(event.globalPos())

    def _highlight_neighbors(self, node):
        self._scene.clearSelection()
        for edge in node._connected_edges:
            edge.setSelected(True)

    def _show_link_detail(self, edge):
        d = edge.link_data
        info = (
            f"链路 ID: {d.get('id', '-')}\n\n"
            f"源设备: {d.get('src_name', '')}\n"
            f"源端口: {d.get('src_interface', '')}\n\n"
            f"目标设备: {d.get('dst_name', '')}\n"
            f"目标端口: {d.get('dst_interface', '')}\n\n"
            f"链路类型: {d.get('link_type', 'ethernet')}\n"
            f"带宽: {d.get('bandwidth', '') or '-'}\n"
            f"发现时间: {d.get('discovered_at', '-')}"
        )
        QMessageBox.information(self, "链路详情", info)

    def load_data(self, location="全部站点"):
        # 增量更新：diff 节点增删，边全量重建（边重建轻量，不算浪费）
        assets = db.get_all_assets()
        if location != "全部站点":
            assets = [a for a in assets if (a.get("location") or "未设置") == location]
        links = db.get_all_topology_links(location)
        new_ids = {a["id"] for a in assets}

        # 1. 移除已不存在的节点
        removed = [nid for nid in self._nodes if nid not in new_ids]
        for nid in removed:
            node = self._nodes.pop(nid)
            node._destroyed = True
            if node.scene() is not None:
                self._scene.removeItem(node)

        # 2. 移除旧边（全量重建）
        for edge in self._edges:
            if edge.scene() is not None:
                self._scene.removeItem(edge)
            if edge._handle is not None and edge._handle.scene() is not None:
                self._scene.removeItem(edge._handle)
        self._edges.clear()
        # 清除节点旧边引用，避免残留已销毁的边导致拖拽卡顿
        for _node in self._nodes.values():
            _node._connected_edges.clear()
        self._drag_link_line = None
        self._drag_link_src = None
        self._drag_linking = False
        self._hover_node = None
        self._clear_marquee()

        if not assets:
            # 清空残留节点
            for nid in list(self._nodes.keys()):
                node = self._nodes.pop(nid)
                node._destroyed = True
                if node.scene() is not None:
                    self._scene.removeItem(node)
            text = self._scene.addText("No devices found\n\nAdd devices first, then come back")
            text.setDefaultTextColor(QColor(C["text2"]))
            text.setFont(QFont("Segoe UI", 14))
            text.setPos(-150, -50)
            return

        saved_positions = db.get_node_positions()

        # 3. 新增节点（给未保存位置的分配圆形初始位置）
        cx, cy = 0, 0
        r = max(180, len(assets) * 40)
        unsaved = [a for a in assets if a["id"] not in saved_positions]
        for i, a in enumerate(unsaved):
            angle = 2 * math.pi * i / len(unsaved) - math.pi / 2 if unsaved else 0
            saved_positions[a["id"]] = (cx + r * math.cos(angle), cy + r * math.sin(angle))

        for a in assets:
            aid = a["id"]
            if aid in self._nodes:
                # 已有节点：更新位置（如果 saved_positions 变了）
                x, y = saved_positions[aid]
                node = self._nodes[aid]
                if abs(node.pos().x() - x) > 0.5 or abs(node.pos().y() - y) > 0.5:
                    node._position_locked = True
                    node.setPos(x, y)
                    node._position_locked = False
            else:
                x, y = saved_positions[aid]
                node = create_node(a, x, y)
                self._scene.addItem(node)
                self._nodes[aid] = node

        # 4. 重建边
        saved_controls = db.get_edge_control_points()
        for link in links:
            sid = link["src_asset_id"]
            did = link["dst_asset_id"]
            if sid in self._nodes and did in self._nodes:
                try:
                    ctrl = saved_controls.get(link["id"])
                    edge = EdgeGraphicsItem(self._nodes[sid], self._nodes[did], link, control_offset=ctrl)
                    self._scene.addItem(edge)
                    self._scene.addItem(edge._handle)
                    self._edges.append(edge)
                except Exception as ex_edge:
                    import logging
                    logging.getLogger(__name__).warning(
                        'Failed to render edge %s->%s: %s', sid, did, ex_edge
                    )

        self.fitInView(self._scene.sceneRect().adjusted(-50, -50, 50, 50), Qt.KeepAspectRatio)


# Import db at module level to avoid circular imports
from core import db


class StyledButton(QPushButton):
    """Styled button with consistent look"""

    def __init__(self, text, color="blue", icon_char=None):
        super().__init__(text)
        self.setMinimumHeight(36)

        colors = {
            "blue": (C["blue"], C["bg"]),
            "green": (C["green"], C["bg"]),
            "red": (C["red"], C["bg"]),
            "surface": (C["text"], C["bg3"]),
        }
        fg, bg = colors.get(color, colors["blue"])

        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: 1px solid {C["surface"]};
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {C["surface"]};
                border-color: {fg};
            }}
            QPushButton:pressed {{
                background-color: {C["overlay"]};
            }}
        """)


class LinkEditDialog(QDialog):
    """Dialog for editing topology link details"""

    def __init__(self, link_data, parent=None):
        super().__init__(parent)
        self.link_data = link_data
        self.setWindowTitle("编辑链路")
        self.setModal(True)
        self.setMinimumSize(380, 250)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {C['bg2']};
                color: {C['text']};
            }}
            QLabel {{
                color: {C['text']};
            }}
            QLineEdit, QComboBox {{
                background-color: {C['bg']};
                color: {C['text']};
                border: 1px solid {C['surface']};
                border-radius: 6px;
                padding: 6px;
            }}
        """)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.summary_label = QLabel(
            f"{link_data.get('src_name', '')}  →  {link_data.get('dst_name', '')}"
        )
        self.summary_label.setStyleSheet(f"color: {C['lavender']}; font-weight: bold;")
        form.addRow("链路", self.summary_label)

        self.src_interface_edit = QLineEdit(link_data.get("src_interface", ""))
        form.addRow("源端口", self.src_interface_edit)

        self.dst_interface_edit = QLineEdit(link_data.get("dst_interface", ""))
        form.addRow("目标端口", self.dst_interface_edit)

        self.link_type_combo = QComboBox()
        self.link_type_combo.addItems(["ethernet", "fiber", "trunk", "wireless"])
        current_type = link_data.get("link_type", "ethernet")
        index = self.link_type_combo.findText(current_type)
        if index >= 0:
            self.link_type_combo.setCurrentIndex(index)
        else:
            self.link_type_combo.addItem(current_type)
            self.link_type_combo.setCurrentIndex(self.link_type_combo.count() - 1)
        form.addRow("类型", self.link_type_combo)

        self.bandwidth_edit = QLineEdit(link_data.get("bandwidth", ""))
        form.addRow("带宽", self.bandwidth_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self):
        return {
            "src_interface": self.src_interface_edit.text().strip(),
            "dst_interface": self.dst_interface_edit.text().strip(),
            "link_type": self.link_type_combo.currentText().strip(),
            "bandwidth": self.bandwidth_edit.text().strip(),
        }


class TopologyWidget(QWidget):
    """Main topology widget with toolbar and view"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_location = "全部站点"
        self.setStyleSheet(f"background-color: {C['bg']};")
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.view = TopologyView()
        self.view.setStyleSheet("border: none;")
        self.view.linkCreated.connect(self._on_link_created)
        self.view.editAssetRequested.connect(self._on_edit_asset)
        self.view.editLinkRequested.connect(self._on_edit_link)
        self.view.deleteLinkRequested.connect(self._on_delete_link)
        self.view.deleteNodeLinksRequested.connect(self._on_delete_node_links)
        self.view.discoverRequested.connect(self._on_discover_from_device)

        sidebar = QFrame()
        sidebar.setFixedWidth(240)
        sidebar.setStyleSheet(f"""
            QFrame {{
                background-color: {C['bg2']};
                border-right: 1px solid {C['bg3']};
            }}
        """)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 16)
        sidebar_layout.setSpacing(8)

        title = QLabel("网络拓扑")
        title.setStyleSheet(f"""
            color: {C['lavender']};
            font-size: 16px;
            font-weight: bold;
            padding: 8px 0;
        """)
        sidebar_layout.addWidget(title)

        self.location_label = QLabel("站点")
        self.location_label.setStyleSheet(
            f"color: {C['text3']}; font-size: 11px; font-weight: bold; padding-top: 4px;"
        )
        sidebar_layout.addWidget(self.location_label)

        self.location_combo = QComboBox()
        self.location_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {C['bg']};
                color: {C['text']};
                border: 1px solid {C['surface']};
                border-radius: 6px;
                padding: 6px;
            }}
        """)
        self.location_combo.currentTextChanged.connect(self._on_location_changed)
        sidebar_layout.addWidget(self.location_combo)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background-color: {C['bg3']};")
        sidebar_layout.addWidget(sep)

        tools_label = QLabel("工具")
        tools_label.setStyleSheet(
            f"color: {C['text3']}; font-size: 11px; font-weight: bold; padding-top: 8px;"
        )
        sidebar_layout.addWidget(tools_label)

        tool_group = QFrame()
        tool_group.setStyleSheet("QFrame{background:transparent;}")
        tool_layout = QHBoxLayout(tool_group)
        tool_layout.setContentsMargins(0, 0, 0, 0)
        tool_layout.setSpacing(4)

        self.btn_tool_select = StyledButton("🖱 选择", "blue")
        self.btn_tool_select.setCheckable(True)
        self.btn_tool_select.setChecked(True)
        self.btn_tool_select.setToolTip("选择模式：拖拽节点移动、框选 (F2)")
        self.btn_tool_select.clicked.connect(lambda: self.view._set_tool_and_sync(TopologyView.TOOL_SELECT))
        tool_layout.addWidget(self.btn_tool_select)

        self.btn_tool_connect = StyledButton("🔗 连线", "green")
        self.btn_tool_connect.setCheckable(True)
        self.btn_tool_connect.setToolTip("连线模式：从节点拖拽到节点创建连线 (F3)")
        self.btn_tool_connect.clicked.connect(lambda: self.view._set_tool_and_sync(TopologyView.TOOL_CONNECT))
        tool_layout.addWidget(self.btn_tool_connect)

        self.btn_tool_pan = StyledButton("✋ 平移", "surface")
        self.btn_tool_pan.setCheckable(True)
        self.btn_tool_pan.clicked.connect(lambda: self.view._set_tool_and_sync(TopologyView.TOOL_PAN))
        tool_layout.addWidget(self.btn_tool_pan)

        sidebar_layout.addWidget(tool_group)

        btn_refresh = StyledButton("↻ 刷新", "blue")
        btn_refresh.clicked.connect(self._refresh)
        sidebar_layout.addWidget(btn_refresh)

        btn_discover = StyledButton("⚡ 自动发现", "green")
        btn_discover.clicked.connect(self._auto_discover)
        sidebar_layout.addWidget(btn_discover)

        self.btn_edit = StyledButton("✎ 编辑链路", "surface")
        self.btn_edit.clicked.connect(self._edit_selected_link)
        sidebar_layout.addWidget(self.btn_edit)

        btn_del = StyledButton("🗑 删除链路", "red")
        btn_del.clicked.connect(self._del_link)
        sidebar_layout.addWidget(btn_del)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.HLine)
        sep3.setStyleSheet(f"background-color: {C['bg3']};")
        sidebar_layout.addWidget(sep3)

        view_label = QLabel("视图")
        view_label.setStyleSheet(
            f"color: {C['text3']}; font-size: 11px; font-weight: bold; padding-top: 4px;"
        )
        sidebar_layout.addWidget(view_label)

        view_group = QFrame()
        view_group.setStyleSheet("QFrame{background:transparent;}")
        view_layout = QHBoxLayout(view_group)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(4)

        self.btn_grid = StyledButton("⊞ 网格", "surface")
        self.btn_grid.setCheckable(True)
        self.btn_grid.setChecked(True)
        self.btn_grid.clicked.connect(self.view.toggle_grid)
        view_layout.addWidget(self.btn_grid)

        self.btn_snap = StyledButton("⊡ 吸附", "surface")
        self.btn_snap.setCheckable(True)
        self.btn_snap.setChecked(True)
        self.btn_snap.clicked.connect(self.view.toggle_snap)
        view_layout.addWidget(self.btn_snap)

        sidebar_layout.addWidget(view_group)

        btn_fit = StyledButton("⤢ 适应窗口", "surface")
        btn_fit.clicked.connect(self.view.fit_to_view)
        sidebar_layout.addWidget(btn_fit)

        self.btn_labels = StyledButton("🏷 标签", "surface")
        self.btn_labels.setCheckable(True)
        self.btn_labels.clicked.connect(self._toggle_labels)
        sidebar_layout.addWidget(self.btn_labels)

        sep_align = QFrame()
        sep_align.setFrameShape(QFrame.HLine)
        sep_align.setStyleSheet(f"background-color: {C['bg3']};")
        sidebar_layout.addWidget(sep_align)

        align_label = QLabel("对齐")
        align_label.setStyleSheet(
            f"color: {C['text3']}; font-size: 11px; font-weight: bold; padding-top: 4px;"
        )
        sidebar_layout.addWidget(align_label)

        align_row1 = QFrame()
        align_row1.setStyleSheet("QFrame{background:transparent;}")
        ar1_layout = QHBoxLayout(align_row1)
        ar1_layout.setContentsMargins(0, 0, 0, 0)
        ar1_layout.setSpacing(3)
        for icon, mode, tip in [("⇤", "left", "左对齐"), ("⇥", "right", "右对齐"),
                                 ("⇡", "top", "顶部对齐"), ("⇣", "bottom", "底部对齐")]:
            b = StyledButton(icon, "surface")
            b.setFixedWidth(36)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, m=mode: self.view.align(m))
            ar1_layout.addWidget(b)
        sidebar_layout.addWidget(align_row1)

        align_row2 = QFrame()
        align_row2.setStyleSheet("QFrame{background:transparent;}")
        ar2_layout = QHBoxLayout(align_row2)
        ar2_layout.setContentsMargins(0, 0, 0, 0)
        ar2_layout.setSpacing(3)
        for icon, mode, tip in [("↔", "hcenter", "水平居中"), ("↕", "vcenter", "垂直居中")]:
            b = StyledButton(icon, "surface")
            b.setFixedWidth(36)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, m=mode: self.view.align(m))
            ar2_layout.addWidget(b)
        sidebar_layout.addWidget(align_row2)

        sep_layout = QFrame()
        sep_layout.setFrameShape(QFrame.HLine)
        sep_layout.setStyleSheet(f"background-color: {C['bg3']};")
        sidebar_layout.addWidget(sep_layout)

        layout_label = QLabel("自动布局")
        layout_label.setStyleSheet(
            f"color: {C['text3']}; font-size: 11px; font-weight: bold; padding-top: 4px;"
        )
        sidebar_layout.addWidget(layout_label)

        btn_force = StyledButton("力导向布局", "surface")
        btn_force.clicked.connect(lambda: self._apply_layout("force_directed"))
        sidebar_layout.addWidget(btn_force)

        btn_tree = StyledButton("树形布局", "surface")
        btn_tree.clicked.connect(lambda: self._apply_layout("hierarchical"))
        sidebar_layout.addWidget(btn_tree)

        btn_reset = StyledButton("重置布局", "surface")
        btn_reset.clicked.connect(self._reset_layout)
        sidebar_layout.addWidget(btn_reset)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(f"background-color: {C['bg3']};")
        sidebar_layout.addWidget(sep2)

        io_label = QLabel("导入 / 导出")
        io_label.setStyleSheet(
            f"color: {C['text3']}; font-size: 11px; font-weight: bold; padding-top: 8px;"
        )
        sidebar_layout.addWidget(io_label)

        btn_export = StyledButton("导出拓扑", "surface")
        btn_export.clicked.connect(self._export)
        sidebar_layout.addWidget(btn_export)

        btn_import = StyledButton("导入拓扑", "surface")
        btn_import.clicked.connect(self._import)
        sidebar_layout.addWidget(btn_import)

        sidebar_layout.addStretch()

        self.stats_label = QLabel()
        self.stats_label.setStyleSheet(f"color: {C['text2']}; font-size: 11px;")
        self.stats_label.setWordWrap(True)
        sidebar_layout.addWidget(self.stats_label)

        hints = QLabel(
            "💡 <b>操作指南</b><br>"
            "F2 选择 · F3 连线 · F4 平移<br>"
            "<b>连线：点 🔗按钮 → 从节点拖到节点</b><br>"
            "框选: 拖拽空白 · 多选: Ctrl+点击<br>"
            "Ctrl+A 全选 · Delete 删除<br>"
            "Ctrl+H 网格 · Ctrl+G 吸附<br>"
            "Alt+方向 对齐 · Ctrl+1 适应"
        )
        hints.setStyleSheet(f"color: {C['text3']}; font-size: 10px; padding: 8px 0;")
        hints.setWordWrap(True)
        hints.setTextFormat(Qt.RichText)
        sidebar_layout.addWidget(hints)

        main_layout.addWidget(sidebar)

        main_layout.addWidget(self.view, 1)

        self._refresh_location_options()
        self._refresh()

    def _refresh_location_options(self):
        current = self.current_location
        assets = db.get_all_assets()
        locations = sorted({(a.get("location") or "未设置") for a in assets})

        self.location_combo.blockSignals(True)
        self.location_combo.clear()
        self.location_combo.addItem("全部站点")
        self.location_combo.addItems(locations)

        index = self.location_combo.findText(current)
        if index < 0:
            current = "全部站点"
            index = 0
        self.location_combo.setCurrentIndex(index)
        self.location_combo.blockSignals(False)
        self.current_location = current

    def _on_location_changed(self, location):
        self.current_location = location or "全部站点"
        self._refresh()

    def _current_assets(self):
        assets = db.get_all_assets()
        if self.current_location == "全部站点":
            return assets
        return [a for a in assets if (a.get("location") or "未设置") == self.current_location]

    def _current_links(self):
        return db.get_all_topology_links(self.current_location)

    def _selected_edge(self):
        selected = [item for item in self.view._scene.selectedItems() if isinstance(item, EdgeGraphicsItem)]
        return selected[0] if selected else None

    def _refresh(self):
        self._refresh_location_options()
        self.view.load_data(self.current_location)
        n = len(self.view._nodes)
        e = len(self.view._edges)
        self.stats_label.setText(
            f"📍 站点: {self.current_location}  |  设备: {n}  |  连线: {e}\n"
            f"工具: 选择(F2) · 连线(F3) · 平移(F4)"
        )

    def _add_link(self):
        if len(self.view._nodes) < 2:
            QMessageBox.warning(self, "错误", "当前站点需要至少 2 台设备")
            return
        self.view.start_linking()
        self._update_tool_buttons("connect")

    def _update_tool_buttons(self, active):
        self.btn_tool_select.setChecked(active == "select")
        self.btn_tool_connect.setChecked(active == "connect")
        self.btn_tool_pan.setChecked(active == "pan")

    def _on_link_created(self, src_id, dst_id):
        db.add_topology_link(src_id, dst_id)
        # 延迟到事件循环空闲执行，避免在 mouseReleaseEvent 中途重建场景
        # （scene.clear() 会销毁连线/节点，导致重入崩溃和连线模式残留）
        QTimer.singleShot(0, self._refresh)

    def _edit_selected_link(self):
        edge = self._selected_edge()
        if not edge:
            QMessageBox.information(self, "提示", "请先在拓扑中选中一条链路")
            return

        dialog = LinkEditDialog(edge.link_data, self)
        if dialog.exec() != QDialog.Accepted:
            return

        db.update_topology_link(edge.link_data["id"], **dialog.get_values())
        self._refresh()
        QMessageBox.information(self, "成功", "链路已更新")

    def _del_link(self):
        edge = self._selected_edge()
        if edge:
            link = edge.link_data
            text = f"删除 {link.get('src_name', '')} 与 {link.get('dst_name', '')} 之间的链路？"
            reply = QMessageBox.question(self, "删除链路", text)
            if reply != QMessageBox.Yes:
                return
            db.delete_topology_link(link["id"])
            self._refresh()
            return

        links = self._current_links()
        if not links:
            QMessageBox.information(self, "提示", "没有可删除的链路")
            return

        items = [f"{l['src_name']} <-> {l['dst_name']}" for l in links]
        item, ok = QInputDialog.getItem(self, "删除链路", "选择要删除的链路:", items, 0, False)
        if not ok:
            return

        db.delete_topology_link(links[items.index(item)]["id"])
        self._refresh()

    def _reset_layout(self):
        reply = QMessageBox.question(
            self, "重置布局",
            "是否将所有节点位置和连线曲线重置为默认？"
        )
        if reply != QMessageBox.Yes:
            return
        db.clear_node_positions()
        db.clear_edge_control_points()
        self._refresh()

    def _toggle_labels(self, checked):
        for edge in self.view._edges:
            edge.set_label_visible(checked)
        self.btn_labels.setText("隐藏标签" if checked else "显示标签")

    def _auto_discover(self):
        online = [a for a in self._current_assets() if a.get("status") == "online"]
        if not online:
            QMessageBox.information(self, "提示", "当前站点没有在线设备，请先扫描设备状态")
            return
        reply = QMessageBox.question(
            self, "自动发现",
            f"将对 {len(online)} 台在线设备执行 LLDP/CDP 邻居发现，\n"
            "通过 SSH 登录设备并解析邻居关系。\n\n继续？"
        )
        if reply != QMessageBox.Yes:
            return
        self._run_discovery(online)

    def _run_discovery(self, assets):
        self._discovery_progress = QProgressDialog(
            "正在发现拓扑...", "取消", 0, len(assets), self
        )
        self._discovery_progress.setWindowTitle("LLDP/CDP 自动发现")
        self._discovery_progress.setMinimumDuration(0)
        self._discovery_progress.setValue(0)

        self._discovery_worker = DiscoveryWorker(assets, self)
        self._discovery_worker.progress.connect(self._on_discovery_progress)
        self._discovery_worker.finished.connect(self._on_discover_finished)
        self._discovery_worker.error.connect(self._on_discover_error)
        self._discovery_worker.canceled.connect(self._on_discover_canceled)
        self._discovery_progress.canceled.connect(self._discovery_worker.cancel)
        self._discovery_worker.start()

    def _on_discovery_progress(self, current, total, message):
        if hasattr(self, '_discovery_progress'):
            self._discovery_progress.setMaximum(total)
            self._discovery_progress.setValue(current)
            self._discovery_progress.setLabelText(message)

    def _on_discover_finished(self, links):
        if hasattr(self, '_discovery_progress'):
            self._discovery_progress.close()
        self._refresh()
        if links:
            summary = f"发现 {len(links)} 条链路：\n\n"
            for link in links[:10]:
                summary += f"  {link['src_name']}:{link.get('src_intf', '')} ↔ {link['dst_name']}:{link.get('dst_intf', '')}\n"
            if len(links) > 10:
                summary += f"\n...还有 {len(links) - 10} 条"
            QMessageBox.information(self, "发现完成", summary)
        else:
            QMessageBox.information(self, "发现完成", "未发现新的链路")

    def _on_discover_error(self, message):
        if hasattr(self, '_discovery_progress'):
            self._discovery_progress.close()
        QMessageBox.critical(self, "发现失败", f"自动发现出错：\n{message}")

    def _on_discover_canceled(self):
        if hasattr(self, '_discovery_progress'):
            self._discovery_progress.close()
        QMessageBox.information(self, "已取消", "已取消拓扑自动发现")

    def _on_discover_from_device(self, asset_id):
        asset = db.get_asset_by_id(asset_id)
        if not asset:
            QMessageBox.warning(self, "错误", "设备数据不存在")
            return
        if asset.get("status") != "online":
            QMessageBox.information(self, "提示", f"设备 {asset['name']} 不在线，无法发现")
            return
        self._run_discovery([asset])

    def _on_edit_asset(self, asset_id):
        asset = db.get_asset_by_id(asset_id)
        if not asset:
            return
        from ui.asset_panel import AssetEditDialog
        dialog = AssetEditDialog(self, asset=asset)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if data:
                db.update_asset(asset_id, **data)
                self._refresh()

    def _on_edit_link(self, link_data):
        link_id = link_data.get("id")
        if link_id is None:
            return
        dialog = LinkEditDialog(link_data, self)
        if dialog.exec() == QDialog.Accepted:
            db.update_topology_link(link_id, **dialog.get_values())
            self._refresh()

    def _on_delete_link(self, link_data):
        link_id = link_data.get("id")
        if link_id is None:
            return
        text = f"删除 {link_data.get('src_name', '')} ↔ {link_data.get('dst_name', '')} 的链路？"
        reply = QMessageBox.question(self, "删除链路", text)
        if reply == QMessageBox.Yes:
            db.delete_topology_link(link_id)
            self._refresh()

    def _on_delete_node_links(self, asset_id):
        links = [e.link_data for e in self.view._edges
                 if e.src_node.asset_id == asset_id or e.dst_node.asset_id == asset_id]
        if not links:
            QMessageBox.information(self, "提示", "该设备没有连线")
            return
        reply = QMessageBox.question(
            self, "删除连线",
            f"确定删除该设备的 {len(links)} 条连线？"
        )
        if reply == QMessageBox.Yes:
            for link in links:
                db.delete_topology_link(link["id"])
            self._refresh()

    def _apply_layout(self, algorithm):
        node_ids = list(self.view._nodes.keys())
        if not node_ids:
            return
        edge_pairs = [(e.src_node.asset_id, e.dst_node.asset_id) for e in self.view._edges]
        if algorithm not in ("force_directed", "hierarchical"):
            return

        # 布局计算移后台线程，避免大拓扑时 UI 卡死
        self._layout_worker = LayoutWorker(algorithm, node_ids, edge_pairs, self)
        self._layout_worker.done.connect(self._on_layout_done)
        self._layout_worker.error.connect(
            lambda m: QMessageBox.critical(self, "布局失败", f"自动布局出错：\n{m}")
        )
        self._layout_worker.start()

    def _on_layout_done(self, positions):
        for nid, (x, y) in positions.items():
            node = self.view._nodes.get(nid)
            if node:
                node._position_locked = True
                node.setPos(x, y)
                node._position_locked = False
                db.save_node_position(nid, x, y)
        self.view.fitInView(self.view._scene.sceneRect().adjusted(-50, -50, 50, 50),
                            Qt.KeepAspectRatio)

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export", "topology.json", "JSON (*.json)")
        if not path:
            return

        assets = self._current_assets()
        links = self._current_links()
        data = {
            "location": self.current_location,
            "nodes": [{
                "id": a["id"],
                "name": a["name"],
                "ip": a["ip"],
                "location": a.get("location", ""),
            } for a in assets],
            "edges": [{
                "src": l["src_asset_id"],
                "dst": l["dst_asset_id"],
                "source_intf": l.get("src_interface", ""),
                "target_intf": l.get("dst_interface", ""),
                "link_type": l.get("link_type", "ethernet"),
                "bandwidth": l.get("bandwidth", ""),
            } for l in links]
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "成功", f"已导出到:\n{path}")

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import", "", "JSON (*.json)")
        if not path:
            return

        allowed_ids = None
        if self.current_location != "全部站点":
            allowed_ids = {asset["id"] for asset in self._current_assets()}

        success, message = TopologyManager().import_topology(path, allowed_ids)
        if success:
            self._refresh()
            QMessageBox.information(self, "成功", message)
        else:
            QMessageBox.critical(self, "错误", message)

