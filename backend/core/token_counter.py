# -*- coding: utf-8 -*-
"""
DeepSeek V3 精确 token 计数
优先使用真实 DeepSeek tokenizer（vendored BPE 词表，tokenizers 库加载）；
加载失败时回退到启发式估算（旧 estimate_tokens 逻辑），保证任何环境可用。
"""

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_TOKENIZER_PATH = Path(__file__).resolve().parent.parent / "vendor" / "deepseek_tokenizer" / "tokenizer.json"

_lock = threading.Lock()
_tokenizer = None  # None=未加载; False=加载失败; 其他=Tokenizer 实例


def _load_tokenizer():
    """惰性加载 DeepSeek V3 tokenizer（线程安全，失败后缓存 False）"""
    global _tokenizer
    if _tokenizer is None:
        with _lock:
            if _tokenizer is None:
                try:
                    from tokenizers import Tokenizer
                    _tokenizer = Tokenizer.from_file(str(_TOKENIZER_PATH))
                    logger.info("DeepSeek V3 tokenizer 加载成功")
                except Exception as e:
                    logger.warning(f"加载 DeepSeek tokenizer 失败，回退启发式估算: {e}")
                    _tokenizer = False
    return _tokenizer if _tokenizer is not False else None


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（回退方案：中文 1 字符≈1 token，其余 4 字符≈1 token）"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return int(cjk + other / 4) + 1


def count_tokens(text: str) -> int:
    """精确计数单个文本的 token 数（真实 DeepSeek tokenizer，失败回退估算）"""
    if not text:
        return 0
    tok = _load_tokenizer()
    if tok is not None:
        try:
            return len(tok.encode(text).ids)
        except Exception as e:
            logger.warning(f"tokenizer 计数失败，回退估算: {e}")
    return estimate_tokens(text)


def count_message_tokens(message: dict) -> int:
    """精确计数单条消息 token 数（content + tool_calls）"""
    total = count_tokens(message.get("content", "") or "")
    tool_calls = message.get("tool_calls")
    if tool_calls:
        total += count_tokens(json.dumps(tool_calls, ensure_ascii=False))
    return total


def count_messages_tokens(messages: list) -> int:
    """精确计数消息列表总 token 数（逐条求和）"""
    return sum(count_message_tokens(m) for m in messages)


def count_json_tokens(obj) -> int:
    """精确计数 JSON 序列化结构的总 token 数"""
    return count_tokens(json.dumps(obj, ensure_ascii=False))