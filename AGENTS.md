# 仓库贡献指南

## 项目结构与模块组织

本仓库由 Python API/worker 后端和 Vue 3 + TypeScript 前端组成。后端代码位于 `api/app/`：`auth/` 负责账户，`assistant/` 负责模型连接与对话，`knowledge/` 负责笔记、导入、索引和搜索，`core/` 存放共享基础设施，`ops/` 存放 worker 与运维检查。数据库迁移位于 `api/alembic/versions/`，验证和维护脚本位于 `api/scripts/`。前端代码与资源位于 `web/src/`；设计参考和评测数据分别位于 `design/`、`evaluation/`。

## 构建、测试与开发命令

- `python3 scripts/dev-up.py` — 构建并启动本地 Docker Compose 服务；需要 Docker Desktop 和 Python 3。
- `docker compose --env-file .env.local config --quiet` — 检查 Compose 配置。
- `cd web && npm run dev` — 启动 Vite 前端；`npm run build` 会进行 Vue 类型检查并构建生产包，`npm run typecheck` 只检查类型。
- `docker compose --env-file .env.local exec -T api /app/.venv/bin/python -m scripts.verify_m1` — 运行 M1 后端回归验证。相关验证包括 `scripts.verify_m2`、`scripts.verify_conversations`、`scripts.verify_lifecycle` 和 `scripts.check_integrity`，均在 API 容器内执行。

## 代码风格与命名约定

Python 使用 4 个空格缩进；Vue/TypeScript 格式与相邻代码保持一致。Python 使用 `snake_case`，TypeScript 变量和函数使用 `camelCase`，Vue 组件使用 `PascalCase.vue`。后端功能代码放入对应领域包。Alembic 迁移使用递增的零填充序号和简短用途命名，例如 `0013_add_feature.py`；持久化数据变更时同步更新数据库设计文档。

## 测试与验证

验证脚本位于 `api/scripts/`；目前没有独立测试套件。请在 Compose 环境中运行与改动相关的验证；修改前端时运行 `npm run build`。部分脚本会创建临时账户和数据，扩展脚本前请检查其清理逻辑。

## 提交与 Pull Request 规范

近期提交使用简短的中文类型前缀，例如 `后端：...`、`前端：...`、`构建：...`。请沿用此格式并清楚概括改动。Pull Request 应说明用户可见影响或数据结构变更，关联相关设计/验证文档，列出执行过的命令及结果；界面改动请附截图。迁移或配置变更需明确说明。

## 安全与本地配置

不要将 `.env.local`、模型 API Key、加密密钥或本地数据提交到仓库。日常关闭服务时请保留数据库和对象存储卷；`docker compose down -v` 会删除持久化数据。
