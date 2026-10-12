#!/usr/bin/env bash
# ==============================================================================
# Lensflow - Linux 单机轻量部署与运行脚本 (自用/开发模式)
# 支持环境: Ubuntu, Debian, CentOS, Rocky, AlmaLinux
# ==============================================================================

set -e

# 确保在项目根目录运行
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "=========================================="
echo "🚀 开始部署 Lensflow (AI Video Studio)..."
echo "📂 项目根目录: $PROJECT_ROOT"
echo "=========================================="

# 1. 检查并安装 Node.js 与 pnpm
echo "▶ 步骤 1/5: 检查 Node.js 与 pnpm 环境..."
if ! command -v node &> /dev/null; then
    echo "未检测到 Node.js，正在尝试安装 Node.js 22 LTS..."
    if command -v apt-get &> /dev/null; then
        curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
        sudo apt-get install -y nodejs
    elif command -v dnf &> /dev/null; then
        curl -fsSL https://rpm.nodesource.com/setup_22.x | sudo bash -
        sudo dnf install -y nodejs
    else
        echo "❌ 请手动安装 Node.js >= 20 后重试！"
        exit 1
    fi
fi
echo "✓ Node.js 版本: $(node -v)"

if ! command -v pnpm &> /dev/null; then
    echo "未检测到 pnpm，正在通过 npm 安装..."
    sudo npm install -g pnpm pm2
else
    if ! command -v pm2 &> /dev/null; then
        sudo npm install -g pm2
    fi
fi
echo "✓ pnpm 版本: $(pnpm -v)"
echo "✓ PM2 版本: $(pm2 -v)"

# 2. 检查并安装 Python 3.12 (推荐使用 uv 管理)
echo "▶ 步骤 2/5: 检查 Python 与 uv 工具..."
if ! command -v uv &> /dev/null; then
    echo "正在安装轻量级 Python 包管理器 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v uv &> /dev/null; then
    echo "❌ uv 安装失败，请检查网络或权限！"
    exit 1
fi
echo "✓ uv 版本: $(uv --version)"

# 3. 配置 .env 环境变量
echo "▶ 步骤 3/5: 检查环境配置文件 .env..."
if [ ! -f .env ]; then
    echo "创建默认 .env 文件..."
    cat << 'EOF' > .env
NEXT_PUBLIC_API_URL=
ENVIRONMENT=development
RUNTIME_SETTINGS_ENABLED=true
AUTH_COOKIE_NAME=ai-video-studio_session
AUTH_REQUIRED=false
AUTH_SESSION_DAYS=30
AUTH_COOKIE_SECURE=false
CELERY_TASK_ALWAYS_EAGER=true
DEFAULT_PROVIDER=qwen
TEXT_PROVIDER=qwen
IMAGE_PROVIDER=qwen
AGENT_PROVIDER=qwen
QWEN_API_KEY=""
QWEN_TEXT_BASE_URL="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
QWEN_TEXT_MODEL="qwen-max"
QWEN_IMAGE_BASE_URL="https://dashscope-intl.aliyuncs.com/api/v1"
QWEN_IMAGE_MODEL="qwen-image-plus"
EOF
    echo "⚠️ 已生成基础 .env 文件，请后续填入你的 API Key！"
else
    echo "✓ 已存在 .env 文件，保留现有配置。"
fi

# 4. 构建前端与安装依赖
echo "▶ 步骤 4/5: 安装依赖并执行编译构建..."
pnpm approve-builds --all || true
pnpm install
NEXT_PUBLIC_API_URL="" pnpm build

# 配置后端 Python 3.12 虚拟环境
echo "配置后端 Python 3.12 虚拟环境..."
uv venv --python 3.12 apps/api/.venv
uv pip install --python apps/api/.venv -e "apps/api[dev]"

# 5. 使用 PM2 启动或重启进程
echo "▶ 步骤 5/5: 使用 PM2 守护服务..."
pm2 restart ecosystem.config.cjs --update-env || pm2 start ecosystem.config.cjs
pm2 save

echo ""
echo "=========================================="
echo "🎉 部署完成！服务已在后台运行："
echo "=========================================="
pm2 status
echo ""
echo "👉 前端服务地址: http://127.0.0.1:3000"
echo "👉 后端服务地址: http://127.0.0.1:8000"
echo ""
echo "💡 常用管理命令:"
echo "   查看实时日志: pm2 logs"
echo "   重启服务:     pm2 restart all"
echo "   停止服务:     pm2 stop all"
echo "   开机自启:     pm2 startup (根据提示执行一次即可)"
echo ""
echo "🌐 如需配置 Nginx 反向代理，请参考: scripts/nginx.conf"
