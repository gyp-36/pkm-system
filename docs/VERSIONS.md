# 技术栈版本兼容记录

核对日期：2026-10-03（M3 相关行的验收状态更新于 2026-10-05）。Python 依赖由 `uv.lock` 锁定，前端依赖由 `package-lock.json` 锁定。M3 新增文件解析、网页抓取和 ONLYOFFICE 签名依赖；M3 镜像构建与运行验证已随 2026-10-05 集成验收完成（唯余真实公网网页抓取因环境 DNS 污染未验证）。

| 组件 | 版本 | 兼容性依据与状态 |
| --- | --- | --- |
| Python | 3.12 (`python:3.12-slim-bookworm`) | 所选 Python 包的 `Requires-Python` 均包含 3.12；镜像构建通过 |
| FastAPI / Uvicorn | 0.142.2 / 0.54.0 | 容器 API 健康检查与文档请求通过 |
| SQLAlchemy / Alembic | 2.1.1 / 1.20.0 | 初始迁移和 `alembic check` 通过 |
| Argon2-cffi / email-validator | 25.1.0 / 2.3.0 | M1 账号密码哈希和邮箱格式校验；双账号注册登录验证通过 |
| Psycopg / pgvector Python | 3.3.6 / 0.5.0 | 1024 维向量的数据库往返探针通过 |
| PostgreSQL / pgvector | 18 / 0.8.6 (`pgvector/pgvector:0.8.6-pg18`) | 镜像含 linux/arm64 与 linux/amd64；本机迁移通过 |
| Ollama / Embedding | 0.35.0 / `qwen3-embedding:0.6b` | 镜像含 linux/arm64 与 linux/amd64；本机 1024 维推理通过 |
| Node / Vue / Vite / Vue 插件 | 24 / 3.5.43 / 8.3.2 / 6.0.9 | Vite 要求 Node `^20.19.0 || >=22.12.0`；容器构建通过 |
| TypeScript / Vue Router / vue-tsc | 6.0.3 / 5.3.1 / 3.3.11 | TypeScript 7.0.2 与当前 vue-tsc 实际构建不兼容（内部 `./lib/tsc` 未导出）；6.0.3 的类型检查和构建通过 |
| Marked / DOMPurify | 18.0.14 / 3.4.16 | M1 Markdown 预览经 DOMPurify 清理后渲染；Node 24 容器内类型检查与构建通过 |
| uv | 0.12.21 | 用 `uv.lock` 和 `uv sync --locked` 固定 Python 依赖 |
| LangChain / langchain-openai | 1.4.3 / 1.6.7 | M2 `create_agent` 与 OpenAI 兼容聊天模型适配；API 镜像构建及本地模拟服务工具调用通过 |
| Cryptography | 50.0.2 | M2 Fernet 加密模型连接 Key；容器内密文存储、读取和删除验收通过 |
| python-multipart / python-docx | 0.0.32 / 1.2.0 | M3 文件上传和 DOCX 段落提取；容器内多格式上传与 DOCX 定位验收通过（2026-10-05） |
| openpyxl / pypdf | 3.1.5 / 6.19.0 | M3 XLSX 单元格与可检索 PDF 页提取；容器内格式矩阵验收通过（2026-10-05） |
| BeautifulSoup / PyJWT | 4.15.0 / 2.15.1 | M3 网页文本解析与 ONLYOFFICE 文件/回调签名；回调签名校验与重定向/DNS 门禁确定性用例通过（2026-10-05）；真实公网抓取因宿主代理 fake-IP DNS 污染未验证 |
| ONLYOFFICE Docs | `ONLYOFFICE_IMAGE` 可配置；默认 `onlyoffice/documentserver:latest` | M3 可选 Compose profile；真实浏览器打开、编辑、`status=2`/`status=6` 回调与 DOC/XLS 转换已于 2026-10-05 端到端验收通过，部署前应把所用镜像标签固定为该次验收版本 |

查询来源：[PyPI 项目元数据](https://pypi.org/)、[npm Registry](https://www.npmjs.com/)、[Vite Node 版本要求](https://vite.dev/guide/)、[pgvector Docker 标签](https://hub.docker.com/r/pgvector/pgvector/tags)、[Ollama Docker 镜像](https://hub.docker.com/r/ollama/ollama/tags)、[uv Docker 指南](https://docs.astral.sh/uv/guides/integration/docker/)、[LangChain Agent 文档](https://docs.langchain.com/oss/python/langchain/agents)、[DeepSeek API 文档](https://api-docs.deepseek.com/api/create-chat-completion/)。

本机为 arm64 Mac，后期阿里云通常使用 amd64；本机 Docker 中的 Ollama 使用 CPU。云端 2 vCPU / 2 GB 内存可行性尚未验证，届时按实测资源消耗决定是否升配。
