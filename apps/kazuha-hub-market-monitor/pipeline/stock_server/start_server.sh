#!/bin/bash

# 检查Python是否安装
if ! command -v python3 &> /dev/null; then
    echo "错误：Python 3 未安装"
    exit 1
fi

# 检查pip是否安装
if ! command -v pip3 &> /dev/null; then
    echo "错误：pip 3 未安装"
    exit 1
fi

# 创建虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
echo "激活虚拟环境..."
source venv/bin/activate

# 安装依赖
echo "安装依赖..."
pip3 install -r requirements.txt

# 读取运行模式参数，默认为 http（Streamable HTTP模式，MCP协议新标准）
MODE="${1:-http}"

if [ "$MODE" = "sse" ]; then
    # SSE模式：通过HTTP SSE提供服务
    HOST="${MCP_HOST:-0.0.0.0}"
    PORT="${MCP_PORT:-8091}"
    echo "启动股票MCP服务 (SSE模式) - ${HOST}:${PORT}..."
    MCP_TRANSPORT=sse MCP_HOST="$HOST" MCP_PORT="$PORT" python3 stock_mcp_integrated.py
elif [ "$MODE" = "http" ]; then
    # Streamable HTTP模式（推荐）：MCP协议新标准，性能更好
    HOST="${MCP_HOST:-0.0.0.0}"
    PORT="${MCP_PORT:-8091}"
    echo "启动股票MCP服务 (Streamable HTTP模式) - ${HOST}:${PORT}..."
    MCP_TRANSPORT=http MCP_HOST="$HOST" MCP_PORT="$PORT" python3 stock_mcp_integrated.py
elif [ "$MODE" = "stdio" ]; then
    # stdio模式：通过标准输入输出通信，适合本地IDE集成
    echo "启动股票MCP服务 (stdio模式)..."
    python3 stock_mcp_integrated.py
else
    echo "用法: $0 [http|sse|stdio]"
    echo "  http  - Streamable HTTP模式（默认，推荐），端口8091"
    echo "  sse   - SSE模式，端口8091"
    echo "  stdio - stdio模式，通过标准输入输出通信"
    exit 1
fi
