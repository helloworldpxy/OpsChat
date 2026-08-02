# 智能运维Agent (OpsChat)

一个基于大模型的安全智能运维 Agent 系统，通过 B/S 架构提供自然语言交互界面，让运维人员能够通过自然语言与操作系统交互，实现智能运维。适配通用 Linux 发行版，原生支持 LoongArch 等国产架构，Windows 下可运行（部分功能不支持）。

## 项目简介

本项目通过 B/S 架构提供自然语言交互界面，让运维人员能够通过自然语言与操作系统交互，实现智能运维。

### 核心特性

- **智能运维Agent**：基于大模型的自然语言交互，支持流式输出和Markdown渲染
- **智能根因分析**：一键系统诊断，自动检测异常并分析根本原因，给出修复建议
- **三层安全护栏**：Prompt注入防御(38条) → 工具调用校验(11条规则+LLM输出校验) → 执行沙箱
- **MCP插件化**：24个标准化运维工具，覆盖系统/网络/进程/服务/文件/诊断，包含lsof/netstat/dmesg/iostat原生命令
- **配置漂移检测**：监控关键配置文件变更，建立基线对比
- **完整GUI界面**：现代化Web界面，支持多对话管理、设置、监控、审计日志
- **API配置灵活**：预置DeepSeek、MiMo、Qwen、GLM、Kimi等主流大模型
- **思维链审计**：完整的推理过程记录和可视化追溯
- **B/S架构**：浏览器访问，无需安装客户端
- **国产架构原生支持**：适配 LoongArch（龙芯）等国产 CPU 架构

## 技术架构

```
┌─────────────────────────────────────────────┐
│           B/S 前端 (对话 + 审计面板)          │
├─────────────────────────────────────────────┤
│        Agent 核心层 (调度 + 思维链管理)        │
├──────────┬──────────────┬───────────────────┤
│ 意图解析层 │  安全护栏层   │   执行引擎层       │
│ (NLU)    │ (过滤/校验)   │ (MCP Tools/插件)  │
├──────────┴──────────────┴───────────────────┤
│           OS 底层 (Linux)                    │
└─────────────────────────────────────────────┘
```

## 技术栈

| 组件 | 技术方案 |
|------|----------|
| 后端框架 | Python + FastAPI |
| 前端 | HTML/CSS/JavaScript + Jinja2 |
| 大模型 | DeepSeek / Qwen 等 (OpenAI兼容API) |
| 数据库 | SQLite + SQLAlchemy |
| 部署 | Docker |

## 平台支持

| 平台 | 支持程度 |
|------|----------|
| Linux（x86_64 / LoongArch / ARM） | 全功能 |
| Windows | 完整 GUI、对话、psutil 类信息工具可用；`lsof`/`netstat`/`dmesg`/`iostat` 原生命令及 `systemctl` 服务管理不可用（会返回友好提示） |

## 快速开始

### 环境要求

- Python 3.10+ (推荐 3.10)
- Conda (Miniconda 或 Anaconda)
- Docker (可选，用于容器化部署)

### Conda 环境创建指南

本项目使用 Conda 管理 Python 环境，确保跨平台兼容性（x86_64、LoongArch 等）。

#### 1. 安装 Conda

如果尚未安装 Conda，请先安装 Miniconda：

```bash
# Linux
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh

# Windows
# 下载安装器: https://docs.conda.io/en/latest/miniconda.html

# macOS
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh
bash Miniconda3-latest-MacOSX-x86_64.sh
```

#### 2. 创建项目环境

```bash
# 进入项目目录
cd opschat

# 使用 environment.yml 创建环境（推荐）
conda env create -f environment.yml

# 或者手动创建环境
conda create -n opschat python=3.10 -y
conda activate opschat
pip install -r requirements.txt
```

#### 3. 激活环境

```bash
conda activate opschat
```

#### 4. 验证环境

```bash
# 检查 Python 版本
python --version

# 检查关键依赖
python -c "import fastapi; import openai; import sqlalchemy; print('依赖检查通过')"
```

#### 5. 配置环境变量

```bash
# 复制示例配置
cp .env.example .env

# 编辑 .env 文件，配置 LLM API Key
# Windows: notepad .env
# Linux: vim .env
```

#### 6. 启动项目

```bash
python run.py
```

