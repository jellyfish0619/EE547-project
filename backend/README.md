# CourseMate Backend

FastAPI 服务 + 异步文档处理 Worker（PDF 解析、chunk、pgvector 嵌入）。数据库建表语句在仓库根目录 **`docs/schema.sql`**（与 `docker-compose` 中的 Postgres 初始化一致）。

---

## 目录结构

```
backend/
├── api/                      # HTTP API（容器内 PYTHONPATH=/app）
│   ├── main.py               # FastAPI 入口，挂载路由
│   ├── config.py             # 环境变量（Settings）
│   ├── database.py           # SQLAlchemy engine / Session
│   ├── models.py             # ORM 与 docs/schema.sql 对齐
│   ├── schemas.py            # Pydantic 请求/响应体
│   ├── deps.py               # get_db、JWT get_current_user
│   ├── security.py           # bcrypt、JWT 签发与校验
│   ├── util.py               # 如文档状态对外统一展示
│   └── routers/
│       ├── auth.py           # 注册 / 登录 / 当前用户
│       ├── courses.py        # 课程 CRUD
│       ├── documents.py      # PDF 上传、列表、状态、摘要、删除
│       ├── qa.py             # RAG 问答与历史
│       └── quiz.py           # 测验生成、提交、历史
├── worker/                   # SQS 消费或本地管道
│   ├── main.py               # SQS 轮询 或 --local 跑单文件
│   ├── pdf_parser.py         # PDF → 文本 chunk
│   ├── embedder.py           # 向量写入 PostgreSQL（pgvector）
│   └── llm.py                # RAG：search_and_answer、generate_quiz、摘要更新
├── Dockerfile
├── requirements.txt
└── README.md                 # 本文件
```

---

## 配置与环境变量

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | 数据库连接串。API 侧可用 `postgresql+psycopg2://...`；Worker 内会自动规范为 `postgresql://...` 供 `psycopg2` 使用。 |
| `JWT_SECRET` | JWT 签名密钥（生产环境务必修改）。 |
| `OPENAI_API_KEY` | 问答、测验、文档摘要（Worker 写 `documents.summary`）需要。未配置时问答/测验接口会返回 `503`。 |
| `OPENAI_CHAT_MODEL` | 可选，默认 `gpt-4o-mini`。 |
| `S3_BUCKET_NAME` | 若配置：上传写入 S3，SQS 消息带 `s3_key`。 |
| `SQS_QUEUE_URL` | 若配置：上传后发消息，由 Worker 异步处理；若未配置且无 S3，API 会 **子进程** 调用 `worker/main.py --local` 处理。 |
| `AWS_REGION` | 默认 `us-east-1`。 |
| `LOCAL_UPLOAD_DIR` | 本机暂存 PDF，默认 `/app/data/uploads`；`docker-compose` 中通过命名卷 `uploads` 挂载，供 API 与 Worker 共享。 |

仓库根目录 **`docker-compose.yml`** 已挂载 `uploads` 卷到 API 与 Worker，便于「SQS + 本地路径」模式。

---

## 运行

- **推荐**：在仓库根目录执行 `docker compose up`（API：`uvicorn api.main:app --host 0.0.0.0 --port 8000`；Worker：`python worker/main.py`）。
- 本地开发（需已安装 `requirements.txt`、Postgres + pgvector）：在 `backend` 的上一级或设 `PYTHONPATH` 指向 `backend` 的父目录使 `api` / `worker` 可导入，例如  
  `PYTHONPATH=. uvicorn api.main:app --reload`（工作目录为 **`backend`**）。

健康检查：`GET /health`。

---

## API 约定

- **Base URL**：`http://localhost:8000`（compose 映射端口以实际为准）。
- **鉴权**：标有 🔒 的接口需在请求头携带  
  `Authorization: Bearer <access_token>`。
- **ID 类型**：数据库主键为 **自增整数**（`users.id`、`courses.id`、`documents.id` 等）；JSON 中为数字。测验的 `session_id` 为 **UUID** 字符串。

---

## API 参考 — `api/routers/auth.py`

### POST `/auth/register`

**请求**

```json
{
  "email": "user@example.com",
  "password": "yourpassword"
}
```

**响应 `201`**：`access_token`、`token_type`（`bearer`）。

