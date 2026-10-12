# Lensflow 服务器轻量单机部署指南 (Linux)

本文档面向 Linux (Ubuntu / Debian / CentOS / Rocky 等主流系统) 服务器的轻量单机部署方案。  
采用 **SQLite 数据库 + Celery Eager 模式**，无需启动 PostgreSQL 或 RabbitMQ，资源占用极小，512MB~1GB 内存即可流畅运行。

---

## 目录
- [一、准备工作](#一准备工作)
- [二、本地一键打包](#二本地一键打包)
- [三、上传到服务器](#三上传到服务器)
- [四、服务器一键安装与启动](#四服务器一键安装与启动)
- [五、配置 Nginx 反向代理 (强烈推荐)](#五配置-nginx-反向代理-强烈推荐)
- [六、常用运维与管理命令](#六常用运维与管理命令)
- [七、常见问题排查](#七常见问题排查)

---

## 一、准备工作

在你的 Linux 服务器上确认：
1. 服务器具备公网 IP，安全组/防火墙已放行对应端口：
   - 如果使用 Nginx 反向代理：放行 **80** 和 **443** 端口。
   - 如果直接访问端口：放行 **3000**（前端）和 **8000**（后端 API）。
2. 服务器能够访问外网拉取 npm / python 依赖包。

---

## 二、本地一键打包

本地已经为你生成好打包脚本，可直接生成去除临时缓存的轻量压缩包（约 0.6 MB）：

- **Windows 用户**（在项目根目录 PowerShell 运行）：
  ```powershell
  powershell -File scripts/pack.ps1
  ```
- **macOS / Linux 用户**（在项目根目录终端运行）：
  ```bash
  chmod +x scripts/pack.sh
  ./scripts/pack.sh
  ```

执行后将在项目根目录下生成 **`lensflow-deploy.tar.gz`**。

---

## 三、上传到服务器

将生成的压缩包上传至你的 Linux 服务器目标目录（例如 `/var/www/`）：

```bash
# 请将 your-server-ip 替换为你的服务器 IP
scp lensflow-deploy.tar.gz root@your-server-ip:/var/www/
```

登录服务器并解压：
```bash
ssh root@your-server-ip

# 创建目录并解压
mkdir -p /var/www/lensflow
tar -xzvf /var/www/lensflow-deploy.tar.gz -C /var/www/lensflow
cd /var/www/lensflow
```

---

## 四、服务器一键安装与启动

项目内置了自动化安装启动脚本 `scripts/deploy-linux.sh`：

```bash
# 赋予执行权限并执行一键部署
chmod +x scripts/deploy-linux.sh
./scripts/deploy-linux.sh
```

该脚本将自动执行以下操作：
1. 检测并安装 Node.js 22、pnpm、PM2；
2. 安装轻量 Python 管理器 `uv` 并初始化 Python 3.12 虚拟环境；
3. 安装前后端依赖并编译前端生产版本；
4. 生成并配置 `.env` 环境变量；
5. 使用 PM2 启动前端（3000 端口）与后端（8000 端口）守护进程，支持异常自动重启。

---

## 五、配置 Nginx 反向代理 (强烈推荐)

配置 Nginx 可以将前端页面与后端 API 统一在 80/443 端口，解决跨域与浏览器 SSE 流式传输缓冲问题。

### 1. 安装 Nginx
- **Ubuntu / Debian**:
  ```bash
  sudo apt-get update
  sudo apt-get install -y nginx
  ```
- **CentOS / RHEL**:
  ```bash
  sudo dnf install -y nginx
  sudo systemctl enable --now nginx
  ```

### 2. 写入 Nginx 站点配置
将项目中的 `scripts/nginx.conf` 复制到 Nginx 配置目录：
```bash
sudo cp scripts/nginx.conf /etc/nginx/conf.d/lensflow.conf
```
编辑配置文件，将 `YOUR_DOMAIN_OR_SERVER_IP` 改为你的服务器 IP 或域名：
```bash
sudo nano /etc/nginx/conf.d/lensflow.conf
# 或使用 vim: sudo vim /etc/nginx/conf.d/lensflow.conf
```

### 3. 测试并重载 Nginx
```bash
sudo nginx -t
sudo systemctl reload nginx
```

此时打开浏览器，访问 `http://你的服务器IP` 即可直接进入 Lensflow 创作平台！

---

## 六、常用运维与管理命令

通过 PM2 管理服务进程（随时查看状态与日志）：

| 操作 | 命令 |
| :--- | :--- |
| **查看服务运行状态** | `pm2 status` |
| **查看实时日志** | `pm2 logs` （或分别查看 `pm2 logs lensflow-api` / `pm2 logs lensflow-web`） |
| **重启全部服务** | `pm2 restart all` |
| **停止全部服务** | `pm2 stop all` |
| **设置开机自启** | `pm2 startup`（根据终端提示复制执行一行命令，然后执行 `pm2 save`） |

### 修改 API Key / 模型配置
如需更换 API Key 或调整模型，直接修改 `/var/www/lensflow/.env`：
```bash
nano /var/www/lensflow/.env
```
修改后重启后端服务：
```bash
pm2 restart lensflow-api
```

---

## 七、常见问题排查

1. **浏览器打不开网页？**
   - 检查服务器防火墙及云厂商（阿里云/腾讯云/华为云/AWS）安全组是否放行了 80 端口（以及 3000、8000 端口）。
2. **Agent 对话或流式卡住无响应？**
   - 检查 Nginx 配置中的 `proxy_buffering off;` 是否已配置（SSE 流式传输严禁启用代理缓存）。
3. **查看错误日志**：
   - 前端日志：`pm2 logs lensflow-web`
   - 后端日志：`pm2 logs lensflow-api`
   - Nginx 日志：`/var/log/nginx/error.log`
