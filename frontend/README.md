# CourseMate — Frontend

Static HTML/CSS/JavaScript application served by Nginx.
No build step required — files are served directly.

---

## Directory Structure

```
frontend/
├── index.html        # Login / Register page
├── dashboard.html    # Course list page
├── course.html       # Course detail: documents, summary, Q&A, quiz (main page)
├── css/
│   └── style.css     # Global styles
└── js/
    └── api.js        # All API calls encapsulated here (ES module)
```

---

## Pages

### `index.html` — Login / Register
- Toggle between login and register forms
- On success: stores `access_token` in `localStorage`, redirects to `dashboard.html`

### `dashboard.html` — Course List
- Lists all courses for the logged-in user
- Create new course (name + description)
- Delete course
- Click a course to go to `course.html?course_id=<id>`

### `course.html` — Course Detail (main interface)
All learning features are on this single page, organized into sections:

| Section | Features |
|---------|----------|
| **Documents** | Upload PDF, view processing status, delete documents |
| **Summary** | Section-level AI summary per document |
| **Knowledge Map** | Structured Markdown outline of the document; click to regenerate |
| **Study Mode** | Page-by-page reader with "Explain This Page" AI button |
| **Concept Cards** | Grid of key terms with definitions, formulas, examples |
| **Q&A** | Ask questions with RAG; shows sources; history with delete |
| **Quiz** | Full-screen modal: generate → answer → submit → review results |

---

## `api.js` — API Client

All fetch calls are encapsulated in `js/api.js` as an exported `api` object.

**Authentication** is handled automatically — every request includes the Bearer token from `localStorage`.

**Math rendering** uses MathJax (loaded from CDN). Markdown is rendered with marked.js. A math-stash technique protects LaTeX expressions (`\(…\)`, `\[…\]`) from being escaped by the Markdown parser.

### Available API methods

```javascript
// Auth
api.register(email, password)
api.login(email, password)

// Courses
api.getCourses()
api.createCourse(name, description)
api.getCourseDetail(courseId)
api.deleteCourse(courseId)

// Documents
api.uploadDocument(courseId, file, autoSummary)
api.getDocumentStatus(docId)
api.getDocumentSummary(docId)
api.deleteDocument(docId)

// Learning features
api.getKnowledgeMap(docId, regenerate)     // regenerate=true to force refresh
api.explainPage(docId, page)
api.getConcepts(docId, regenerate)

// Q&A
api.askQuestion(courseId, question, documentId)
api.getQAHistory(courseId)
api.deleteQA(courseId, qaId)
api.clearQAHistory(courseId)

// Quiz
api.generateQuiz(courseId, numQuestions, documentId, difficulty)
api.submitQuiz(sessionId, answers)
api.getQuizResult(sessionId)
api.getQuizHistory(courseId)
api.deleteQuizAttempt(courseId, sessionId)
```

### Navigation helpers

```javascript
getCourseIdFromUrl()          // reads ?course_id= from URL
goToCourse(courseId)
goToQA(courseId)
goToQuiz(courseId)
```

---

## Quiz — Question Types

The quiz modal supports three question types:

| Type | Input | Grading |
|------|-------|---------|
| `mcq` | Radio buttons (A/B/C/D) | Instant, local |
| `short_answer` | Textarea | GPT-graded on submit |
| `calculation` | Textarea + math symbol toolbar | GPT-graded on submit |

The calculation input includes a toolbar with 25 common math symbols (exponents, fractions, integrals, Greek letters, etc.) and a live LaTeX preview powered by MathJax.

---

## Key Frontend Patterns

### Markdown + LaTeX rendering

MathJax and marked.js are both loaded. To prevent marked.js from escaping LaTeX backslashes, the `renderMarkdown(el, text)` function:
1. Extracts all math expressions (`\(…\)`, `\[…\]`, `$…$`, `$$…$$`) and replaces them with unique placeholders
2. Runs `marked.parse()` on the result
3. Restores the original math expressions
4. Calls `MathJax.typesetPromise()` to render

### Document status polling

After uploading a PDF, the frontend polls `GET /documents/{id}/status` every 3 seconds until `status` is `ready` or `failed`.

### ES Module caching

`api.js` is imported as an ES module with a cache-busting version query:
```javascript
import { api, getCourseIdFromUrl } from "./js/api.js?v=2";
```

If JS changes don't appear in the browser, do a hard refresh: **Cmd+Shift+R** (Mac) or **Ctrl+Shift+R** (Windows).

---

## Configuration

The API base URL is set at the top of `js/api.js`:

```javascript
const API_BASE = "http://localhost:8000";
```

Change this to your EC2 public IP or domain for production:

```javascript
const API_BASE = "http://52.35.208.152:8000";
```

---

## External Libraries (CDN, no install required)

| Library | Purpose |
|---------|---------|
| [MathJax 3](https://www.mathjax.org/) | LaTeX math rendering |
| [marked.js 9](https://marked.js.org/) | Markdown → HTML |
