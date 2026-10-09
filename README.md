# 网页讲解助手

网页讲解助手是一个可独立部署的页面讲解与 RAG 问答服务，可在空知识库下运行，也可连接兼容的铁路记忆馆部署。

仓库不包含生产知识文档、图书导入数据、向量数据、会话、缓存、API 密钥、虚拟形象素材或数据库卷。

## 组件

- `core`：FastAPI 服务，负责账号、会话、SSE 对话、网页组件、页面上下文、研究笔记、可选网站同步和受控网站写入会话。
- `rag`：基于 FastAPI、Haystack 和 PostgreSQL/pgvector 的服务，负责文档入库、切片、检索、API 密钥和优先级排序。
- `postgres`：仅供本服务使用的私有 pgvector 数据库。
- 网站集成：可选的只读 PostgreSQL 访问和限时网站写入 API。

## 快速开始

1. 创建共享外部网络，或启动能够创建 `guide_agent_edge` 的网站 Compose 服务栈。

```bash
docker network create guide_agent_edge
docker network create web_default
```

2. 将 `.env.example` 复制为 `.env`，替换全部密码、令牌和模型配置。
3. 启动讲解助手。

```bash
docker compose up -d --build
```

4. 打开 `http://localhost:8080/guide-agent/admin`。

PostgreSQL、SQLite、上传文件、缓存和向量表均以空数据初始化。健康检查位于 `/health`。

## 公开入口

- 网页组件脚本：`/guide-agent/widget.js`
- 团队工作区：`/guide-agent/admin`
- Core API：`/api/guide-agent/`
- 外部入库 API：`/api/guide-agent/v1/`

## Agent 内核

- `tool_configure.json` 声明可用工具，以及 `visitor`、`member`、`team` 和 `cli` 的可见范围。
- 启动时扫描 `core/app/tools/`，由工具自行注册。
- `POST /api/guide-agent/chat/stream` 是主要流式入口。
- `core/main-agent.py` 提供本地检查和提问 CLI。
- 工具循环设有上限和单项超时，连续失败后自动熔断。
- SQLite 在私有卷中保存页面缓存、章节缓存、答案缓存、会话、对话和工具审计记录。

## 知识库导入

可通过 RAG API 或通用结构化文档导入器添加文档：

```bash
python scripts/import_documents.py \
  --document example=/path/to/structured/document \
  --priority secondary \
  --env-file .env \
  --wait
```

导入器要求目录包含：

```text
knowledge_base/knowledge_base.json
text_raw/pages_text/page_001.txt
```

仓库不包含固定书名、本地路径或专题评分。

## 网站集成

网站同步默认关闭。如需启用：

1. 配置 `WEBSITE_EXPORT_BASE_URL` 和 `WEBSITE_EXPORT_TOKEN`。
2. 设置 `WEBSITE_SYNC_ENABLED=true`。
3. 可选：配置 `WEBSITE_READONLY_DATABASE_URL`，直接执行只读内容查询。
4. 可选：配置 `WEBSITE_WRITE_BASE_URL` 和 `WEBSITE_WRITE_ADMIN_TOKEN`，启用限时草稿或发布会话。

网站为可选依赖。关闭同步后，讲解助手仍可使用自身数据库提供对话、页面上下文、缓存和检索功能。

## 测试

```bash
docker compose run --rm --no-deps core pytest
docker compose run --rm --no-deps rag pytest
docker compose config
```

## 许可证

MIT，详见 [LICENSE](LICENSE)。
