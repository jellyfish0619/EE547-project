# CourseMate Frontend

## 项目简介

CourseMate 是一个 AI 驱动的课程助手，支持上传课程 PDF、智能问答和自动生成测验。

后端 API 已经完成，前端需要实现以下页面和功能。

---

## 页面结构

```
frontend/
  ├── index.html        登录 / 注册
  ├── dashboard.html    课程列表
  ├── course.html       课程详情 + 上传文档
  ├── qa.html           问答界面
  ├── quiz.html         测验界面
  ├── css/
  │   └── style.css
  └── js/
      └── api.js        所有 fetch 调用封装在这里
```

---

## 后端 API 地址

本地开发时：`http://localhost:8000`

所有需要登录的接口都要在请求头带上 token：
```
Authorization: Bearer <access_token>
```

完整接口文档可以在 `http://localhost:8000/docs` 查看。

---

## 各页面功能说明

### 1. `index.html` — 登录 / 注册

**注册**
```
POST /auth/register
Body: { "email": "...", "password": "..." }
返回: { "access_token": "...", "token_type": "bearer" }
```

**登录**
```
POST /auth/login
Body: { "email": "...", "password": "..." }
返回: { "access_token": "...", "token_type": "bearer" }
```

登录/注册成功后，把 `access_token` 存到 `localStorage`，然后跳转到 `dashboard.html`。

---

### 2. `dashboard.html` — 课程列表

**获取课程列表**
```
GET /courses
返回: [{ "id": 1, "name": "...", "description": "...", "created_at": "..." }]
```

**创建课程**
```
POST /courses
Body: { "name": "ECE 510", "description": "Linear Algebra" }
返回: { "id": 1, "name": "...", ... }
```

**删除课程**
```
DELETE /courses/{course_id}
```

---

### 3. `course.html` — 课程详情 + 上传文档

URL 参数：`?course_id=1`

**获取课程详情（含文档列表）**
```
GET /courses/{course_id}
返回: {
  "id": 1,
  "name": "...",
  "documents": [
    { "id": 1, "filename": "lecture1.pdf", "status": "ready" }
  ]
}
```

文档 status 说明：
| status | 含义 |
|---|---|
| `pending` | 等待处理 |
| `processing` | 正在解析 + 生成向量 |
| `ready` | 处理完成，可以问答 |
| `failed` | 处理失败 |

**上传 PDF**
```
POST /courses/{course_id}/documents
Content-Type: multipart/form-data
字段:
  file         PDF 文件（必填）
  auto_summary true/false（是否自动生成摘要，默认 true）
返回: { "id": 1, "filename": "...", "status": "pending" }
```

上传后 status 是 `pending`，需要轮询状态直到变成 `ready`：
```
GET /documents/{doc_id}/status
返回: { "id": 1, "filename": "...", "status": "ready" }
```

**查看文档摘要**（status 为 ready 且开启了 auto_summary 才有）
```
GET /documents/{doc_id}/summary
返回: { "id": 1, "filename": "...", "summary": "这门课主要讲..." }
```

**删除文档**
```
DELETE /documents/{doc_id}
```

---

### 4. `qa.html` — 问答界面

URL 参数：`?course_id=1`

**提问**
```
POST /courses/{course_id}/qa
Body: {
  "question": "What is Gaussian elimination?",
  "document_id": 1    // 可选，不传则搜索课程所有文档
}
返回: {
  "answer": "Gaussian elimination is...",
  "sources": [
    { "filename": "lecture1.pdf", "page_number": 5, "content": "..." }
  ]
}
```

`sources` 是 AI 回答所引用的原文，建议在回答下方展示出处。

**获取历史问答记录**
```
GET /courses/{course_id}/qa
返回: [{ "id": 1, "question": "...", "answer": "...", "created_at": "..." }]
```

---

### 5. `quiz.html` — 测验界面

URL 参数：`?course_id=1`

**生成测验**
```
POST /courses/{course_id}/quiz/generate
Body: {
  "num_questions": 5,      // 1-30，默认 5
  "document_id": 1         // 可选，不传则从所有文档出题
}
返回: {
  "session_id": "uuid...",
  "questions": [
    {
      "id": 1,
      "question": "What is...",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "answer": "B"         // 正确答案（注意：展示题目时不要显示这个字段）
    }
  ]
}
```

**提交答案**
```
POST /quiz/{session_id}/submit
Body: {
  "answers": [
    { "question_id": 1, "answer": "B" },
    { "question_id": 2, "answer": "A" }
  ]
}
返回: {
  "session_id": "uuid...",
  "score": 3,
  "total": 5,
  "results": [
    { "question_id": 1, "correct": true, "correct_answer": "B", "user_answer": "B" },
    { "question_id": 2, "correct": false, "correct_answer": "C", "user_answer": "A" }
  ]
}
```

**查看某次测验的错题详情**
```
GET /quiz/{session_id}/result
返回: {
  "session_id": "uuid...",
  "score": 3,
  "total": 5,
  "created_at": "...",
  "questions": [
    {
      "question_id": 1,
      "question": "What is...",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "correct_answer": "B",
      "user_answer": "A",
      "correct": false
    }
  ]
}
```

**查看历史测验记录**
```
GET /courses/{course_id}/quiz/history
返回: [{ "session_id": "uuid...", "score": 3, "total": 5, "created_at": "..." }]
```

---

## `api.js` 封装建议

所有接口调用统一写在 `api.js`，示例结构：

```javascript
const API_BASE = "http://localhost:8000";

function getToken() {
  return localStorage.getItem("access_token");
}

async function apiFetch(path, options = {}) {
  const res = await fetch(API_BASE + path, {
    ...options,
    headers: {
      "Authorization": `Bearer ${getToken()}`,
      ...options.headers,
    },
  });
  if (!res.ok) throw await res.json();
  return res.json();
}

// 示例
export const api = {
  login:      (email, password) => apiFetch("/auth/login", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({email, password}) }),
  getCourses: ()                 => apiFetch("/courses"),
  createCourse: (name, desc)    => apiFetch("/courses", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({name, description: desc}) }),
  askQuestion: (courseId, question, documentId) => apiFetch(`/courses/${courseId}/qa`, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({question, document_id: documentId}) }),
  // ... 其他接口
};
```

---

## 开发注意事项

1. **token 管理**：登录后存 `localStorage`，每次请求带上；退出登录时清除
2. **状态轮询**：上传 PDF 后每隔 3 秒查一次 `/documents/{id}/status`，直到变成 `ready` 或 `failed`
3. **Quiz 答案隐藏**：生成题目时后端会返回正确答案，前端展示题目时不要显示 `answer` 字段，提交后再显示对错
4. **跨域**：本地开发如果遇到 CORS 问题，告知后端在 `api/main.py` 里加 `CORSMiddleware`
