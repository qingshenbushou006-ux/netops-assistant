"""
网络拓扑发现与管理
支持:
- LLDP/CDP邻居发现
- ARP表分析
- 手动拓扑编辑
- 拓扑数据导入导出
"""
import re
import json
import ipaddress
from typing import List, Dict, Tuple, Optional, Set
from collections import defaultdict

from core import db
from core.ssh_manager import SSHConnection


# LLDP/CDP邻居解析命令
NEIGHBOR_COMMANDS = {
    "huawei": {
        "lldp": "display lldp neighbor brief",
        "lldp_detail": "display lldp neighbor interface",
        "arp": "display arp",
        "interfaces": "display interface brief",
        "mac_table": "display mac-address",
    },
    "cisco": {
        "lldp": "show lldp neighbors",
        "lldp_detail": "show lldp neighbors detail",
        "cdp": "show cdp neighbors",
        "cdp_detail": "show cdp neighbors detail",
        "arp": "show arp",
        "interfaces": "show ip interface brief",
        "mac_table": "show mac address-table",
    },
    "h3c": {
        "lldp": "display lldp neighbor-information list",
        "lldp_detail": "display lldp neighbor-information interface",
        "arp": "display arp",
        "interfaces": "display interface brief",
        "mac_table": "display mac-address",
    },
    "linux": {
        "arp": "arp -a",
        "interfaces": "ip addr show",
        "routes": "ip route show",
        "neighbors": "ip neigh show",
    },
    "default": {
        "lldp": "show lldp neighbors",
        "arp": "show arp",
        "interfaces": "show ip interface brief",
    },
}


def get_neighbor_commands(vendor: str) -> dict:
    """获取厂商对应的邻居发现命令"""
    vendor_lower = vendor.lower() if vendor else ""
    for key in NEIGHBOR_COMMANDS:
        if key in vendor_lower:
            return NEIGHBOR_COMMANDS[key]
    return NEIGHBOR_COMMANDS["default"]


class LLDPNeighbor:
    """LLDP邻居信息"""
    def __init__(self, local_interface: str, remote_interface: str,
                 remote_name: str, remote_ip: str = ""):
        self.local_interface = local_interface
        self.remote_interface = remote_interface
        self.remote_name = remote_name
        self.remote_ip = remote_ip

    def __repr__(self):
        return f"LLDP({self.local_interface} -> {self.remote_name}:{self.remote_interface})"


class ARPEntry:
    """ARP表项"""
    def __init__(self, ip: str, mac: str, interface: str = ""):
        self.ip = ip
        self.mac = mac
        self.interface = interface


