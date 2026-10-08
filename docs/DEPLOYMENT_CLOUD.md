# 云端演示部署（M4）

面向 2 vCPU / 2 GB 演示实例的部署说明。目标是稳定演示核心功能：注册登录、笔记与笔记本/标签、
多格式导入、关键词 + 向量混合检索、知识库问答与持久化对话。

> 模型取舍：2 GB 实例默认**用第三方模型（阿里云百炼 DashScope），不启动 Ollama 容器**——
> 嵌入与图片描述都走远程 API，本项目常驻内存从约 1.1 GB 降到约 600 MB，2 GB 可稳定运行、不再 OOM。
> 本地开发仍在 `compose.yaml` 里用 Ollama，互不影响。
> 另：2 GB 实例**不启动 ONLYOFFICE**（`office` profile 保持关闭）。在线编辑 DOCX/XLSX/PDF
> 与旧版 Office 转换将不可用，相关接口返回 503（`api/app/knowledge/m3.py` 已做守卫），其余功能不受影响。
> 若需在线编辑或本地模型，请升级到 4 GB 并加 `--profile office` / 切回 ollama provider。

## 一、服务器需要安装的内容

| 组件 | 说明 |
| --- | --- |
| **Docker Engine 24+ 与 compose 插件** | 唯一硬性依赖；应用、数据库、模型、对象存储、前端全部在容器内 |
| `git`、`curl`、`openssl` | 拉取代码、健康检查、生成密钥 |
| **Caddy**（推荐）或 Nginx | 宿主侧 HTTPS 入口与证书自动续期 |
| 域名 + DNS | 主域名与对象存储子域名各一条 A 记录 |

宿主机**不需要**安装 Python、Node、PostgreSQL、Ollama、MinIO —— 均在容器内运行。

**规格与前置**：
- 2 vCPU / 4 GB 内存或按需开 swap（`sudo fallocate -l 4G /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`）
- 磁盘 ≥ 40 GB（镜像 + Ollama 模型卷约 610 MB + 数据卷）
- 能出网：拉镜像、下载 Ollama 模型、`link-fetch-worker` 抓取网页
- 放行 22（SSH）、80、443

## 二、部署步骤

### 1. 安装 Docker 与 Caddy

```bash
# Docker（官方脚本，Ubuntu/Debian 适用）
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker

# Caddy
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update && sudo apt-get install -y caddy
```

### 2. 获取代码

```bash
git clone <你的仓库地址> /opt/pkm-system
cd /opt/pkm-system
```

> 仓库当前未配置远程（`git remote -v` 为空）。如尚未托管，可直接用 `rsync` 上传，但务必排除
> `node_modules/`、`.venv/`、`.env.local`：
> ```bash
> rsync -av --exclude node_modules --exclude .venv --exclude .env.local --exclude .git \
>   ./ user@服务器:/opt/pkm-system/
> ```

### 3. 配置 DNS

在域名服务商处添加两条 A 记录，均指向服务器公网 IP：

- `pkm.example.com`（主入口）
- `storage.pkm.example.com`（对象存储，用于文件上传/下载的预签名 URL）

### 4. 生成生产环境文件并启动

脚本会生成含随机密钥的 `.env.prod`（权限 600）、构建镜像、执行迁移、启动服务；
传入 `DASHSCOPE_API_KEY` 时使用第三方模型（推荐，内存友好），否则走本地 Ollama（需 ≥4GB）：

```bash
cd /opt/pkm-system
DOMAIN=pkm.example.com STORAGE_DOMAIN=storage.pkm.example.com \
  DASHSCOPE_API_KEY=sk-你的百炼Key ./deploy/deploy.sh
```

脚本等价于以下手动步骤：

```bash
cp .env.prod.example .env.prod   # 或用脚本自动生成，务必填入真实随机值与 DASHSCOPE_API_KEY
chmod 600 .env.prod
docker compose --env-file .env.prod -f compose.yaml -f compose.prod.yaml up -d --build --wait --scale ollama=0
# 本地模型模式则去掉 --scale ollama=0，并追加：
# docker compose --env-file .env.prod -f compose.yaml -f compose.prod.yaml --profile model-setup run --rm model-init
```

### 5. 启动 HTTPS 入口

```bash
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile
sudo editor /etc/caddy/Caddyfile        # 替换其中的域名
sudo systemctl reload caddy
```

### 6. 验证

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.prod.yaml ps
curl -fsS https://pkm.example.com/health/ready
```

浏览器打开 `https://pkm.example.com/` 注册账号，依次验证：新建笔记、上传一个 PDF/PNG、
关键词搜索、配置 DeepSeek Key 后做一次知识库问答。

