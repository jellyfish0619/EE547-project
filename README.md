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
  │   │   ├── auth.py 注册和登录接口
  │   │   ├── courses.py 课程的增删查接口
  │   │   ├── documents.py PDF 上传和状态查询
  │   │   ├── qa.py 问答接口
  │   │   └── quiz.py 测验接口
  │   ├── models/
  │   │   └── schemas.py  定义请求和响应的数据格式
  │   └── core/
  │       ├── auth.py JWT逻辑
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


## 开发规范

从github clone 后创建一个自己的分支，每次提交后需要merge的话，微信告诉我，我会合并到
main中。定期pull最新的main。然后最好重新创造一个新的虚拟环境，python版本是3.11，
其他所需要的依赖，都写在backend文档中的requirements.txt文件中，直接安装就行。