启动后访问 http://localhost:8000

### Conda 环境管理常用命令

```bash
# 查看所有环境
conda env list

# 激活环境
conda activate opschat

# 退出环境
conda deactivate

# 更新环境（当 environment.yml 变更时）
conda env update -f environment.yml --prune

# 删除环境
conda remove -n opschat --all

# 导出当前环境（用于分享）
conda env export > environment.yml
```

### LoongArch（龙芯）平台说明

在 LoongArch 平台上，部分 Python 包可能没有预编译的 wheel，需要从源码编译。建议使用龙芯官方 Python 仓库：

```bash
# 配置龙芯 Python 仓库
wget https://cloud.loongnix.cn/releases/loongarch64/python/set-pip.sh
chmod +x set-pip.sh
./set-pip.sh

# 然后正常创建 Conda 环境
conda env create -f environment.yml
```

### Docker 部署

```bash
# 构建镜像
docker build -t opschat .

# 运行容器
docker run -d -p 8000:8000 --env-file .env opschat

# 或使用 docker-compose
docker-compose up -d
```

## 项目结构

```
opschat/
├── backend/                     # 后端Python项目
│   ├── __init__.py
│   ├── main.py                  # FastAPI应用入口
│   ├── config.py                # 配置管理
│   ├── database.py              # 数据库配置
│   ├── api/                     # API路由
│   │   ├── chat.py              # 对话接口（含多对话管理）
│   │   ├── tools.py             # 工具管理
│   │   ├── audit.py             # 审计日志
│   │   ├── settings.py          # 设置接口
│   │   └── models.py            # 模型列表
│   ├── core/                    # 核心模块
│   │   ├── agent.py             # Agent调度器
│   │   ├── llm_client.py        # 大模型调用
│   │   ├── chain_of_thought.py  # 思维链管理
│   │   └── root_cause.py        # 智能根因分析
│   ├── mcp/                     # MCP协议
│   │   ├── protocol.py          # 协议核心
│   │   ├── registry.py          # 工具注册
│   │   └── tools/               # 工具实现
│   │       ├── system.py        # 系统工具
│   │       ├── network.py       # 网络工具
│   │       ├── process.py       # 进程工具
│   │       ├── service.py       # 服务工具
│   │       ├── file.py          # 文件操作+配置漂移检测
│   │       └── native.py        # 原生命令(lsof/netstat/dmesg/iostat)
│   ├── security/                # 安全模块（9条规则）
│   │   ├── guardrail.py         # 安全护栏
│   │   ├── input_sanitizer.py   # 输入过滤
│   │   ├── output_validator.py  # 输出校验
│   │   └── sandbox.py           # 执行沙箱
│   ├── models/                  # 数据模型
│   ├── utils/                   # 工具函数
│   └── templates/               # 前端模板
├── static/                      # 静态资源
├── tests/                       # 测试代码
├── docs/                        # 文档
├── environment.yml              # Conda环境配置
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## API接口

### 对话接口

```http
POST /api/chat
Content-Type: application/json

{
  "message": "帮我查看磁盘使用情况"
}
```

### 设置接口

```http
# 获取当前设置
GET /api/settings

# 保存API配置
POST /api/settings/api
Content-Type: application/json

{
  "provider": "deepseek",
  "api_key": "sk-xxx",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-v4-flash"
}

# 获取可用模型列表
GET /api/models

