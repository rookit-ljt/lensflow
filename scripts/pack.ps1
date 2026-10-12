# Windows 打包脚本: 生成干净的部署压缩包 lensflow-deploy.tar.gz
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

$outputFile = Join-Path $projectRoot "lensflow-deploy.tar.gz"

Write-Host "📦 正在打包 Lensflow 部署源码包..." -ForegroundColor Cyan

# 排除模式
$excludeList = @(
    "--exclude=node_modules",
    "--exclude=apps/api/.venv",
    "--exclude=apps/web/.next",
    "--exclude=apps/web/.next-dev",
    "--exclude=apps/web/.next-prod",
    "--exclude=.git",
    "--exclude=*.db",
    "--exclude=apps/api/uploads/*",
    "--exclude=*.log",
    "--exclude=__pycache__",
    "--exclude=*.pyc",
    "--exclude=lensflow-deploy.tar.gz"
)

tar -czvf $outputFile @excludeList .

$fileSize = (Get-Item $outputFile).Length / 1MB
Write-Host "==========================================" -ForegroundColor Green
Write-Host "✅ 打包完成: $outputFile" -ForegroundColor Green
Write-Host "📊 文件大小: $([math]::Round($fileSize, 2)) MB" -ForegroundColor Green
Write-Host "💡 你可以将此压缩包上传至服务器并解压:" -ForegroundColor Yellow
Write-Host "   scp lensflow-deploy.tar.gz user@your-server-ip:/var/www/" -ForegroundColor Yellow
Write-Host "   ssh user@your-server-ip 'mkdir -p /var/www/lensflow && tar -xzvf /var/www/lensflow-deploy.tar.gz -C /var/www/lensflow'" -ForegroundColor Yellow
Write-Host "==========================================" -ForegroundColor Green
