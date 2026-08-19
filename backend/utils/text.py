# -*- coding: utf-8 -*-
"""
文本处理工具
- ANSI 转义序列清理
- 长行 / 超长文本截断（借鉴 MiMo token-efficient 过滤思路）
"""

import re
from typing import Optional

# ANSI 转义序列：CSI (SGR等) / OSC (title等) / 其他
_ANSI_RE = re.compile(
    r"""
    \x1b\[[0-9;]*[a-zA-Z]        # CSI 序列
    |\x1b\][^\x07\x1b]*(\x07|\x1b\\)  # OSC 序列（如 \x1b]0;title\x07）
    |\x1b[@-_][0-9;]*[a-zA-Z]?   # 其他转义
    |\x1b\\(?:\[[0-9;]*[a-zA-Z])?  # ST
    """,
    re.VERBOSE,
)


def strip_ansi(text: str) -> str:
    """去除文本中的 ANSI 转义序列"""
    if not text:
        return text
    return _ANSI_RE.sub("", text)


def truncate_text(
    text: str,
    max_chars: int = 8000,
    max_line_len: int = 500,
) -> str:
    """
    裁剪文本：先清 ANSI，压缩连续空行，再按行/总量截断

    Args:
        text: 原始文本
        max_chars: 总字符上限
        max_line_len: 单行字符上限（超长行截断并标注长度）

    Returns:
        str: 裁剪后的文本
    """
    if not text:
        return ""
    text = strip_ansi(text)

    lines: list = []
    prev_blank = False
    for line in text.split("\n"):
        is_blank = not line.strip()
        if is_blank:
            if prev_blank:
                continue
            prev_blank = True
        else:
            prev_blank = False

        if len(line) > max_line_len:
            line = line[:max_line_len] + f"...[+{len(line) - max_line_len} chars]"
        lines.append(line)

    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars] + f"\n...[truncated, total {len(text)} chars]"
    return out


def truncate_json(
    obj,
    max_chars: int = 8000,
    max_line_len: int = 500,
) -> str:
    """JSON 序列化后再裁剪（用于工具结果入历史）"""
    import json
    text = json.dumps(obj, ensure_ascii=False, default=str)
    return truncate_text(text, max_chars=max_chars, max_line_len=max_line_len)