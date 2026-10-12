#!/usr/bin/env bash
# ==============================================================================
# Lensflow - 宝塔面板 (BT-Panel) 专属一键初始化与部署脚本
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "=========================================="
echo "🏰 正在宝塔面板环境中部署 Lensflow..."
echo "📂 项目路径: $PROJECT_ROOT"
echo "=========================================="

# 1. 检查 Node.js 与 pnpm
echo "▶ 步骤 1/4: 检查 Node.js 与 pnpm/PM2..."
if ! command -v node &> /dev/null; then
    echo "未检测到 Node.js，正在尝试安装 Node.js 22 LTS..."
    if command -v apt-get &> /dev/null; then
        curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
        sudo apt-get install -y nodejs
    elif command -v dnf &> /dev/null; then
        curl -fsSL https://rpm.nodesource.com/setup_22.x | sudo bash -
        sudo dnf install -y nodejs
    else
        echo "❌ 请在宝塔面板【软件商店】安装【Node.js版本管理器】，并安装 Node v20 或 v22！"
        exit 1
    fi
fi
echo "✓ Node.js: $(node -v)"

# 安装 pnpm 和 pm2
if ! command -v pnpm &> /dev/null; then
    npm install -g pnpm pm2
fi
if ! command -v pm2 &> /dev/null; then
    npm install -g pm2
fi
echo "✓ pnpm: $(pnpm -v)"
echo "✓ PM2: $(pm2 -v)"

# 2. 安装 uv (用于隔离管理 Python 3.12 虚拟环境，不污染宝塔系统 Python)
echo "▶ 步骤 2/4: 安装轻量 Python 管理器 uv..."
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
echo "✓ uv: $(uv --version)"

# 3. 编译构建
echo "▶ 步骤 3/4: 安装依赖并构建项目..."
pnpm approve-builds --all || true
pnpm install

# 确保所有 node_modules/.bin 下的可执行脚本具有执行权限
echo "正在修复可执行文件权限..."
chmod -R 755 "$PROJECT_ROOT"
find "$PROJECT_ROOT" -type d -name ".bin" -exec chmod -R +x {} + 2>/dev/null || true

NEXT_PUBLIC_API_URL="" pnpm build

# 配置后端 Python 3.12 虚拟环境
echo "创建独立 Python 3.12 虚拟环境..."
chmod -R 755 "$HOME/.local" 2>/dev/null || true
find "$HOME/.local/share/uv" -type f -name "python*" -exec chmod +x {} + 2>/dev/null || true
uv venv --python 3.12 apps/api/.venv
chmod -R 755 apps/api/.venv
find apps/api/.venv -type d -name "bin" -exec chmod -R +x {} + 2>/dev/null || true
uv pip install --python apps/api/.venv -e "apps/api[dev]"
find apps/api/.venv -type d -name "bin" -exec chmod -R +x {} + 2>/dev/null || true

# 4. PM2 守护启动
echo "▶ 步骤 4/4: 使用 PM2 启动服务..."
pm2 restart ecosystem.config.cjs --update-env || pm2 start ecosystem.config.cjs
pm2 save

echo ""
echo "=========================================="
echo "🎉 宝塔服务部署成功！进程状态如下："
echo "=========================================="
pm2 status
echo ""
echo "👉 本地前端服务: http://127.0.0.1:3000"
echo "👉 本地后端服务: http://127.0.0.1:8000"
echo ""
echo "👉 下一步：在宝塔面板【网站】中添加反向代理，即可绑定域名或通过 80 端口访问！"
