"""
ANSI 转义序列解析器
将含 ANSI 颜色/样式的文本转换为 (text, QTextCharFormat) 片段列表
"""
import re
from PySide6.QtGui import QTextCharFormat, QColor, QFont

# Catppuccin Mocha 色板映射 ANSI 16 色
ANSI_COLORS = {
    0: "#1e1e2e",   # Black
    1: "#f38ba8",   # Red
    2: "#a6e3a1",   # Green
    3: "#f9e2af",   # Yellow
    4: "#89b4fa",   # Blue
    5: "#f5c2e7",   # Magenta
    6: "#94e2d5",   # Cyan
    7: "#bac2de",   # White
    # Bright variants
    8: "#585b70",   # Bright Black (gray)
    9: "#f38ba8",   # Bright Red
    10: "#a6e3a1",  # Bright Green
    11: "#f9e2af",  # Bright Yellow
    12: "#89b4fa",  # Bright Blue
    13: "#f5c2e7",  # Bright Magenta
    14: "#94e2d5",  # Bright Cyan
    15: "#a6adc8",  # Bright White
}

DEFAULT_FG = "#cdd6f4"
DEFAULT_BG = "#1e1e2e"

# 256 色映射：16-231 为 6x6x6 色立方体
_256_CUBE_STEPS = [0x00, 0x5f, 0x87, 0xaf, 0xd7, 0xff]

def _256_to_hex(n):
    """将 256 色编号转换为 hex 颜色值"""
    if n < 16:
        return ANSI_COLORS.get(n, DEFAULT_FG)
    if n < 232:
        n -= 16
        r = _256_CUBE_STEPS[n // 36]
        g = _256_CUBE_STEPS[(n % 36) // 6]
        b = _256_CUBE_STEPS[n % 6]
        return f"#{r:02x}{g:02x}{b:02x}"
    if n < 256:
        v = 8 + (n - 232) * 10
        return f"#{v:02x}{v:02x}{v:02x}"
    return DEFAULT_FG


# 匹配 CSI 序列: ESC [ ... (final byte @-~)
_CSI_RE = re.compile(r'\x1b\[([0-9;?]*)[@-~]')


class AnsiParser:
    """状态机 ANSI 解析器，输出 (text, QTextCharFormat) 片段"""

    def __init__(self):
        self._fg = None       # 当前前景色 QColor 或 None(默认)
        self._bg = None       # 当前背景色 QColor 或 None(默认)
        self._bold = False
        self._underline = False
        self._reverse = False

    def _has_style(self):
        """当前是否有任何样式属性"""
        return self._fg is not None or self._bg is not None or self._bold or self._underline or self._reverse

    def _current_format(self):
        """根据当前状态生成 QTextCharFormat，无样式时返回 None"""
        if not self._has_style():
            return None

        fmt = QTextCharFormat()

        fg = self._fg
        bg = self._bg

        if self._reverse:
            fg, bg = bg, fg

        if fg is not None:
            fmt.setForeground(fg)
        if bg is not None:
            fmt.setBackground(bg)

        if self._bold:
            font = fmt.font()
            font.setWeight(QFont.Bold)
            fmt.setFont(font)

        if self._underline:
            fmt.setFontUnderline(True)

        return fmt

    def _apply_sgr(self, params_str):
        """应用 SGR 参数"""
        if not params_str:
            self._reset()
            return

        params = []
        for p in params_str.split(';'):
            try:
                params.append(int(p) if p else 0)
            except ValueError:
                params.append(0)

        i = 0
        while i < len(params):
            code = params[i]

            if code == 0:
                self._reset()
            elif code == 1:
                self._bold = True
            elif code == 2:
                pass  # Dim, ignore
            elif code == 4:
                self._underline = True
            elif code == 7:
                self._reverse = True
            elif code == 22:
                self._bold = False
            elif code == 24:
                self._underline = False
            elif code == 27:
                self._reverse = False
            elif 30 <= code <= 37:
                color_idx = code - 30
                self._fg = QColor(ANSI_COLORS[color_idx])
            elif code == 38:
                # 扩展前景色
                i += 1
                if i < len(params):
                    ext = params[i]
                    if ext == 5 and i + 1 < len(params):
                        # 256 色: 38;5;n
                        i += 1
                        self._fg = QColor(_256_to_hex(params[i]))
                    elif ext == 2 and i + 3 < len(params):
                        # TrueColor: 38;2;r;g;b
                        r, g, b = params[i+1], params[i+2], params[i+3]
                        self._fg = QColor(r, g, b)
                        i += 3
            elif code == 39:
                self._fg = None  # 默认前景色
            elif 40 <= code <= 47:
                color_idx = code - 40
                self._bg = QColor(ANSI_COLORS[color_idx])
            elif code == 48:
                # 扩展背景色
                i += 1
                if i < len(params):
                    ext = params[i]
                    if ext == 5 and i + 1 < len(params):
                        i += 1
                        self._bg = QColor(_256_to_hex(params[i]))
                    elif ext == 2 and i + 3 < len(params):
                        r, g, b = params[i+1], params[i+2], params[i+3]
                        self._bg = QColor(r, g, b)
                        i += 3
            elif code == 49:
                self._bg = None  # 默认背景色
            elif 90 <= code <= 97:
                color_idx = code - 90 + 8  # Bright 系列
                self._fg = QColor(ANSI_COLORS[color_idx])
            elif 100 <= code <= 107:
                color_idx = code - 100 + 8
                self._bg = QColor(ANSI_COLORS[color_idx])

            i += 1

    def _reset(self):
        """重置所有属性为默认值"""
        self._fg = None
        self._bg = None
        self._bold = False
        self._underline = False
        self._reverse = False

    def parse(self, text):
        """
        解析含 ANSI 转义的文本，返回格式化片段列表

        Args:
            text: 含 ANSI 转义序列的原始文本

        Returns:
            list of (str, QTextCharFormat) 元组
        """
        segments = []
        last_end = 0

        for m in _CSI_RE.finditer(text):
            # 转义序列之前的纯文本
            plain = text[last_end:m.start()]
            if plain:
                # 处理回车和退格
                plain = self._process_control_chars(plain)
                if plain:
                    segments.append((plain, self._current_format()))

            # 处理 SGR 序列 (以 'm' 结尾的 CSI)
            cmd_char = m.group(0)[-1]
            if cmd_char == 'm':
                self._apply_sgr(m.group(1))
            # 其他 CSI 序列（光标移动等）直接跳过

            last_end = m.end()

        # 最后一段纯文本
        remaining = text[last_end:]
        if remaining:
            remaining = self._process_control_chars(remaining)
            if remaining:
                segments.append((remaining, self._current_format()))

        return segments

    def _process_control_chars(self, text):
        """处理控制字符：BEL 等。退格和回车保留给缓冲层处理。"""
        result = []
        for ch in text:
            code = ord(ch)
            if code == 0x07:  # BEL - 铃声，忽略
                continue
            if code == 0x7f:  # DEL - 当作退格处理
                result.append('\b')
                continue
            if code < 0x20 and code not in (0x08, 0x0a, 0x0d, 0x09):
                # 其他控制字符忽略，保留 BS(0x08) LF(0x0a) CR(0x0d) TAB(0x09)
                continue
            result.append(ch)
        return ''.join(result)