# 测试API连接
POST /api/settings/test-connection
```

### 工具列表

```http
GET /api/tools
```

### 审计日志

```http
GET /api/audit/logs
```

## 功能特性

### 1. 完整GUI界面

- **对话页面**：智能运维对话界面，支持流式输出和Markdown渲染
- **设置页面**：用户可自行配置API和系统参数
  - 预置主流大模型厂商（DeepSeek、MiMo、Qwen、ChatGLM、文心等）
  - 支持自定义API地址
  - API Key安全存储
  - 测试连接功能
- **审计日志页面**：可视化思维链推理过程
- **系统监控页面**：实时查看系统状态

### 2. 智能运维对话

- 支持自然语言输入
- 流式输出（SSE）实时显示
- 支持Markdown渲染
- 对话历史管理

### 3. 安全护栏

- **第一层**：Prompt注入防御
- **第二层**：LLM输出意图校验
- **第三层**：执行沙箱/最小权限

### 4. MCP工具（24个）

| 类别 | 工具 | 风险等级 |
|------|------|----------|
| 系统感知 | `get_system_info`, `get_cpu_usage`, `get_memory_usage`, `get_disk_usage` | 低 |
| 原生命令 | `lsof_ports`(端口占用), `dmesg_kernel_log`(内核日志), `iostat_disk_io`(磁盘IO) | 低 |
| 网络感知 | `get_network_status`, `get_network_connections`, `netstat_connections`, `ping_host` | 低 |
| 进程管理 | `get_process_list`, `get_process_detail`, `detect_zombies`, `kill_process` | 低/高 |
| 服务管理 | `list_services`, `get_service_status`, `restart_service`, `stop_service`, `get_system_logs` | 低/中 |
| 文件操作 | `delete_file`, `chmod`, `config_drift_check` | 低/高 |
| 智能诊断 | `diagnose_system`（一键健康诊断+根因分析） | 低 |

### 5. 智能根因分析

自动执行全面系统诊断，包含：
- **异常检测**：CPU/内存/磁盘/进程/日志/网络六维度检测
- **关联分析**：CPU高→哪个进程导致→是否异常
- **根因推断**：OOM事件→内存泄漏→具体进程
- **健康评分**：0-100分系统健康度评估
- **修复建议**：针对性的操作建议

### 6. 审计日志

完整的思维链记录，包括：
- 用户输入
- 环境感知
- LLM推理
- 安全检查
- 执行结果

## 部署（Linux）

### 通用 Linux 部署

1. 安装 Python 3.10+ 与 Docker（可选）
2. 创建虚拟环境并安装依赖
3. 配置 `.env`
4. 启动服务
5. 通过浏览器访问

### Docker镜像仓库配置

如需加速或使用私有镜像仓库，可配置 registry-mirrors。

### 部署步骤

1. 安装Docker
2. 构建或拉取镜像
3. 运行容器
4. 通过浏览器访问

## 开发指南

### 添加新的MCP工具

1. 在 `backend/mcp/tools/` 下创建新文件
2. 继承 `ToolExecutor` 类
3. 实现 `execute` 方法
4. 在 `registry.py` 中注册工具

```python
from backend.mcp.protocol import ToolExecutor, ToolDefinition, RiskLevel

class MyTool(ToolExecutor):
    async def execute(self, **kwargs) -> dict:
        # 实现工具逻辑
        return {"success": True, "result": "..."}
```

### 配置安全规则

在 `backend/security/output_validator.py` 中添加新的安全规则：

```python
def _rule_my_custom_rule(self, tool_name, parameters, current_user):
    # 自定义规则逻辑
    if some_condition:
        return ValidationResult(
            is_valid=False,
            message="拒绝原因",
            risk_level=RiskLevel.HIGH.value
        )
    return ValidationResult(is_valid=True, message="通过")
```

## 测试

```bash
# 运行所有测试
pytest tests/

# 运行特定测试
pytest tests/test_security.py

# 生成覆盖率报告
pytest --cov=backend tests/
```

## 文档

- [需求分析文档](docs/1-需求分析文档.md)
- [功能设计文档](docs/2-功能设计文档.md)
- [产品说明书](docs/3-产品说明书.md)
- [测试报告](docs/4-测试报告.md)
- [性能测试报告](docs/5-性能测试报告.md)
- [部署文档](docs/6-部署文档.md)

## 安全提醒

> ⚠️ **重要**：本系统包含 `kill_process`、`restart_service`、`delete_file`、`chmod` 等高危运维工具，可对主机执行修改性操作。
> 请仅在内网或受信任环境中部署使用，切勿直接暴露在公网。如确需公网访问，请自行在前置网关增加身份认证与访问控制。

## 许可证

本项目采用 [PolyForm Noncommercial License 1.0.0](./LICENSE)。

**使用限制**：
- 允许非商业用途：个人研究、教育、公益组织、非营利性机构、政府机构等
- **禁止商业用途**：任何直接或间接以盈利为目的的使用、分发、集成均不允许
- **未授权禁止用于比赛**：未经作者书面授权，不得将本项目用于任何形式的竞赛、比赛或评比活动

如需商业授权或比赛授权，请联系作者。
