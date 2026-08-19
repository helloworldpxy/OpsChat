#!/usr/bin/env python3
"""
智能运维Agent启动脚本
用于启动FastAPI应用服务器
"""

import os
import sys
import uvicorn
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


def main():
    """主启动函数"""
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    reload = os.getenv("RELOAD", "false").lower() == "true"

    print(f"启动智能运维Agent服务...")
    print(f"访问地址: http://localhost:{port}")
    print(f"日志级别: {log_level}")
    print(f"热重载: {reload}")
    print("-" * 50)

    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=reload,
        access_log=True,
    )


if __name__ == "__main__":
    main()
