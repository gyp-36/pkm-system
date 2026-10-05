#!/usr/bin/env bash
# 云服务器一键部署脚本（幂等，可重复执行）。
#
# 用法：
#   DOMAIN=pkm.example.com STORAGE_DOMAIN=storage.pkm.example.com ./deploy/deploy.sh
#
# 首次执行会生成含随机密钥的 .env.prod（权限 600）；已存在时复用，不会覆盖。
# 之后构建镜像、执行数据库迁移、启动全部服务，并下载本地模型。
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
ENV_FILE="$ROOT/.env.prod"

DOMAIN="${DOMAIN:-}"
STORAGE_DOMAIN="${STORAGE_DOMAIN:-${OBJECT_STORAGE_DOMAIN:-}}"
if [[ -z "$DOMAIN" || -z "$STORAGE_DOMAIN" ]]; then
  echo "错误：必须提供 DOMAIN 和 STORAGE_DOMAIN 环境变量。" >&2
  echo "示例：DOMAIN=pkm.example.com STORAGE_DOMAIN=storage.pkm.example.com $0" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "错误：未检测到 docker，请先安装 Docker Engine。" >&2
  exit 1
fi

rand_hex() { openssl rand -hex "$1"; }
# Fernet 密钥 = 32 字节随机数的 urlsafe-base64 编码
rand_fernet() { openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'; }

if [[ ! -f "$ENV_FILE" ]]; then
  echo "生成 $ENV_FILE ..."
  umask 077
  cat > "$ENV_FILE" <<EOF
# 由 deploy/deploy.sh 生成。含加密主密钥，切勿提交或泄露。
# 丢失 PKM_CREDENTIAL_KEY 会导致已保存的模型 API Key 无法解密。
APP_ENV=production
ASSISTANT_TRACE_VIEW_ENABLED=false

POSTGRES_USER=pkm
POSTGRES_DB=pkm
POSTGRES_PASSWORD=$(rand_hex 24)

PKM_CREDENTIAL_KEY=$(rand_fernet)

# 文件链接签名密钥（JWT HS256）
PKM_FILE_LINK_SECRET=$(rand_hex 32)

OBJECT_STORAGE_ACCESS_KEY=$(openssl rand -hex 16 | tr 'a-f' 'A-F')
OBJECT_STORAGE_SECRET_KEY=$(openssl rand -base64 36 | tr -d '\n')
OBJECT_STORAGE_BUCKET=pkm-files

# 前端与对象存储的公网域名（前置 Caddy 终结 HTTPS）
DOMAIN=$DOMAIN
OBJECT_STORAGE_DOMAIN=$STORAGE_DOMAIN

# 固定到 80；由宿主 Caddy 反代到 127.0.0.1:80
WEB_HOST_PORT=80
EOF
  chmod 600 "$ENV_FILE"
  echo "已写入 $ENV_FILE"
else
  echo "复用已存在的 $ENV_FILE（未覆盖）。"
fi

COMPOSE=(docker compose --env-file "$ENV_FILE" -f compose.yaml -f compose.prod.yaml)

echo "==> 构建并启动服务（不含 office profile）"
"${COMPOSE[@]}" up -d --build --wait

echo "==> 下载本地模型（embeddings + vision，首次较慢）"
"${COMPOSE[@]}" --profile model-setup run --rm model-init

echo "==> 运行模型连接自检"
"${COMPOSE[@]}" exec -T api /app/.venv/bin/python -m app.ops.probe || true

echo
echo "部署完成。"
echo "  服务状态： ${COMPOSE[*]} ps"
echo "  下一步  ： 确认 DNS 已解析到本机，并启动宿主 Caddy（见 deploy/Caddyfile.example）"
echo "  浏览器  ： https://$DOMAIN/docs"