class TopologyManager:
    """拓扑管理器"""

    def __init__(self):
        self._progress_callback = None
        self._log_callback = None

    def set_callbacks(self, progress_cb=None, log_cb=None):
        """设置回调"""
        self._progress_callback = progress_cb
        self._log_callback = log_cb

    def _report_progress(self, current: int, total: int, message: str):
        if self._progress_callback:
            self._progress_callback(current, total, message)

    def _report_log(self, message: str):
        if self._log_callback:
            self._log_callback(message)

    def discover_neighbors(self, asset: dict, cancel_event=None) -> List[LLDPNeighbor]:
        """发现单台设备的LLDP邻居"""
        vendor = asset.get("vendor", "")
        commands = get_neighbor_commands(vendor)

        conn = SSHConnection(
            host=asset["ip"],
            port=asset.get("port", 22),
            username=asset.get("username", ""),
            password=asset.get("password", ""),
            enable_password=asset.get("enable_password", ""),
        )

        if cancel_event is not None and cancel_event.is_set():
            return []

        success, msg = conn.connect()
        if not success:
            self._report_log(f"连接 {asset['name']} 失败: {msg}")
            return []

        neighbors = []
        try:
            if cancel_event is not None and cancel_event.is_set():
                return []

            if asset.get("enable_password"):
                conn.enter_enable_mode(wait_time=1)

            if cancel_event is not None and cancel_event.is_set():
                return []

            # 尝试LLDP
            if "lldp" in commands:
                output = conn.send_command(commands["lldp"], wait_time=3)
                if cancel_event is not None and cancel_event.is_set():
                    return []
                neighbors = self._parse_lldp_output(output, vendor)

            # 如果LLDP没结果，尝试CDP（Cisco特有）
            if not neighbors and "cdp" in commands:
                if cancel_event is not None and cancel_event.is_set():
                    return []
                output = conn.send_command(commands["cdp"], wait_time=3)
                if cancel_event is not None and cancel_event.is_set():
                    return []
                neighbors = self._parse_cdp_output(output)

        except Exception as e:
            self._report_log(f"发现邻居异常: {e}")
        finally:
            conn.disconnect()

        return neighbors

    def _parse_lldp_output(self, output: str, vendor: str) -> List[LLDPNeighbor]:
        """解析LLDP邻居输出"""
        neighbors = []
        if not output:
            return neighbors

        lines = output.split("\n")
        # 表头关键词组合（一行同时含某组全部词则视为表头/说明行跳过）
        _header_markers = (
            {"local", "interface", "neighbor"},
            {"device", "capability", "codes"},
            {"chassis", "id"},
            {"device", "id", "local", "intf", "hold-time"},
        )

        def _is_rubbish_line(line: str) -> bool:
            stripped = line.strip()
            if not stripped:
                return True
            low = stripped.lower()
            # 分隔线/统计行
            if any(t in low for t in ("total items", "total entries",
                                       "------", "======", "items:")):
                return True
            tokens = set(low.split())
            for marker in _header_markers:
                if marker.issubset(tokens):
                    return True
            return False

        if "huawei" in vendor.lower() or "h3c" in vendor.lower():
            # Huawei/H3C display lldp neighbor brief:
            #   Local Interface    Neighbor Device    Neighbor Interface
            #   GE0/0/1            DeviceA            GE0/0/2
            for line in lines:
                if _is_rubbish_line(line):
                    continue
                parts = line.strip().split()
                if len(parts) < 3:
                    continue
                # 接口名列必须以字母开头（GE/GigE/Eth/XGE/100GE/Vlan 等）
                if not parts[0][0].isalpha():
                    continue
                local_intf = parts[0]
                remote_name = parts[1]
                remote_intf = parts[-1]  # 最后一列是邻居接口
                neighbors.append(LLDPNeighbor(local_intf, remote_intf, remote_name))
        else:
            # Cisco brief:
            #   Device ID     Local Intf    Hold-time  Capability  Port ID
            #   DeviceA       Gi0/1         120        R           Gi0/2
            for line in lines:
                if _is_rubbish_line(line):
                    continue
                parts = line.strip().split()
                if len(parts) < 5:
                    continue
                # Device ID 必须以字母开头（排除 (R)/--- 等标记）
                if not parts[0][0].isalpha():
                    continue
                remote_name = parts[0]
                local_intf = parts[1]
                remote_intf = parts[-1]
                neighbors.append(LLDPNeighbor(local_intf, remote_intf, remote_name))

        return neighbors

    def _parse_cdp_output(self, output: str) -> List[LLDPNeighbor]:
        """解析CDP邻居输出"""
        neighbors = []
        if not output:
            return neighbors

        lines = output.split("\n")
        current_device = {}

        for line in lines:
            # Device ID
            device_match = re.search(r'Device ID:\s*(.+)', line)
            if device_match:
                if current_device:
                    neighbors.append(LLDPNeighbor(
                        current_device.get("local_intf", ""),
                        current_device.get("remote_intf", ""),
                        current_device.get("name", "")
                    ))
                current_device = {"name": device_match.group(1).strip()}
                continue

            # Interface
            intf_match = re.search(
                r'Interface:\s*(\S+).*Port ID.*:\s*(\S+)', line
            )
            if intf_match and current_device:
                current_device["local_intf"] = intf_match.group(1)
                current_device["remote_intf"] = intf_match.group(2)

        # 最后一个设备
        if current_device and "local_intf" in current_device:
            neighbors.append(LLDPNeighbor(
                current_device["local_intf"],
                current_device["remote_intf"],
                current_device["name"]
            ))

        return neighbors

    # ponytail: discover_arp_table / _parse_arp_output 当前无调用方（死代码）。
    # 保留供 "ARP 反查拓扑 fallback"（文档 P2-11）接入：对不支持 LLDP/CDP 的设备，
    # 用 ARP+MAC 表交叉比对补全链路。接入时复用 discover_neighbors 的同一 SSH 连接（P0 SSH 复用）。
    def discover_arp_table(self, asset: dict) -> List[ARPEntry]:
        """发现设备的ARP表"""
        vendor = asset.get("vendor", "")
        commands = get_neighbor_commands(vendor)

        conn = SSHConnection(
            host=asset["ip"],
            port=asset.get("port", 22),
            username=asset.get("username", ""),
            password=asset.get("password", ""),
            enable_password=asset.get("enable_password", ""),
        )

        success, msg = conn.connect()
        if not success:
            return []

        entries = []
        try:
            if asset.get("enable_password"):
                conn.enter_enable_mode(wait_time=1)

            if "arp" in commands:
                output = conn.send_command(commands["arp"], wait_time=3)
                entries = self._parse_arp_output(output, vendor)
        except Exception:
            pass
        finally:
            conn.disconnect()

        return entries

    def _parse_arp_output(self, output: str, vendor: str) -> List[ARPEntry]:
        """解析ARP表输出"""
        entries = []
        if not output:
            return entries

        lines = output.split("\n")
        for line in lines:
            # 通用ARP格式: IP MAC Interface
            match = re.search(
                r'(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4})\s+(\S+)',
                line
            )
            if match:
                ip = match.group(1)
                mac = match.group(2)
                intf = match.group(3)
                entries.append(ARPEntry(ip, mac, intf))
                continue

            # Linux格式: ? (10.1.1.1) at aa:bb:cc:dd:ee:ff [ether] on eth0
            match = re.search(
                r'\?\s+\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]+)\s+.*\s+on\s+(\S+)',
                line
            )
            if match:
                entries.append(ARPEntry(match.group(1), match.group(2), match.group(3)))

        return entries

    def auto_discover_topology(self, assets: List[dict] = None,
                               max_workers: int = 10,
                               cancel_event=None) -> List[Dict]:
        """
        自动发现拓扑（并发版）
        返回发现的链路列表

        max_workers: 并发 SSH 扫描线程数
        cancel_event: threading.Event，置位后停止后续扫描（协作取消）
        """
        if assets is None:
            assets = db.get_all_assets()

        online_assets = [a for a in assets if a.get("status") == "online"]
        if not online_assets:
            self._report_log("没有在线设备")
            return []

        asset_by_name = {a["name"].lower(): a for a in assets}
        asset_by_ip = {a["ip"]: a for a in assets}

        total = len(online_assets)
        results = {}  # asset_id -> list[LLDPNeighbor]
        errors = []

        def _scan_one(asset: dict):
            """单台设备发现（在线程池 worker 中执行）"""
            if cancel_event is not None and cancel_event.is_set():
                return
            self._report_log(f"扫描 {asset['name']} ({asset['ip']})...")
            try:
                neighbors = self.discover_neighbors(asset, cancel_event=cancel_event)
                results[asset["id"]] = neighbors
                self._report_log(f"  {asset['name']}: 发现 {len(neighbors)} 个邻居")
            except Exception as e:
                errors.append(f"{asset['name']}: {e}")
                self._report_log(f"  {asset['name']}: 异常 {e}")

        # 并发扫描
        from concurrent.futures import ThreadPoolExecutor, as_completed
        done = 0
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_scan_one, a): a for a in online_assets}
            for future in as_completed(futures):
                done += 1
                asset = futures[future]
                self._report_progress(done, total, f"正在发现 {asset['name']} 的邻居...")
                if cancel_event is not None and cancel_event.is_set():
                    # 取消：停止提交剩余任务
                    for f in futures:
                        f.cancel()
                    break

        if cancel_event is not None and cancel_event.is_set():
            self._report_log("发现已取消")
            return []

        # 汇总链路
        discovered_links = []
        seen_pairs = set()
        for asset in online_assets:
            neighbors = results.get(asset["id"], [])
            for neighbor in neighbors:
                remote_asset = None
                if neighbor.remote_name in asset_by_name:
                    remote_asset = asset_by_name[neighbor.remote_name]
                elif neighbor.remote_ip and neighbor.remote_ip in asset_by_ip:
                    remote_asset = asset_by_ip[neighbor.remote_ip]
                else:
                    remote_asset = self._fuzzy_match_asset(
                        neighbor, asset_by_name, asset_by_ip)

                if remote_asset:
                    pair = tuple(sorted((asset["id"], remote_asset["id"])))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    db.add_topology_link(
                        asset["id"], remote_asset["id"],
                        neighbor.local_interface, neighbor.remote_interface,
                        "ethernet"
                    )
                    discovered_links.append({
                        "src_id": asset["id"],
                        "src_name": asset["name"],
                        "src_intf": neighbor.local_interface,
                        "dst_id": remote_asset["id"],
                        "dst_name": remote_asset["name"],
                        "dst_intf": neighbor.remote_interface,
                        "link_type": "ethernet",
                    })

        if errors:
            self._report_log(f"发现完成，{len(errors)} 台设备异常")
        self._report_log(f"发现 {len(discovered_links)} 条链路")
        return discovered_links

    def _fuzzy_match_asset(self, neighbor: LLDPNeighbor,
                           asset_by_name: dict, asset_by_ip: dict):
        """LLDP 邻居名与本地资产模糊匹配，按序回退。

        精确名/IP 已在调用前查过，此处处理：
        1. 去域名后缀（DeviceA.example.com → DeviceA）
        2. 去尾部 -N/_N 序号（R1-2 → R1）
        3. CIDR 子网匹配（remote_ip 落在资产网段内）
        """
        name = (neighbor.remote_name or "").strip()
        if not name:
            return None

        # 1. 去域名后缀
        base = name.split(".")[0].lower()
        if base in asset_by_name:
            return asset_by_name[base]

        # 2. 去尾部 -N / _N 序号
        for sep in ("-", "_"):
            idx = base.rfind(sep)
            if idx > 0 and base[idx + 1:].isdigit():
                stripped = base[:idx]
                if stripped in asset_by_name:
                    return asset_by_name[stripped]

        # 3. CIDR 子网匹配（remote_ip 命中某资产网段）
        if neighbor.remote_ip:
            for ip, asset in asset_by_ip.items():
                if _ip_in_network(neighbor.remote_ip, ip):
                    return asset

        return None


    def add_manual_link(self, src_id: int, dst_id: int,
                        src_intf: str = "", dst_intf: str = "",
                        link_type: str = "ethernet", bandwidth: str = "") -> int:
        """手动添加链路"""
        return db.add_topology_link(src_id, dst_id, src_intf, dst_intf, link_type, bandwidth)

    def get_topology_data(self) -> Dict:
        """
        获取拓扑数据（用于可视化）
        返回: {nodes: [...], edges: [...]}
        """
        assets = db.get_all_assets()
        links = db.get_all_topology_links()

        nodes = []
        for asset in assets:
            nodes.append({
                "id": asset["id"],
                "name": asset["name"],
                "ip": asset["ip"],
                "vendor": asset.get("vendor", ""),
                "status": asset.get("status", "unknown"),
                "group": asset.get("group_name", "其他"),
            })

        edges = []
        for link in links:
            edges.append({
                "id": link["id"],
                "source": link["src_asset_id"],
                "target": link["dst_asset_id"],
                "source_intf": link.get("src_interface", ""),
                "target_intf": link.get("dst_interface", ""),
                "link_type": link.get("link_type", "ethernet"),
                "bandwidth": link.get("bandwidth", ""),
                "source_name": link.get("src_name", ""),
                "target_name": link.get("dst_name", ""),
            })

        return {"nodes": nodes, "edges": edges}

    def export_topology(self, file_path: str) -> bool:
        """导出拓扑到JSON文件"""
        try:
            data = self.get_topology_data()
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def import_topology(self, file_path: str,
                        allowed_asset_ids: Optional[Set[int]] = None) -> Tuple[bool, str]:
        """从JSON文件导入拓扑"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            imported = 0
            duplicates = 0
            invalid = 0
            skipped = 0

            for edge in data.get("edges", []):
                source = edge.get("source", edge.get("src"))
                target = edge.get("target", edge.get("dst"))

                if isinstance(source, str):
                    asset = self._find_asset_by_name_or_ip(source)
                    source = asset["id"] if asset else None

                if isinstance(target, str):
                    asset = self._find_asset_by_name_or_ip(target)
                    target = asset["id"] if asset else None

                if source is None or target is None:
                    invalid += 1
                    continue

                if allowed_asset_ids is not None and (
                        source not in allowed_asset_ids or target not in allowed_asset_ids):
                    skipped += 1
                    continue

                _, created = db.add_topology_link(
                    source, target,
                    edge.get("source_intf", ""),
                    edge.get("target_intf", ""),
                    edge.get("link_type", "ethernet"),
                    edge.get("bandwidth", ""),
                    return_created=True,
                )
                if created:
                    imported += 1
                else:
                    duplicates += 1

            message = f"成功导入 {imported} 条链路"
            if duplicates:
                message += f"\n跳过 {duplicates} 条重复链路"
            if invalid:
                message += f"\n跳过 {invalid} 条无效链路"
            if skipped:
                message += f"\n跳过 {skipped} 条不在当前站点的链路"
            return True, message

        except Exception as e:
            return False, f"导入失败: {e}"

    def _find_asset_by_name_or_ip(self, identifier: str) -> Optional[dict]:
        """通过名称或IP查找资产"""
        assets = db.get_all_assets()
        for asset in assets:
            if asset["name"] == identifier or asset["ip"] == identifier:
                return asset
        return None


def _ip_in_network(ip: str, network: str) -> bool:
    """判断 IP 是否落在 network 网段内（支持 CIDR 或单个 IP）。

    network 不做 format 校验，非 CIDR 格式直接退化为字符串相等。
    """
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(network, strict=False)
    except (ValueError, TypeError):
        return ip == network


def generate_sample_topology():
    """生成示例拓扑数据"""
    assets = db.get_all_assets()
    if len(assets) < 2:
        return

    # 简单连接：第一台设备连接其他所有设备
    main_device = assets[0]
    for i in range(1, len(assets)):
        db.add_topology_link(
            main_device["id"], assets[i]["id"],
            f"GE0/0/{i}", f"GE0/0/1",
            "ethernet", "1Gbps"
        )
