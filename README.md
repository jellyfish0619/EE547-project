# EE547-project


## 期望的目录结构

### 总体架构
```
coursemate/
  ├── backend/Python 后端（A + B）
  ├── frontend/前端页面（C）
  ├── docs/文档和架构图
  ├── docker-compose.yml本地启动所有服务
  ├── .env.example环境变量模板（提交）
  ├── .env真实 key（不提交）
  ├── .gitignore
  └── README.md
```

### backend
```
backend/
  ├── api/人员 A
  │   ├── main.pyFastAPI 入口
  │   ├── routers/
  │   │   ├── auth.py注册/登录
  │   │   ├── courses.py
  │   │   ├── documents.py上传PDF、查状态
  │   │   ├── qa.py问答接口
  │   │   └── quiz.py
  │   ├── models/
  │   │   └── schemas.py请求/响应的数据结构
  │   └── core/
  │       ├── auth.pyJWT 逻辑
  │       └── database.py数据库连接
  ├── worker/人员 B
  │   ├── main.pySQS 消费者入口
  │   ├── pdf_parser.pyPDF 解析 + 切块
  │   ├── embedder.pysentence-transformers
  │   └── llm.py向量检索 + LLM 调用
  ├── Dockerfile
  └── requirements.txt
```

### fronted
```
frontend/人员 C
  ├── index.html登录/注册
  ├── dashboard.html课程列表
  ├── course.html课程详情 + 上传
  ├── qa.html问答界面
  ├── quiz.html测验界面
  ├── css/
  │   └── style.css
  └── js/
      └── api.js所有 fetch 调用封装在这里
```

### docs
```
docs/
  ├── architecture.md系统架构说明
  ├── schema.sql建表语句
  └── api.md所有接口文档
```
