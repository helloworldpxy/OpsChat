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
    app_version: str = "1.2.0"
    debug: bool = Field(default=False, description="调试模式")

    # 服务器配置
    host: str = Field(default="127.0.0.1", description="服务器主机地址（默认仅本机访问；内网/公网部署请显式设为 0.0.0.0 并开启认证）")
    port: int = Field(default=8000, description="服务器端口")
    cors_origins: str = Field(
        default="http://localhost:8000,http://127.0.0.1:8000",
        description="CORS允许的源，逗号分隔；默认仅允许本机访问（前端由本服务同源提供，无需跨域）。如需放行其它来源，在 .env 中配置 CORS_ORIGINS 或用 * 表示全部（注意：与 allow_credentials=True 不兼容）"
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

    # 权限审批配置
    enable_permission_service: bool = Field(
        default=True,
        description="启用权限审批服务"
    )
    permission_ask_timeout: int = Field(
        default=300,
        description="审批请求超时时间(秒)，超时自动拒绝"
    )
    sudo_timeout: int = Field(
        default=300,
        description="sudo 密码生效时间(秒)，对应 timestamp_timeout"
    )

    # 上下文窗口配置（用于前端 ContextMeter 占用估算）
    context_window: int = Field(
        default=128000,
        description="模型上下文窗口 token 上限（ContextMeter 的 100% 基准）"
    )

    # 历史裁剪（token 预算 + 工具结果截断）
    history_token_budget_ratio: float = Field(
        default=0.4,
        description="对话历史占上下文窗口的 token 预算比例（超出从最旧消息裁剪）"
    )
    tool_result_max_chars: int = Field(
        default=8000,
        description="工具执行结果写入模型历史的最大字符数（ANSI 清理 + 长行截断）"
    )

    # SSE 心跳
    sse_heartbeat_interval: int = Field(
        default=15,
        description="SSE 心跳间隔(秒)，避免长工具执行期间代理/网关断连"
    )

    # 基础登录认证（可选，默认关闭）
    auth_enabled: bool = Field(
        default=False,
        description="启用基础登录认证（HTTP Basic）"
    )
    auth_username: str = Field(
        default="admin",
        description="认证用户名"
    )
    auth_password: str = Field(
        default="",
        description="认证密码（留空则认证视为未配置，禁用认证）"
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
        "openai": {
            "name": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "models": ["gpt-5", "gpt-5-mini"],
            "description": "OpenAI 官方 API"
        },
        "anthropic": {
            "name": "Anthropic Claude",
            "base_url": "https://api.anthropic.com/v1",
            "models": ["claude-sonnet-4-5", "claude-haiku-4-5"],
            "description": "Anthropic Claude（OpenAI 兼容接口）"
        },
        "gemini": {
            "name": "Google Gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "models": ["gemini-2.5-flash", "gemini-2.5-pro"],
            "description": "Google Gemini（OpenAI 兼容接口）"
        },
        "xai": {
            "name": "xAI Grok",
            "base_url": "https://api.x.ai/v1",
            "models": ["grok-3", "grok-3-mini"],
            "description": "xAI Grok API 平台"
        },
        "mistral": {
            "name": "Mistral",
            "base_url": "https://api.mistral.ai/v1",
            "models": ["mistral-large-latest", "mistral-medium-latest"],
            "description": "Mistral AI 平台"
        },
        "groq": {
            "name": "Groq",
            "base_url": "https://api.groq.com/openai/v1",
            "models": ["llama-3.3-70b-versatile", "qwen3-32b"],
            "description": "Groq 高性能推理云"
        },
        "nvidia": {
            "name": "NVIDIA NIM",
            "base_url": "https://integrate.api.nvidia.com/v1",
            "models": ["deepseek-ai/deepseek-v3.1", "meta/llama-3.3-70b-instruct"],
            "description": "NVIDIA NIM 推理微服务"
        },
        "siliconflow": {
            "name": "硅基流动",
            "base_url": "https://api.siliconflow.cn/v1",
            "models": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen3-235B-A22B", "deepseek-ai/DeepSeek-R1"],
            "description": "SiliconFlow 硅基流动，汇聚开源模型"
        },
        "ollama": {
            "name": "Ollama（本地）",
            "base_url": "http://localhost:11434/v1",
            "models": ["qwen3:32b", "llama3.3:70b", "deepseek-r1:70b"],
            "description": "本地 Ollama，OpenAI 兼容接口"
        },
        "local": {
            "name": "本地 OpenAI 兼容",
            "base_url": "http://localhost:8000/v1",
            "models": [],
            "description": "任意本地 OpenAI 兼容服务（vLLM / LM Studio 等）"
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
