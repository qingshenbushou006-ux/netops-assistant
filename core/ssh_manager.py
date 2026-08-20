"""
SSH 连接管理模块
使用 Paramiko + Pyte 实现嵌入式终端
"""
import socket
import threading
import time

import paramiko
import pyte


LEGACY_HOST_KEY_ALGORITHMS = (
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "rsa-sha2-512",
    "rsa-sha2-256",
    "ssh-rsa",
)

LEGACY_KEY_EXCHANGES = (
    "curve25519-sha256@libssh.org",
    "ecdh-sha2-nistp256",
    "ecdh-sha2-nistp384",
    "ecdh-sha2-nistp521",
    "diffie-hellman-group16-sha512",
    "diffie-hellman-group-exchange-sha256",
    "diffie-hellman-group14-sha256",
    "diffie-hellman-group14-sha1",
    "diffie-hellman-group-exchange-sha1",
    "diffie-hellman-group1-sha1",
)

LEGACY_CIPHERS = (
    "aes128-ctr",
    "aes192-ctr",
    "aes256-ctr",
    "aes128-cbc",
    "aes192-cbc",
    "aes256-cbc",
    "3des-cbc",
)

LEGACY_ERROR_MARKERS = (
    "no acceptable host key",
    "incompatible ssh peer",
    "unknown cipher",
    "no acceptable kex algorithm",
)


def _safe_error_text(exc):
    try:
        return str(exc)
    except Exception:
        return repr(exc)


def _format_error_text(exc):
    message = _safe_error_text(exc)
    try:
        decoded = message.encode("gbk", errors="ignore").decode("utf-8", errors="ignore")
        return decoded or message
    except Exception:
        return message


def _is_legacy_handshake_error(exc):
    message = _safe_error_text(exc).lower()
    return any(marker in message for marker in LEGACY_ERROR_MARKERS)


def _create_client():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    return client


def _legacy_transport_factory(*args, **kwargs):
    transport = paramiko.Transport(*args, **kwargs)
    security_options = transport.get_security_options()
    if hasattr(security_options, "key_types"):
        security_options.key_types = LEGACY_HOST_KEY_ALGORITHMS
    if hasattr(security_options, "kex"):
        security_options.kex = LEGACY_KEY_EXCHANGES
    if hasattr(security_options, "ciphers"):
        security_options.ciphers = LEGACY_CIPHERS
    return transport


