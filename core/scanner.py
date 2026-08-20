"""
网络扫描模块 - 检测设备在线状态
"""
import subprocess
import platform
import socket
import threading
from concurrent.futures import ThreadPoolExecutor


def ping_host(ip, timeout=2):
    """Ping 单个主机，返回是否在线"""
    param = "-n" if platform.system().lower() == "windows" else "-c"
    timeout_param = "-w" if platform.system().lower() == "windows" else "-W"
    try:
        result = subprocess.run(
            ["ping", param, "1", timeout_param, str(timeout), ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 2,
        )
        return result.returncode == 0
    except Exception:
        return False


def check_port(ip, port=22, timeout=2):
    """检测端口是否开放"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, int(port)))
        sock.close()
        return result == 0
    except Exception:
        return False


def scan_assets_batch(assets, callback=None, max_workers=20):
    """
    批量检测资产在线状态
    assets: list of dict, 每个需有 'id', 'ip', 'port' 字段
    callback: function(asset_id, is_online) 
    返回 {asset_id: bool}
    """
    results = {}

    def _check(asset):
        aid = asset.get("id")
        if asset.get("protocol") == "serial":
            return aid, None

        ip = asset.get("ip", "")
        port = asset.get("port", 22)
        online = ping_host(ip) or check_port(ip, port)
        results[aid] = online
        if callback:
            callback(aid, online)
        return aid, online

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(_check, assets))

    return results
