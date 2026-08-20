"""
Telnet 连接管理模块
接口与 SSHConnection 保持一致，方便终端统一调用
"""
import socket
import threading
import time
import telnetlib


class TelnetConnection:
    """单个 Telnet 连接封装"""

    def __init__(self, host, port=23, username="", password="",
                 timeout=10, encoding="utf-8"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self.encoding = encoding

        self._tn = None
        self.connected = False

        self._on_output = None
        self._on_disconnect = None
        self._output_thread = None
        self._running = False

    def set_output_callback(self, callback):
        self._on_output = callback

    def set_disconnect_callback(self, callback):
        self._on_disconnect = callback

    def connect(self):
        """建立 Telnet 连接"""
        try:
            self._tn = telnetlib.Telnet(self.host, self.port, self.timeout)
        except socket.timeout:
            return False, f"连接超时：{self.host}:{self.port}"
        except socket.error as exc:
            return False, f"网络错误：{exc}"
        except Exception as exc:
            return False, f"连接失败：{exc}"

        try:
            # 等待 login 提示
            idx, match, text = self._tn.expect(
                [b"[Ll]ogin:", b"[Uu]sername:", b"[Pp]assword:"],
                timeout=self.timeout
            )
            if idx in (0, 1) and self.username:
                self._tn.write(self.username.encode(self.encoding) + b"\r")
                # 等待 password 提示
                idx2, _, _ = self._tn.expect([b"[Pp]assword:"], timeout=5)
                if idx2 == 0 and self.password:
                    self._tn.write(self.password.encode(self.encoding) + b"\r")
            elif idx == 2 and self.password:
                self._tn.write(self.password.encode(self.encoding) + b"\r")
        except Exception:
            pass  # 某些设备不需要登录

        self.connected = True
        self._running = True
        self._output_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._output_thread.start()
        return True, "连接成功"

    def _receive_loop(self):
        """后台接收数据循环"""
        while self.connected:
            # 暂停机制：_running=False 时等待而非退出
            if not self._running:
                time.sleep(0.05)
                continue
            try:
                data = self._tn.read_very_eager()
                if data:
                    text = data.decode(self.encoding, errors="replace")
                    if self._on_output:
                        self._on_output(text)
                else:
                    time.sleep(0.05)
            except EOFError:
                break
            except Exception:
                break

        was_paused = not self._running
        if not was_paused:
            self.connected = False
            self._running = False
            if self._on_disconnect:
                self._on_disconnect()

    def send_command(self, command, wait_time=None):
        """发送命令"""
        if not (self._tn and self.connected):
            return "" if wait_time is not None else False

        try:
            self._tn.write(command.encode(self.encoding) + b"\r")
            if wait_time is None:
                return True

            # 暂停 receive loop 避免数据竞争
            self._running = False
            time.sleep(0.15)

            deadline = time.time() + max(wait_time, 0)
            chunks = []
            while time.time() < deadline:
                try:
                    data = self._tn.read_very_eager()
                    if data:
                        text = data.decode(self.encoding, errors="replace")
                        if self._on_output:
                            self._on_output(text)
                        chunks.append(text)
                        deadline = time.time() + max(wait_time, 0)
                    else:
                        time.sleep(0.1)
                except EOFError:
                    break
            return "".join(chunks)
        except Exception:
            self.connected = False
            return "" if wait_time is not None else False
        finally:
            self._running = True

    def send_command_paged(self, command, timeout=30):
        """
        发送命令并自动处理分页（--- More --- 等），返回完整输出。
        """
        if not (self._tn and self.connected):
            return ""

        _MORE_PATTERNS = ("--More--", "---- More ----", "--- More ---", " --More-- ")

        self._running = False  # 暂停 receive loop
        try:
            self._tn.write(command.encode(self.encoding) + b"\r")

            deadline = time.time() + timeout
            chunks = []

            while time.time() < deadline:
                try:
                    data = self._tn.read_very_eager()
                    if data:
                        text = data.decode(self.encoding, errors="replace")
                        if self._on_output:
                            self._on_output(text)
                        chunks.append(text)
                        deadline = time.time() + timeout
                    else:
                        time.sleep(0.1)
                except EOFError:
                    break

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
                    try:
                        self._tn.write(b" ")
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
            self._running = True  # 恢复 receive loop

    def send_keys(self, data):
        """发送原始按键"""
        if self._tn and self.connected:
            try:
                if isinstance(data, str):
                    data = data.encode(self.encoding)
                self._tn.write(data)
                return True
            except Exception:
                self.connected = False
                return False
        return False

    def resize(self, cols, rows):
        """Telnet 不支持动态调整窗口大小"""
        pass

    def disconnect(self):
        """断开连接"""
        self._running = False
        self.connected = False
        try:
            if self._tn:
                self._tn.close()
        except Exception:
            pass

    def __del__(self):
        self.disconnect()
