# 云服务器部署说明（inspiration-space.xyz 子域 + 宝塔环境）

面向服务器 `8.163.13.117`（Alibaba Cloud Linux 3 + 宝塔面板 + nginx）。该机同时运行着
`inspiration-space.xyz` 与 MySQL，本方案以**不干扰现有站点**为前提，用独立子域接入本项目。

> 内存说明：本机 1.8 GB。**生产改用第三方模型（百炼 DashScope），不再运行 Ollama 容器**，
> 嵌入与视觉都走远程 API，因此本项目容器常驻内存从约 1.1 GB 降到约 600 MB，2 GB 实例可稳定运行。
> 本地开发仍用仓库内 `compose.yaml` 走 Ollama，与此部署无关。2 GB 实例不启用 ONLYOFFICE（未加 `office` profile）。

## 一、域名与 DNS

前端使用主域名 `inspiration-space.xyz`，对象存储使用子域，A 记录均指向 `8.163.13.117`：

| 地址 | 用途 | DNS |
| --- | --- | --- |
| `inspiration-space.xyz` | 前端入口（浏览器访问） | 已解析 |
| `storage.inspiration-space.xyz` | 对象存储（文件上传/下载的预签名 URL 直连） | 需新增 A 记录 |

> 主域名此前承载的旧应用（Spring Boot + 静态前端）已清理，systemd 服务、目录与 nginx vhost 均已移除，
> 配置备份在 `/root/old-app-backup-*/`。

## 二、已完成的准备工作（镜像与配置已在服务器上）

以下内容已在部署前完成，无需重复：

- `/opt/pkm-system/images/` 下已放置 `pkm-api-prod.tar.gz`、`pkm-web-prod.tar.gz`（均为 **linux/amd64**）
- `/opt/pkm-system/deploy/compose.deploy.yaml` 自包含 Compose（纯镜像，无 build，无源码，**不含 ollama**）
- `/opt/pkm-system/deploy/.env.prod.example` 环境模板
- 依赖镜像：`pgvector/pgvector:0.8.6-pg18`、
  `quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z`（复用本机已有 `minio/minio:latest` retag 得到）

校验镜像：

```bash
docker images | grep -E "pkm-|pgvector|minio"
# pkm-api:prod / pkm-web:prod 应为 amd64，大小约 376MB / 49MB
```

## 三、生成环境文件

```bash
cd /opt/pkm-system/deploy
cp .env.prod.example .env.prod
# 填写下面这些值（其余保持默认）
cat > /tmp/mkenv.sh <<'EOF'
set -e
cd /opt/pkm-system/deploy
POSTGRES_PASSWORD=$(openssl rand -hex 24)
PKM_CREDENTIAL_KEY=$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')
PKM_FILE_LINK_SECRET=$(openssl rand -hex 32)
OBJ_AK=$(openssl rand -hex 16 | tr 'a-f' 'A-F')
OBJ_SK=$(openssl rand -base64 36 | tr -d '\n')
cat > .env.prod <<ENV
APP_ENV=production
ASSISTANT_TRACE_VIEW_ENABLED=false
POSTGRES_USER=pkm
POSTGRES_DB=pkm
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
PKM_CREDENTIAL_KEY=${PKM_CREDENTIAL_KEY}
PKM_FILE_LINK_SECRET=${PKM_FILE_LINK_SECRET}
OBJECT_STORAGE_ACCESS_KEY=${OBJ_AK}
OBJECT_STORAGE_SECRET_KEY=${OBJ_SK}
OBJECT_STORAGE_BUCKET=pkm-files
OBJECT_STORAGE_DOMAIN=storage.inspiration-space.xyz
WEB_HOST_PORT=5173
OBJECT_STORAGE_HOST_PORT=19000

# 模型：第三方 OpenAI 兼容服务（百炼 DashScope）
EMBEDDING_PROVIDER=openai
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_API_KEY=${DASHSCOPE_API_KEY:?先在 https://bailian.console.aliyun.com 申请 API Key}
VISION_PROVIDER=openai
VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VISION_MODEL=qwen-vl-plus
VISION_API_KEY=${DASHSCOPE_API_KEY}
ENV
chmod 600 .env.prod
EOF
bash /tmp/mkenv.sh && echo "已生成 .env.prod" && rm -f /tmp/mkenv.sh
```

> 第三方模式的 API Key 从百炼控制台获取，一个 Key 同时用于嵌入与视觉。
> 若想本地模型（需 ≥4GB 内存），把 `EMBEDDING_PROVIDER`/`VISION_PROVIDER` 改回 `ollama` 并启用 ollama 容器。