## 三、关键配置说明

以下三项若保持默认 `localhost` 值，**文件上传/下载会整体失效**（预签名 URL 指向用户自己的电脑）：

| 变量 | 生产值 | 作用 |
| --- | --- | --- |
| `OBJECT_STORAGE_PUBLIC_ENDPOINT` | `https://storage.pkm.example.com` | 上传分块 PUT、下载/预览 GET 的浏览器直连地址 |
| `ONLYOFFICE_PUBLIC_URL` / `ONLYOFFICE_INTERNAL_URL` | 关闭 office 时无需设置 | 在线编辑（本方案不用） |
| `PUBLIC_APP_URL` | 默认 `http://api:8000` 即可 | ONLYOFFICE 回调；本方案不用 |

`compose.prod.yaml` 已为 api 与全部 worker 覆盖 `OBJECT_STORAGE_PUBLIC_ENDPOINT`。
`migrate` 服务只执行 Alembic 迁移、不生成预签名 URL，保持默认值无影响。

模型 provider（生产第三方 / 本地 Ollama 二选一，由 `.env.prod` 控制）：

| 变量 | 第三方（默认） | 本地 Ollama |
| --- | --- | --- |
| `EMBEDDING_PROVIDER` / `VISION_PROVIDER` | `openai` | `ollama` |
| `EMBEDDING_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 留空 |
| `EMBEDDING_MODEL` | `text-embedding-v3`（1024 维，与库表匹配） | `qwen3-embedding:0.6b` |
| `EMBEDDING_API_KEY` | 百炼 Key | 留空 |
| `VISION_MODEL` | `qwen-vl-plus` | `qwen3-vl:2b-instruct` |

第三方模式下 `EMBEDDING_API_KEY`/`VISION_API_KEY` 缺省复用 `DASHSCOPE_API_KEY`。
切换 provider 只需改 `.env.prod` 后 `$C up -d`；向量维度同为 1024，无需改表或重建索引。

`web/nginx.conf` 在容器内把 `/v1`、`/health/*`、`/docs`、`/openapi.json` 反代到 `api:8000`，
保持浏览器同源（前端使用 `credentials: 'same-origin'`）。其中 `/v1/` 关闭了代理缓冲，
确保 AI 对话的 SSE 流式响应逐块下发。

## 四、运维

### 常用命令

```bash
cd /opt/pkm-system
C="docker compose --env-file .env.prod -f compose.yaml -f compose.prod.yaml"
$C ps
$C logs --tail=100 api worker
$C restart api
$C down            # 保留数据卷
```

### 更新部署

```bash
cd /opt/pkm-system && git pull
$C up -d --build --wait   # 迁移随 api 依赖自动执行
```

### 数据备份

三份持久化卷必须备份，缺失即不可恢复：

- `postgres_data` —— 账号、笔记、向量
- `minio_data` —— M3 文件原件与版本
- `.env.prod` —— **含 `PKM_CREDENTIAL_KEY`，丢失将导致已保存的模型 API Key 无法解密**

```bash
# 数据库逻辑备份
$C exec -T db pg_dump -U pkm pkm | gzip > backup/pkm-$(date +%F).sql.gz
# 卷打包（停机窗口内执行更安全）
docker run --rm -v pkm-system_minio_data:/data -v "$PWD/backup":/out alpine \
  tar czf /out/minio-$(date +%F).tar.gz -C /data .
cp .env.prod backup/env.prod.$(date +%F)
```

### 开机自启（可选）

```bash
sudo cp deploy/pkm-compose.service /etc/systemd/system/
sudo editor /etc/systemd/system/pkm-compose.service   # 核对路径
sudo systemctl daemon-reload && sudo systemctl enable --now pkm-compose
```

## 五、故障排查

| 现象 | 排查 |
| --- | --- |
| 容器反复重启 / 被 killed | 内存不足。`docker stats`、`dmesg \| grep -i oom`；减并发或加 swap/升配 |
| 上传成功但下载/预览 404 或连不上 | `OBJECT_STORAGE_PUBLIC_ENDPOINT` 或 `storage` 子域名 DNS/证书有问题 |
| 预签名上传报 403 | 预签名 URL 的签名包含 Host，Caddy 必须原样透传 `Host`（示例配置已设置） |
| AI 对话不流式、一次性出现 | 反代开启了缓冲；确认 `web/nginx.conf` 的 `/v1/` 有 `proxy_buffering off` |
| `/health/ready` 不通过 | `$C logs api`；确认 `migrate` 已成功完成 |
| 模型未就绪 | 重跑 `--profile model-setup run --rm model-init`，再执行 `app.ops.probe` |
