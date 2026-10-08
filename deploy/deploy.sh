#!/usr/bin/env bash
# 云服务器一键部署脚本（幂等，可重复执行）。
#
# 用法（本地 Ollama，需 ≥4GB 内存）：
#   DOMAIN=pkm.example.com STORAGE_DOMAIN=storage.pkm.example.com ./deploy/deploy.sh
#
# 用法（第三方模型，2GB 也可，强烈推荐）：
#   DOMAIN=pkm.example.com STORAGE_DOMAIN=storage.pkm.example.com \
#     DASHSCOPE_API_KEY=sk-xxx ./deploy/deploy.sh
#
# 首次执行会生成含随机密钥的 .env.prod（权限 600）；已存在时复用，不会覆盖。
# 之后构建镜像、执行数据库迁移、启动全部服务；本地模式再下载 Ollama 模型。
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
ENV_FILE="$ROOT/.env.prod"

DOMAIN="${DOMAIN:-}"
STORAGE_DOMAIN="${STORAGE_DOMAIN:-${OBJECT_STORAGE_DOMAIN:-}}"
MODEL_PROVIDER="ollama"
if [[ -n "${DASHSCOPE_API_KEY:-}" || "${EMBEDDING_PROVIDER:-}" == "openai" ]]; then
  MODEL_PROVIDER="openai"
fi
if [[ -z "$DOMAIN" || -z "$STORAGE_DOMAIN" ]]; then
  echo "错误：必须提供 DOMAIN 和 STORAGE_DOMAIN 环境变量。" >&2
  echo "示例：DOMAIN=pkm.example.com STORAGE_DOMAIN=storage.pkm.example.com $0" >&2
  exit 1
fi
if [[ "$MODEL_PROVIDER" == "openai" && -z "${DASHSCOPE_API_KEY:-}${EMBEDDING_API_KEY:-}" ]]; then
  echo "错误：第三方模型模式需要 DASHSCOPE_API_KEY（或 EMBEDDING_API_KEY）。" >&2
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
EOF
  if [[ "$MODEL_PROVIDER" == "openai" ]]; then
    cat >> "$ENV_FILE" <<EOF

# 模型：第三方 OpenAI 兼容服务（默认百炼 DashScope），无需 Ollama
EMBEDDING_PROVIDER=openai
EMBEDDING_BASE_URL=${EMBEDDING_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}
EMBEDDING_MODEL=${EMBEDDING_MODEL:-text-embedding-v3}
EMBEDDING_API_KEY=${EMBEDDING_API_KEY:-${DASHSCOPE_API_KEY:-}}
VISION_PROVIDER=openai
VISION_BASE_URL=${VISION_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}
VISION_MODEL=${VISION_MODEL:-qwen-vl-plus}
VISION_API_KEY=${VISION_API_KEY:-${DASHSCOPE_API_KEY:-}}
EOF
  fi
  cat >> "$ENV_FILE" <<EOF

# 前端与对象存储的公网域名（前置 Caddy 终结 HTTPS）
DOMAIN=$DOMAIN
OBJECT_STORAGE_DOMAIN=$STORAGE_DOMAIN

# 固定到 80；由宿主 Caddy 反代到 127.0.0.1:80
WEB_HOST_PORT=80
EOF
  chmod 600 "$ENV_FILE"
  echo "已写入 $ENV_FILE（模型 provider：$MODEL_PROVIDER）"
else
  echo "复用已存在的 $ENV_FILE（未覆盖）。"
fi

COMPOSE=(docker compose --env-file "$ENV_FILE" -f compose.yaml -f compose.prod.yaml)

# 契约门禁：先构建 api 镜像并静态校验（响应契约覆盖 / tool 信封 / 归属过滤）。
# 未通过则中止，避免把无契约或越权的变更部署上线。
echo "==> 契约门禁（静态检查）"
if ! "${COMPOSE[@]}" --profile gate run --rm contract-check; then
  echo "契约门禁未通过，部署中止。请按上方提示修正后重试。" >&2
  exit 1
fi

echo "==> 构建并启动服务（不含 office profile）"
if [[ "$MODEL_PROVIDER" == "openai" ]]; then
  # 第三方模式：不启动 ollama 容器（内存友好）。
  "${COMPOSE[@]}" up -d --build --wait --scale ollama=0
else
  "${COMPOSE[@]}" up -d --build --wait
  echo "==> 下载本地模型（embeddings + vision，首次较慢）"
  "${COMPOSE[@]}" --profile model-setup run --rm model-init
fi

echo "==> 运行模型连接自检"
"${COMPOSE[@]}" exec -T api /app/.venv/bin/python -m app.ops.probe || true

echo
echo "部署完成（模型 provider：$MODEL_PROVIDER）。"
echo "  服务状态： ${COMPOSE[*]} ps"
echo "  下一步  ： 确认 DNS 已解析到本机，并启动宿主 Caddy（见 deploy/Caddyfile.example）"
echo "  浏览器  ： https://$DOMAIN/docs"
