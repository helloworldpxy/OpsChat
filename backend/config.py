# -*- coding: utf-8 -*-
"""
配置管理模块
管理应用程序的所有配置项
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict
from dotenv import load_dotenv

load_dotenv(override=False)


class Settings(BaseSettings):
    """应用程序配置类"""

    # 应用基本配置
    app_name: str = "智能运维Agent"
    app_version: str = "1.0.0"
    debug: bool = Field(default=False, description="调试模式")

    # 服务器配置
    host: str = Field(default="0.0.0.0", description="服务器主机地址")
    port: int = Field(default=8000, description="服务器端口")
    cors_origins: str = Field(
        default="*",
        description="CORS允许的源，逗号分隔，例如 http://localhost:3000,https://example.com；* 表示允许所有源（注意：与 allow_credentials=True 不兼容，二者不能同时使用）"
    )

    # 数据库配置
    database_url: str = Field(
        default="sqlite:///./data/audit.db",
        description="数据库连接URL"
    )

    # LLM配置
    llm_api_key: str = Field(
        default="",
        description="大模型API密钥"
    )
    llm_base_url: str = Field(
        default="https://api.deepseek.com",
        description="大模型API基础URL"
    )
    llm_model: str = Field(
        default="deepseek-chat",
        description="大模型名称"
    )
    llm_temperature: float = Field(
        default=0.7,
        description="大模型温度参数"
    )
    llm_max_tokens: int = Field(
        default=4096,
        description="大模型最大token数"
    )

    # 安全配置
    enable_security_guardrail: bool = Field(
        default=True,
        description="启用安全护栏"
    )
    enable_input_sanitizer: bool = Field(
        default=True,
        description="启用输入过滤"
    )
    enable_output_validator: bool = Field(
        default=True,
        description="启用输出校验"
    )
    enable_sandbox: bool = Field(
        default=True,
        description="启用执行沙箱"
    )

    # 会话配置
    max_conversation_history: int = Field(
        default=50,
        description="最大对话历史记录数"
    )
    session_timeout: int = Field(
        default=3600,
        description="会话超时时间(秒)"
    )

    # 日志配置
    log_level: str = Field(
        default="INFO",
        description="日志级别"
    )
    log_file: Optional[str] = Field(
        default="logs/opschat.log",
        description="日志文件路径"
    )

    # 模型配置映射
    model_providers: dict = Field(default_factory=lambda: {
        "deepseek": {
            "name": "DeepSeek",
            "base_url": "https://api.deepseek.com",
            "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
            "description": "deepseek-chat/deepseek-reasoner 将于 2026/07/24 弃用，请使用新模型名"
        },
        "mimo": {
            "name": "小米MiMo",
            "base_url": "https://api.xiaomimimo.com/v1",
            "models": ["mimo-v2.5-pro", "mimo-v2.5"],
            "description": "Token Plan 用户需使用专用 API Key，按量计费与 Token Plan 额度不互通"
        },
        "qwen": {
            "name": "通义千问Qwen",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "models": ["qwen3.7-max", "qwen3.7-plus", "qwen3.6-flash"],
            "description": "阿里云百炼平台，支持千问及三方模型"
        },
        "chatglm": {
            "name": "智谱ChatGLM",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "models": ["GLM-5.1", "GLM-5", "GLM-4.7", "GLM-4.7-Flash"],
            "description": "智谱AI开放平台"
        },
        "kimi": {
            "name": "Kimi (月之暗面)",
            "base_url": "https://api.moonshot.cn/v1",
            "models": ["kimi-k2.6"],
            "description": "月之暗面 Kimi API 平台"
        },
        "wenxin": {
            "name": "百度文心",
            "base_url": "https://qianfan.baidubce.com/v2",
            "models": ["ernie-4.5-8k", "ernie-4.0-8k", "ernie-3.5-8k"],
            "description": "百度千帆大模型平台"
        },
        "custom": {
            "name": "自定义API",
            "base_url": "",
            "models": [],
            "description": "支持任意 OpenAI 兼容 API，手动输入 Base URL 和模型名称"
        }
    })

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        protected_namespaces=("settings_",),
    )


# 全局配置实例
settings = Settings()


def get_settings() -> Settings:
    """获取配置实例"""
    return settings
