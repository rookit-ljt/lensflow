#!/usr/bin/env bash
# Linux / macOS 打包脚本: 生成干净的部署压缩包 lensflow-deploy.tar.gz

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

OUTPUT_FILE="$PROJECT_ROOT/lensflow-deploy.tar.gz"

echo "📦 正在打包 Lensflow 部署源码包..."

tar -czvf "$OUTPUT_FILE" \
    --exclude='node_modules' \
    --exclude='apps/api/.venv' \
    --exclude='apps/web/.next' \
    --exclude='apps/web/.next-dev' \
    --exclude='apps/web/.next-prod' \
    --exclude='.git' \
    --exclude='*.db' \
    --exclude='apps/api/uploads/*' \
    --exclude='*.log' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='lensflow-deploy.tar.gz' \
    .

echo "=========================================="
echo "✅ 打包完成: $OUTPUT_FILE"
ls -lh "$OUTPUT_FILE"
echo "=========================================="
