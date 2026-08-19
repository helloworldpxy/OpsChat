#!/bin/bash
set -e
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'
VENV_DIR='.opschat-env'

echo ""
echo "============================================================"
echo "  智能运维Agent (OpsChat)"
echo "============================================================"
echo ""

# ---- 检测 Python ----
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        major=$("$cmd" -c "import sys;print(sys.version_info.major)" 2>/dev/null)
        minor=$("$cmd" -c "import sys;print(sys.version_info.minor)" 2>/dev/null)
        if [ "$major" -eq 3 ] && [ "$minor" -ge 10 ] && [ "$minor" -le 12 ]; then
            PYTHON_CMD="$cmd"
            echo -e "${GREEN}[OK]${NC} 找到 $("$cmd" --version 2>&1)"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${YELLOW}[ERROR]${NC} 需要 Python 3.10~3.12，未找到兼容版本"
    echo -e "${YELLOW}[HINT]${NC} Ubuntu/Debian: sudo apt install python3.10"
    echo -e "${YELLOW}[HINT]${NC} CentOS/RHEL: sudo yum install python3.10"
    exit 1
fi

# ---- 创建/复用虚拟环境 ----
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${BLUE}[INFO]${NC} 正在创建虚拟环境..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    echo -e "${GREEN}[OK]${NC} 虚拟环境创建成功"
else
    echo -e "${YELLOW}[WARN]${NC} 检测到已有虚拟环境，直接复用"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q

# ---- 安装依赖（三级回退） ----
echo -e "${BLUE}[INFO]${NC} 正在安装项目依赖..."

install_deps() {
    # 第1优先: 本地 wheels（无需网络）
    if [ -d "wheels" ] && [ "$(ls wheels/*.whl 2>/dev/null | wc -l)" -gt 0 ]; then
        echo -e "  ${BLUE}[INFO]${NC} 尝试使用本地 wheels..."
        if pip install --no-index --find-links=wheels -r requirements.txt; then
            return 0
        fi
        echo -e "  ${YELLOW}[WARN]${NC} 本地 wheels 不完整，尝试在线安装..."
    fi

    # 第2优先: 默认 PyPI 源
    if pip install -r requirements.txt 2>/dev/null; then
        return 0
    fi

    # 第3优先: 清华镜像源
    echo -e "  ${YELLOW}[WARN]${NC} 默认源失败，切换清华镜像..."
    if pip install -r requirements.txt \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --trusted-host pypi.tuna.tsinghua.edu.cn 2>/dev/null; then
        return 0
    fi

    return 1
}

if install_deps; then
    echo -e "${GREEN}[OK]${NC} 依赖安装完成"
else
    echo -e "${YELLOW}[ERROR]${NC} 依赖安装失败，可能原因："
    echo -e "  1. 网络连接问题 - 请检查网络后重试"
    echo -e "  2. Python版本不兼容 - 建议使用 Python 3.10 或 3.11"
    echo -e "  3. 系统缺少编译工具 - 请安装 gcc/make 等"
    exit 1
fi

# ---- 初始化配置 ----
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "${GREEN}[OK]${NC} 配置文件已初始化"
fi
mkdir -p data logs

# ---- 启动前检查 ----
echo -e "${BLUE}[INFO]${NC} 检查关键依赖..."
if ! python -c "import fastapi, uvicorn, openai, sqlalchemy, psutil" 2>/dev/null; then
    echo -e "${YELLOW}[ERROR]${NC} 关键依赖缺失，请检查上方安装日志"
    exit 1
fi
echo -e "${GREEN}[OK]${NC} 关键依赖检查通过"

# ---- 启动 ----
echo ""
echo "============================================================"
echo -e "  ${GREEN}安装完成，正在启动服务...${NC}"
echo "============================================================"
echo ""
echo "  访问地址: http://localhost:8000"
echo "  首次使用请在浏览器「设置」页面配置 API Key"
echo "  按 Ctrl+C 停止服务"
echo "============================================================"
echo ""

python run.py