> ⚠️ 备份 `.env.prod`。丢失 `PKM_CREDENTIAL_KEY` 会导致已保存的模型 API Key 无法解密。

## 四、加载镜像并启动

```bash
cd /opt/pkm-system
docker load -i images/pkm-api-prod.tar.gz
docker load -i images/pkm-web-prod.tar.gz

cd deploy
C="docker compose --env-file .env.prod -f compose.deploy.yaml"
$C up -d --wait                    # 启动全部服务（不含 ollama / office）
$C exec -T api /app/.venv/bin/python -m app.ops.probe   # 模型自检（会真调一次嵌入接口）
```

第三方模型无需下载，`model-init` 与 ollama 容器均不参与。

此时容器已在运行，宿主机端口映射为：前端 `127.0.0.1:5173`、对象存储 `127.0.0.1:19000`
（仅本机监听，由宝塔 nginx 反代对外）。

## 五、宝塔配置反向代理与 HTTPS

### 1. 添加站点

宝塔面板 → 网站 → 添加站点：
- 域名：`inspiration-space.xyz`
- 根目录：随意（会被反代覆盖）
- 不要勾选 PHP/数据库

### 2. 设置反向代理

在该站点「反向代理」中添加：
- 代理名称：`pkm-app`
- 目标 URL：`http://127.0.0.1:5173`
- 发送域名：`$host`

**关键**：在反向代理的「配置文件」里，为 `/v1/` 路径补上关闭缓冲（否则 AI 对话的流式响应会被卡住）。
可编辑站点 conf，加入：

```nginx
location /v1/ {
    proxy_pass http://127.0.0.1:5173;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
}
```

（或用「配置文件」直接整段替换为仓库中的 `web/nginx.conf` 的 server 段落，把 `listen 5173` 改为 443，
并加上宝塔生成的证书行。）

### 3. 对象存储子域

再添加站点 `storage.inspiration-space.xyz`，反向代理到 `http://127.0.0.1:19000`，
同样设置「发送域名 `$host`」（预签名 URL 的签名包含 Host，必须原样透传）。

### 4. 申请 HTTPS 证书

两个站点分别申请 Let's Encrypt 证书（宝塔一键）或已有证书。**必须 HTTPS**，
否则浏览器会拦截 `https` 页面对 `http` 对象存储的混合内容请求。

## 六、验证

```bash
curl -fsS https://inspiration-space.xyz/health/ready
```

浏览器打开 `https://inspiration-space.xyz/` 注册账号，验证：新建笔记、上传 PDF/PNG、
关键词搜索、配置 DeepSeek Key 后做一次知识库问答。

## 七、内存观察（可选）

第三方模型模式下不再有 Ollama 常驻，内存已很宽裕，简单确认即可：

```bash
free -m; docker stats --no-stream --format "{{.Name}} {{.MemUsage}}"
```

- 本项目容器合计约 600 MB；`available` 应长期高于 800 MB。
- 若仍担心波及现有站点，查看 OOM 记录：`dmesg -T | grep -i "killed process"`。

## 八、日常运维

```bash
cd /opt/pkm-system/deploy
C="docker compose --env-file .env.prod -f compose.deploy.yaml"
$C ps
$C logs --tail=100 api
$C restart api
$C down            # 停止（保留数据卷）
$C up -d           # 再次启动
```

数据备份（三份卷，缺一不可恢复）：

```bash
# 数据库
$C exec -T db pg_dump -U pkm pkm | gzip > /opt/pkm-backup/pkm-$(date +%F).sql.gz
# 对象存储
docker run --rm -v pkm-system_minio_data:/data -v /opt/pkm-backup:/out alpine \
  tar czf /out/minio-$(date +%F).tar.gz -C /data .
# 环境文件
cp .env.prod /opt/pkm-backup/env.prod.$(date +%F)
```

## 九、更新部署

改动代码后，在开发机重新构建 amd64 镜像并上传：

```bash
# 开发机（Apple Silicon 需 --platform linux/amd64）
docker buildx build --platform linux/amd64 -t pkm-api:prod --load ./api
# 契约门禁：构建后、出包前静态校验（响应契约覆盖 / tool 信封 / 归属过滤）。
# 红灯（退出码非 0）表示存在无契约端点或越权查询，禁止出包。
docker run --rm pkm-api:prod /app/.venv/bin/python -m scripts.contract_check --static
docker save pkm-api:prod | gzip -1 > pkm-api-prod.tar.gz
scp pkm-api-prod.tar.gz root@8.163.13.117:/opt/pkm-system/images/
# 服务器
docker load -i images/pkm-api-prod.tar.gz && $C up -d
```
