# -*- coding: utf-8 -*-
"""
日志工具模块
配置和管理应用程序日志
"""

import os
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional

from ..config import settings


def setup_logging(log_level: Optional[str] = None, log_file: Optional[str] = None):
    """
    设置日志配置
    
    Args:
        log_level: 日志级别，默认从配置读取
        log_file: 日志文件路径，默认从配置读取
    """
    level = log_level or settings.log_level
    file_path = log_file or settings.log_file

    # 创建日志目录
    if file_path:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

    # 配置根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 清除现有处理器
    root_logger.handlers.clear()

    # 日志格式
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 文件处理器
    if file_path:
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # 设置第三方库日志级别
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logging.info("日志系统初始化完成")


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的日志器
    
    Args:
        name: 日志器名称
        
    Returns:
        Logger实例
    """
    return logging.getLogger(name)
