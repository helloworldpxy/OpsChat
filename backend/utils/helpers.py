# -*- coding: utf-8 -*-
"""
辅助函数模块
提供常用的工具函数
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional


def generate_trace_id() -> str:
    """
    生成追踪ID
    
    Returns:
        格式: YYYY-MM-DD-XXXX (XXXX为UUID前4位)
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    uuid_short = uuid.uuid4().hex[:8]
    return f"{date_str}-{uuid_short}"


def generate_session_id() -> str:
    """
    生成会话ID
    
    Returns:
        UUID格式的会话ID
    """
    return str(uuid.uuid4())


def format_datetime(dt: Optional[datetime] = None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    格式化日期时间
    
    Args:
        dt: 日期时间对象，默认为当前时间
        fmt: 格式化字符串
        
    Returns:
        格式化后的日期时间字符串
    """
    if dt is None:
        dt = datetime.now()
    return dt.strftime(fmt)


def get_utc_now() -> datetime:
    """获取当前UTC时间"""
    return datetime.now(timezone.utc)


def get_local_now() -> datetime:
    """获取当前本地时间"""
    return datetime.now()


def timedelta_to_str(td: timedelta) -> str:
    """
    将timedelta转换为可读字符串
    
    Args:
        td: timedelta对象
        
    Returns:
        可读的时间差字符串
    """
    total_seconds = int(td.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}秒"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{minutes}分钟"
    elif total_seconds < 86400:
        hours = total_seconds // 3600
        return f"{hours}小时"
    else:
        days = total_seconds // 86400
        return f"{days}天"


def truncate_string(s: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    截断字符串
    
    Args:
        s: 原始字符串
        max_length: 最大长度
        suffix: 截断后缀
        
    Returns:
        截断后的字符串
    """
    if len(s) <= max_length:
        return s
    return s[:max_length - len(suffix)] + suffix


def safe_json_serializable(obj):
    """
    确保对象可以被JSON序列化
    
    Args:
        obj: 待检查的对象
        
    Returns:
        可序列化的对象
    """
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    elif isinstance(obj, (list, tuple)):
        return [safe_json_serializable(item) for item in obj]
    elif isinstance(obj, dict):
        return {str(k): safe_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, datetime):
        return obj.isoformat()
    else:
        return str(obj)