class SSHConnection:
    """单个 SSH 连接封装"""

    def __init__(self, host, port=22, username="", password="",
                 device_type="generic", timeout=10, enable_password="",
                 encoding="utf-8"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.device_type = device_type
        self.timeout = timeout
        self.enable_password = enable_password

        self.encoding = encoding

        self.client = None
        self.shell = None
        self.connected = False

        self.screen = pyte.Screen(120, 40)
        self.stream = pyte.Stream(self.screen)

        self._on_output = None
        self._on_screen_update = None
        self._on_disconnect = None
        self._output_thread = None
        self._running = False
        self._recv_paused = False

    def set_output_callback(self, callback):
        self._on_output = callback

    def set_screen_update_callback(self, callback):
        """设置屏幕更新回调（pyte 处理后触发）"""
        self._on_screen_update = callback

    def set_disconnect_callback(self, callback):
        self._on_disconnect = callback

    def connect(self):
        """建立 SSH 连接"""
        connect_kwargs = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "timeout": self.timeout,
            "allow_agent": False,
            "look_for_keys": False,
        }

        try:
            self.client = _create_client()
            self.client.connect(**connect_kwargs)
        except paramiko.AuthenticationException:
            self._close_client_only()
            return False, "认证失败：用户名或密码错误"
        except paramiko.SSHException as exc:
            if not _is_legacy_handshake_error(exc):
                self._close_client_only()
                return False, f"SSH 错误：{_format_error_text(exc)}"

            self._close_client_only()
            try:
                self.client = _create_client()
                self.client.connect(
                    **connect_kwargs,
                    transport_factory=_legacy_transport_factory,
                )
            except paramiko.AuthenticationException:
                self._close_client_only()
                return False, "认证失败：用户名或密码错误"
            except paramiko.SSHException as legacy_exc:
                self._close_client_only()
                return False, f"SSH 错误：{_format_error_text(legacy_exc)}"
            except socket.timeout:
                self._close_client_only()
                return False, f"连接超时：{self.host}:{self.port}"
            except socket.error as legacy_exc:
                self._close_client_only()
                return False, f"网络错误：{legacy_exc}"
            except Exception as legacy_exc:
                self._close_client_only()
                return False, f"未知错误：{_format_error_text(legacy_exc)}"
        except socket.timeout:
            self._close_client_only()
            return False, f"连接超时：{self.host}:{self.port}"
        except socket.error as exc:
            self._close_client_only()
            return False, f"网络错误：{exc}"
        except Exception as exc:
            self._close_client_only()
            return False, f"未知错误：{_format_error_text(exc)}"

        self.shell = self.client.invoke_shell(
            term="xterm-256color",
            width=120,
            height=40,
        )
        self.shell.settimeout(0.1)

        # SSH Keepalive 防止空闲断开
        transport = self.client.get_transport()
        if transport:
            transport.set_keepalive(15)

        self.connected = True
        self._running = True
        self._output_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._output_thread.start()
        return True, "连接成功"

    def _close_client_only(self):
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass
        self.client = None

    def _receive_loop(self):
        while self.connected:
            # 暂停机制：_running=False 时等待而非退出
            if not self._running:
                time.sleep(0.05)
                continue
            if self._recv_paused:
                time.sleep(0.1)
                continue
            try:
                if self.shell and not self.shell.closed:
                    data = self.shell.recv(4096)
                    if data:
                        text = data.decode(self.encoding, errors="replace")
                        self.stream.feed(text)
                        if self._on_output:
                            self._on_output(text)
                    else:
                        break
                else:
                    break
            except socket.timeout:
                continue
            except Exception:
                break

        was_paused = not self._running
        if not was_paused:
            self.connected = False
            self._running = False
            if self._on_disconnect:
                self._on_disconnect()

    def send_command_paged(self, command, timeout=30):
        """
        发送命令并自动处理分页（--- More --- 等），返回完整输出。
        暂停 receive loop 避免数据被吞。
        """
        if not (self.shell and self.connected and not self.shell.closed):
            return ""

        _MORE_PATTERNS = ("--More--", "---- More ----", "--- More ---", " --More-- ")

        # 暂停 receive loop，防止它吞掉数据
        self._recv_paused = True
        try:
            self.shell.send(command + "\n")

            deadline = time.time() + timeout
            chunks = []
            more_count = 0

            while time.time() < deadline:
                try:
                    if self.shell.recv_ready():
                        data = self.shell.recv(4096)
                        if not data:
                            break
                        text = data.decode(self.encoding, errors="replace")
                        self.stream.feed(text)
                        if self._on_output:
                            self._on_output(text)
                        chunks.append(text)
                        deadline = time.time() + timeout
                    else:
                        time.sleep(0.1)
                except socket.timeout:
                    time.sleep(0.05)

                # 检查分页提示
                combined = "".join(chunks)
                tail = combined[-80:]
                found_more = False
                for pat in _MORE_PATTERNS:
                    if pat in tail:
                        found_more = True
                        chunks[-1] = chunks[-1].replace(pat, "")
                        break
                if found_more:
                    more_count += 1
                    try:
                        self.shell.send(" ")
                    except Exception:
                        break
                    deadline = time.time() + timeout
                    time.sleep(0.3)

            result = "".join(chunks)
            result = result.replace("\r\n", "\n").replace("\r", "\n")
            return result.strip()

        except Exception:
            self.connected = False
            return ""
        finally:
            self._recv_paused = False

    def send_command(self, command, wait_time=None):
        if not (self.shell and self.connected and not self.shell.closed):
            return "" if wait_time is not None else False

        try:
            self.shell.send(command + "\n")
            if wait_time is None:
                return True

            # 暂停 receive loop 避免数据竞争
            self._recv_paused = True
            time.sleep(0.15)

            deadline = time.time() + max(wait_time, 0)
            chunks = []
            while time.time() < deadline:
                try:
                    if self.shell.recv_ready():
                        data = self.shell.recv(4096)
                        if not data:
                            break
                        text = data.decode(self.encoding, errors="replace")
                        self.stream.feed(text)
                        if self._on_output:
                            self._on_output(text)
                        chunks.append(text)
                        deadline = time.time() + max(wait_time, 0)
                    else:
                        time.sleep(0.1)
                except socket.timeout:
                    time.sleep(0.05)

            return "".join(chunks)
        except Exception:
            self.connected = False
            return "" if wait_time is not None else False
        finally:
            self._recv_paused = False

    def enter_enable_mode(self, wait_time=1):
        if not self.enable_password:
            return True

        output = self.send_command("enable", wait_time=wait_time)
        if self.enable_password and "password" in output.lower():
            output += self.send_command(self.enable_password, wait_time=wait_time)
        return True

    def send_keys(self, data):
        if self.shell and self.connected and not self.shell.closed:
            try:
                self.shell.send(data)
                return True
            except Exception:
                self.connected = False
                return False
        return False

    def resize(self, cols, rows):
        if self.shell and self.connected and not self.shell.closed:
            try:
                self.shell.resize_pty(width=cols, height=rows)
                self.screen.resize(cols, rows)
            except Exception:
                pass

    def disconnect(self):
        self._running = False
        self.connected = False
        try:
            if self.shell:
                self.shell.close()
            if self.client:
                self.client.close()
        except Exception:
            pass

    def get_screen_text(self):
        return "\n".join(self.screen.display)

    def __del__(self):
        self.disconnect()


class ConnectionManager:
    """管理多个 SSH 连接"""

    def __init__(self):
        self._connections = {}

    def get_connection(self, asset_id):
        return self._connections.get(asset_id)

    def create_connection(self, asset_id, host, port=22, username="",
                          password="", device_type="generic"):
        self.close_connection(asset_id)

        conn = SSHConnection(
            host=host,
            port=port,
            username=username,
            password=password,
            device_type=device_type,
        )
        self._connections[asset_id] = conn
        return conn

    def close_connection(self, asset_id):
        conn = self._connections.pop(asset_id, None)
        if conn:
            conn.disconnect()

    def close_all(self):
        for conn in self._connections.values():
            conn.disconnect()
        self._connections.clear()

    def get_active_ids(self):
        return [aid for aid, c in self._connections.items() if c.connected]
