# CourseMate API 文档

Base URL: `http://localhost:8000`

所有带 🔒 的接口需要在请求头中携带 JWT token：
```
Authorization: Bearer <token>
```

---

## 认证 — `api/routers/auth.py`

### POST `/auth/register`
注册新用户。

**请求**
```json
{
  "email": "user@example.com",
  "password": "yourpassword"
}
```

**响应 `201`**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

**错误**
- `400` 邮箱已被注册

---

### POST `/auth/login`
登录并获取 token。

**请求**
```json
{
  "email": "user@example.com",
  "password": "yourpassword"
}
```

**响应 `200`**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

**错误**
- `401` 邮箱或密码错误

---

### GET `/auth/me` 🔒
获取当前登录用户的信息。

**响应 `200`**
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "created_at": "2024-01-01T00:00:00"
}
```

---

## 课程 — `api/routers/courses.py`

### GET `/courses` 🔒
获取当前用户的所有课程。

**响应 `200`**
```json
[
  {
    "id": "uuid",
    "name": "机器学习",
    "description": "USC EE599",
    "created_at": "2024-01-01T00:00:00"
  }
]
```

---

### POST `/courses` 🔒
新建一门课程。

**请求**
```json
{
  "name": "机器学习",
  "description": "USC EE599"
}
```

**响应 `201`**
```json
{
  "id": "uuid",
  "name": "机器学习",
  "description": "USC EE599",
  "created_at": "2024-01-01T00:00:00"
}
```

---

### GET `/courses/{course_id}` 🔒
获取某门课程的详情，包含其下所有文档。

**响应 `200`**
```json
{
  "id": "uuid",
  "name": "机器学习",
  "description": "USC EE599",
  "created_at": "2024-01-01T00:00:00",
  "documents": [
    {
      "id": "uuid",
      "filename": "lecture1.pdf",
      "status": "ready"
    }
  ]
}
```

**错误**
- `404` 课程不存在

---

### DELETE `/courses/{course_id}` 🔒
删除课程及其所有文档和文本块。

**响应 `200`**
```json
{
  "message": "课程已删除"
}
```

**错误**
- `404` 课程不存在

---

## 文档 — `api/routers/documents.py`

### POST `/courses/{course_id}/documents` 🔒
上传 PDF 文件。文件存入 S3，同时向 SQS 发送消息触发异步处理，接口立即返回不等待处理完成。

**请求** `multipart/form-data`
```
file: <PDF 文件>
```

**响应 `202`**
```json
{
  "id": "uuid",
  "filename": "lecture1.pdf",
  "status": "pending"
}
```

**错误**
- `400` 上传的文件不是 PDF
- `404` 课程不存在

---

### GET `/courses/{course_id}/documents` 🔒
获取某门课程下的所有文档。

**响应 `200`**
```json
[
  {
    "id": "uuid",
    "filename": "lecture1.pdf",
    "status": "ready",
    "uploaded_at": "2024-01-01T00:00:00"
  }
]
```

---

### GET `/documents/{doc_id}/status` 🔒
查询文档的处理状态。前端上传后轮询此接口显示进度。

**响应 `200`**
```json
{
  "id": "uuid",
  "filename": "lecture1.pdf",
  "status": "processing"
}
```

状态说明：
- `pending` — 等待处理
- `processing` — Worker 正在处理
- `ready` — 处理完成，可以提问
- `failed` — 处理失败

---

### GET `/documents/{doc_id}/summary` 🔒
获取文档的自动生成摘要。仅在状态为 `ready` 时可用。

**响应 `200`**
```json
{
  "id": "uuid",
  "filename": "lecture1.pdf",
  "summary": "本讲义主要介绍了..."
}
```

**错误**
- `404` 文档不存在
- `400` 文档尚未处理完成

---

### DELETE `/documents/{doc_id}` 🔒
删除文档及其所有文本块。

**响应 `200`**
```json
{
  "message": "文档已删除"
}
```

---

## 问答 — `api/routers/qa.py`

### POST `/courses/{course_id}/qa` 🔒
提问。调用向量检索找到相关片段，再调用 LLM 生成基于课程材料的答案。

> **人员A注意：** 此接口的核心逻辑（向量检索 + LLM 调用）由人员B实现在 `worker/llm.py` 中，直接调用 `search_and_answer()` 函数即可。

**请求**
```json
{
  "question": "什么是梯度下降？",
  "document_id": "uuid"
}
```

`document_id` 为可选字段，不传则在整门课的所有文档中搜索。

**响应 `200`**
```json
{
  "answer": "梯度下降是一种优化算法...",
  "sources": [
    {
      "filename": "lecture3.pdf",
      "page_number": 5,
      "content": "梯度下降是..."
    },
    {
      "filename": "lecture7.pdf",
      "page_number": 12,
      "content": "在实际应用中..."
    }
  ]
}
```

**错误**
- `400` 该课程下没有已处理完成的文档

---

### GET `/courses/{course_id}/qa` 🔒
获取某门课程的历史问答记录。

**响应 `200`**
```json
[
  {
    "id": "uuid",
    "question": "什么是梯度下降？",
    "answer": "梯度下降是...",
    "sources": [...],
    "created_at": "2024-01-01T00:00:00"
  }
]
```

---

## 测验 — `api/routers/quiz.py`

### POST `/courses/{course_id}/quiz/generate` 🔒
根据课程文档生成一组选择题。

> **人员A注意：** 测验生成逻辑由人员B实现在 `worker/llm.py` 中，直接调用 `generate_quiz()` 函数即可。

**请求**
```json
{
  "num_questions": 5,
  "document_id": "uuid"
}
```

`document_id` 为可选字段，不传则基于整门课所有文档生成。

**响应 `201`**
```json
{
  "session_id": "uuid",
  "questions": [
    {
      "id": 1,
      "question": "梯度下降的目标是最小化什么？",
      "options": ["A. 准确率", "B. 损失函数", "C. 学习率", "D. 迭代次数"],
      "answer": "B"
    }
  ]
}
```

---

### POST `/quiz/{session_id}/submit` 🔒
提交测验答案，返回得分和每题解析。

**请求**
```json
{
  "answers": [
    {"question_id": 1, "answer": "B"},
    {"question_id": 2, "answer": "A"}
  ]
}
```

**响应 `200`**
```json
{
  "session_id": "uuid",
  "score": 4,
  "total": 5,
  "results": [
    {
      "question_id": 1,
      "correct": true,
      "correct_answer": "B"
    },
    {
      "question_id": 2,
      "correct": false,
      "correct_answer": "C"
    }
  ]
}
```

---

### GET `/courses/{course_id}/quiz/history` 🔒
获取某门课程的历史测验记录。

**响应 `200`**
```json
[
  {
    "session_id": "uuid",
    "score": 4,
    "total": 5,
    "created_at": "2024-01-01T00:00:00"
  }
]
```

---

## 人员A 和 人员B 的接口约定

人员A 的 `qa.py` 和 `quiz.py` 需要调用人员B 在 `worker/llm.py` 中实现的函数。
**开发前必须对齐以下函数签名：**

```python
# worker/llm.py（人员B实现）

def search_and_answer(question: str, course_id: str, db, document_id: str = None) -> dict:
    """
    返回格式：
    {
        "answer": str,
        "sources": [{"filename": str, "page_number": int, "content": str}]
    }
    """
    pass

def generate_quiz(course_id: str, db, num_questions: int = 5, document_id: str = None) -> list:
    """
    返回格式：
    [{"id": int, "question": str, "options": list, "answer": str}]
    """
    pass
```