**错误**：`400` 邮箱已被注册。

### POST `/auth/login`

**请求**：同上（email + password）。

**响应 `200`**：Token。

**错误**：`401` 邮箱或密码错误。

### GET `/auth/me` 🔒

**响应 `200`**

```json
{
  "id": 1,
  "email": "user@example.com",
  "created_at": "2024-01-01T00:00:00"
}
```

---

## API 参考 — `api/routers/courses.py`

### GET `/courses` 🔒

当前用户的课程列表（含 `description`）。

### POST `/courses` 🔒

**请求**：`name`、`description`（可选，默认空字符串）。

### GET `/courses/{course_id}` 🔒

课程详情及 `documents` 简要列表（`id`、`filename`、`status`）。

### DELETE `/courses/{course_id}` 🔒

删除课程及关联文档、chunk 等。

---

## API 参考 — `api/routers/documents.py`

### POST `/courses/{course_id}/documents` 🔒

上传 PDF（`multipart/form-data`，字段 `file`）。

- 配置 **S3 + SQS** 时：写入 S3，并发 SQS 消息（`document_id` + `s3_key`），立即 `202` 返回。
- 仅 **SQS** 时：文件落在共享目录，消息体含 `local_path`。
- **均未配置** 时：写入 `LOCAL_UPLOAD_DIR`，由 API **异步子进程** 执行 `python worker/main.py --local <path> <document_id>`。

**响应 `202`**：`id`、`filename`、`status`（一般为 `pending`）。

### GET `/courses/{course_id}/documents` 🔒

文档列表，含 `uploaded_at`（对应库表 `created_at`）。

### GET `/documents/{doc_id}/status` 🔒

状态：`pending` | `processing` | `ready` | `failed`（历史数据如曾为 `error` 会在响应中显示为 `failed`）。

### GET `/documents/{doc_id}/summary` 🔒

需 `ready` 且已成功写入 `summary`。否则可能 `400`（未完成或摘要不可用）。

### DELETE `/documents/{doc_id}` 🔒

删除文档及其 chunk。

---

## API 参考 — `api/routers/qa.py`

### POST `/courses/{course_id}/qa` 🔒

RAG 问答。逻辑在 **`worker/llm.py`** 的 `search_and_answer()`。

**请求**

```json
{
  "question": "什么是梯度下降？",
  "document_id": "12"
}
```

`document_id` 可选：不传则检索该课程下所有 **已 ready** 文档。

**响应**：`answer` + `sources`（`filename`、`page_number`、`content`）。

**错误**：`400` 课程下无已处理文档；`503` 未配置 OpenAI。

### GET `/courses/{course_id}/qa` 🔒

当前用户在该课程下的问答历史。

---

## API 参考 — `api/routers/quiz.py`

### POST `/courses/{course_id}/quiz/generate` 🔒

由 **`worker/llm.py`** 的 `generate_quiz()` 基于材料生成选择题。

**请求**：`num_questions`（可选）、`document_id`（可选）。

**响应 `201`**：`session_id`（UUID）、`questions`（含 `id`、`question`、`options`、`answer`）。

### POST `/quiz/{session_id}/submit` 🔒

提交答案；须覆盖该会话中的全部题目各一次。

**响应**：`score`、`total`、每题 `correct` / `correct_answer`。

### GET `/courses/{course_id}/quiz/history` 🔒

该课程下当前用户的测验提交记录。

---

## Worker 与 LLM 接口（`worker/llm.py`）

API 中的问答与测验直接调用以下函数（参数 `db` 为 SQLAlchemy `Session`）：

```python
def search_and_answer(
    question: str,
    course_id: str,
    db,
    document_id: str | None = None,
) -> dict:
    """
    返回：
    {
        "answer": str,
        "sources": [
            {"filename": str, "page_number": int, "content": str},
        ],
    }
    """
```

```python
def generate_quiz(
    course_id: str,
    db,
    num_questions: int = 5,
    document_id: str | None = None,
) -> list:
    """
    返回：
    [{"id": int, "question": str, "options": list[str], "answer": str}]
    """
```

文档处理完成后，Worker 会在具备 `OPENAI_API_KEY` 时尝试调用 `update_document_summary()` 填充 `documents.summary`。
