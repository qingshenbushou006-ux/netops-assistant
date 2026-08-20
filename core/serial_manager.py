"""
串口连接管理模块
使用 pyserial 实现嵌入式串口终端
"""
import threading
import time

import serial

try:
    from serial.tools import list_ports
except ImportError:
    list_ports = None

FLOW_CONTROL_OPTIONS = {
    "none": {},
    "xonxoff": {"xonxoff": True},
    "rtscts": {"rtscts": True},
    "dsrdtr": {"dsrdtr": True},
}


def get_available_ports():
    """获取系统可用串口列表"""
    if list_ports is None:
        return []
    return [
        {
            "device": p.device,
            "description": p.description,
            "hwid": p.hwid,
        }
        for p in list_ports.comports()
    ]


class SerialConnection:
    """单个串口连接封装"""

    def __init__(self, port, baud_rate=9600, data_bits=8, parity="N",
                 stop_bits=1, flow_control="none", timeout=0.1, encoding="utf-8"):
        self.port = port
        self.baud_rate = baud_rate
        self.data_bits = data_bits
        self.parity = parity
        self.stop_bits = stop_bits
        self.flow_control = (flow_control or "none").lower()
        self.timeout = timeout
        self.encoding = encoding
        self.line_ending = "\r"

        self.serial = None
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
        try:
            params = {
                "port": self.port,
                "baudrate": self.baud_rate,
                "bytesize": self._get_bytesize(),
                "parity": self._get_parity(),
                "stopbits": self._get_stopbits(),
                "timeout": self.timeout,
                "write_timeout": self.timeout,
            }
            params.update(FLOW_CONTROL_OPTIONS.get(self.flow_control, {}))
            self.serial = serial.Serial(**params)
            self.connected = True
            self._running = True
            self._output_thread = threading.Thread(
                target=self._receive_loop, daemon=True
            )
            self._output_thread.start()
            return True, "连接成功"
        except serial.SerialException as e:
            return False, f"串口错误：{e}"
        except ValueError as e:
            return False, f"参数错误：{e}"
        except Exception as e:
            return False, f"未知错误：{e}"

    def _receive_loop(self):
        while self.connected:
            # 暂停机制：_running=False 时等待而非退出
            if not self._running:
                time.sleep(0.05)
                continue
            try:
                if not self.serial or not self.serial.is_open:
                    break
                data = self.serial.read(4096)
                if data:
                    text = data.decode(self.encoding, errors="replace")
                    if self._on_output:
                        self._on_output(text)
                else:
                    time.sleep(0.02)
            except serial.SerialException:
                break
            except Exception:
                break

        was_paused = not self._running
        if not was_paused:
            self.connected = False
            self._running = False
            if self._on_disconnect:
                self._on_disconnect()

    def send_keys(self, data):
        if not (self.serial and self.connected and self.serial.is_open):
            return False
        try:
            payload = data.encode(self.encoding) if isinstance(data, str) else data
            self.serial.write(payload)
            self.serial.flush()
            return True
        except Exception:
            self.connected = False
            return False

    def send_break(self, duration=0.25):
        """发送串口 Break 信号"""
        if not (self.serial and self.connected and self.serial.is_open):
            return False
        try:
            self.serial.send_break(duration)
            return True
        except Exception:
            return False

    def send_command(self, command, wait_time=None):
        payload = f"{command}{self.line_ending}"
        success = self.send_keys(payload)
        if wait_time is None:
            return success
        if not success:
            return ""
        # 暂停 receive loop 避免数据竞争
        self._running = False
        time.sleep(0.15)
        try:
            time.sleep(max(wait_time, 0))
            chunks = []
            while self.serial and self.serial.is_open and self.serial.in_waiting:
                data = self.serial.read(self.serial.in_waiting)
                if not data:
                    break
                text = data.decode(self.encoding, errors="replace")
                if self._on_output:
                    self._on_output(text)
                chunks.append(text)
            return "".join(chunks)
        finally:
            self._running = True

    def send_command_paged(self, command, timeout=30):
        """
        发送命令并自动处理分页（--- More --- 等），返回完整输出。
        暂停 receive loop 避免数据竞争。
        """
        if not (self.serial and self.connected and self.serial.is_open):
            return ""

        _MORE_PATTERNS = ("--More--", "---- More ----", "--- More ---", " --More-- ")

        # 暂停 receive loop
        self._running = False
        try:
            self.serial.write(f"{command}{self.line_ending}".encode(self.encoding))
            self.serial.flush()

            deadline = time.time() + timeout
            chunks = []

            while time.time() < deadline:
                waiting = self.serial.in_waiting
                if waiting:
                    data = self.serial.read(waiting)
                    if not data:
                        break
                    text = data.decode(self.encoding, errors="replace")
                    if self._on_output:
                        self._on_output(text)
                    chunks.append(text)
                    deadline = time.time() + timeout
                else:
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
                    try:
                        self.serial.write(b" ")
                        self.serial.flush()
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
            self._running = True

    def resize(self, cols, rows):
        return None

    def disconnect(self):
        self._running = False
        self.connected = False
        try:
            if self.serial and self.serial.is_open:
                self.serial.close()
        except Exception:
            pass

    def _get_bytesize(self):
        mapping = {
            5: serial.FIVEBITS,
            6: serial.SIXBITS,
            7: serial.SEVENBITS,
            8: serial.EIGHTBITS,
        }
        return mapping.get(int(self.data_bits), serial.EIGHTBITS)

    def _get_parity(self):
        mapping = {
            "N": serial.PARITY_NONE,
            "E": serial.PARITY_EVEN,
            "O": serial.PARITY_ODD,
            "M": serial.PARITY_MARK,
            "S": serial.PARITY_SPACE,
        }
        return mapping.get(str(self.parity).upper(), serial.PARITY_NONE)

    def _get_stopbits(self):
        mapping = {
            1: serial.STOPBITS_ONE,
            2: serial.STOPBITS_TWO,
        }
        return mapping.get(int(self.stop_bits), serial.STOPBITS_ONE)

    def __del__(self):
        self.disconnect()
