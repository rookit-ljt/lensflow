# 宝塔面板 (BT Panel) 部署 Lensflow 保姆级教程

针对使用**宝塔 Linux 面板**的用户，本项目可完全借助宝塔的可视化界面（文件管理、站点管理、SSL申请）与终端轻松完成部署。

---

## 步骤一：上传与解压（宝塔网页端）

1. 打开并登录你的 **宝塔面板**。
2. 进入左侧菜单 **【文件】**，进入目录 `/www/wwwroot/`。
3. 点击顶部的 **【上传】** 按钮，将本地生成的 `lensflow-deploy.tar.gz`（约 0.6MB）上传上来。
4. 上传完成后，找到 `lensflow-deploy.tar.gz`，点击 **【解压】**，解压目录填写 `/www/wwwroot/lensflow`。

---

## 步骤二：一键初始化环境并启动（宝塔终端）

1. 进入宝塔面板左侧菜单 **【终端】**（输入服务器 root 密码登录）。
2. 依次输入以下命令：

```bash
cd /www/wwwroot/lensflow
chmod +x scripts/deploy-bt.sh
./scripts/deploy-bt.sh
```

> **脚本会自动完成**：
> - 自动检查 Node.js 22、pnpm 和 PM2；
> - 自动安装独立的 Python 3.12 (uv)，绝不破坏宝塔现有的系统 Python 环境；
> - 自动安装前后端依赖并完成生产打包；
> - 使用 PM2 在后台启动并守护前端（3000端口）与后端API（8000端口）。

执行完成后，终端会显示 `lensflow-api` 和 `lensflow-web` 为 `online` 状态。

---

## 步骤三：在宝塔中创建站点与配置反向代理

使用宝塔的 Nginx 站点，一键绑定你的域名并实现统一端口访问。

### 1. 新建站点
1. 点击宝塔面板左侧 **【网站】** -> **【添加站点】**。
2. 域名填写你的域名（若无域名可直接填 `服务器IP`）。
3. 根目录选择 `/www/wwwroot/lensflow`，PHP 版本选择 **纯静态**，点击 **确定**。

### 2. 配置反向代理与流式传输 (关键)
在刚创建的站点右侧点击 **【设置】** -> 左侧切换到 **【配置文件】**：

将原有的配置内容替换为以下内容（请将 `your_domain_or_ip` 替换为你的域名或IP）：

```nginx
server
{
    listen 80;
    server_name your_domain_or_ip;
    index index.html index.htm;
    root /www/wwwroot/lensflow;

    # 上传素材大小限制
    client_max_body_size 50M;

    # 1. 后端 API 反向代理 (FastAPI)
    location ~ ^/(api|health|docs|openapi\.json) {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket 支持
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # 支持 Agent 对话流式响应 (SSE)：关闭缓冲
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }

    # 2. 前端页面反向代理 (Next.js)
    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_read_timeout 60s;
    }

    # 日志
    access_log  /www/wwwlogs/lensflow.log;
    error_log  /www/wwwlogs/lensflow.error.log;
}
```
点击 **【保存】**。

---

## 步骤四：防火墙与安全组放行

1. **宝塔面板内**：点击左侧 **【安全】**，检查系统防火墙是否放行了 **80** 和 **443** 端口。
2. **云服务器控制台（阿里云/腾讯云等）**：检查云安全组是否放行了 **80** 和 **443**。

---

## 步骤五：访问与使用

打开浏览器访问你的域名或服务器 IP，即可正常进入 Lensflow！

### 运维与日志查看：
在宝塔终端中运行：
- 查看进程状态：`pm2 status`
- 查看实时日志：`pm2 logs`
- 重启服务：`pm2 restart all`
- 开启开机自启：`pm2 startup && pm2 save`
