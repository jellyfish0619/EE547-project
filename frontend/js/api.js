const API_BASE = "http://52.35.208.152:8000";

function getToken() {
  return localStorage.getItem("access_token");
}

function setToken(token) {
  localStorage.setItem("access_token", token);
}

function clearToken() {
  localStorage.removeItem("access_token");
}

function buildHeaders(extraHeaders = {}, isJson = true) {
  const headers = { ...extraHeaders };
  const token = getToken();

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  if (isJson && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  return headers;
}

async function apiFetch(path, options = {}) {
  const isFormData = options.body instanceof FormData;

  const response = await fetch(API_BASE + path, {
    ...options,
    headers: buildHeaders(options.headers || {}, !isFormData),
  });

  let data = null;
  try {
    data = await response.json();
  } catch (e) {
    data = { detail: "Non-JSON response from server." };
  }

  if (!response.ok) {
    throw new Error(data.detail || data.message || JSON.stringify(data));
  }

  return data;
}

export function getCourseIdFromUrl() {
  const params = new URLSearchParams(window.location.search);
  return params.get("course_id");
}

export function goToCourse(courseId) {
  window.location.href = `./course.html?course_id=${courseId}`;
}

export function goToQA(courseId) {
  window.location.href = `./qa.html?course_id=${courseId}`;
}

export function goToQuiz(courseId) {
  window.location.href = `./quiz.html?course_id=${courseId}`;
}

export const api = {
  setToken,
  clearToken,
  getToken,

  register: (email, password) =>
    apiFetch("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  login: (email, password) =>
    apiFetch("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  getCourses: () =>
    apiFetch("/courses", {
      method: "GET",
    }),

  createCourse: (name, description) =>
    apiFetch("/courses", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),

  deleteCourse: (courseId) =>
    apiFetch(`/courses/${courseId}`, {
      method: "DELETE",
    }),

  getCourseDetail: (courseId) =>
    apiFetch(`/courses/${courseId}`, {
      method: "GET",
    }),

  uploadDocument: (courseId, file, autoSummary = true) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("auto_summary", String(autoSummary));

    return apiFetch(`/courses/${courseId}/documents`, {
      method: "POST",
      body: formData,
    });
  },

  getDocumentStatus: (docId) =>
    apiFetch(`/documents/${docId}/status`, {
      method: "GET",
    }),

  getDocumentSummary: (docId) =>
    apiFetch(`/documents/${docId}/summary`, {
      method: "GET",
    }),

  deleteDocument: (docId) =>
    apiFetch(`/documents/${docId}`, {
      method: "DELETE",
    }),

  askQuestion: (courseId, question, documentId = null) =>
    apiFetch(`/courses/${courseId}/qa`, {
      method: "POST",
      body: JSON.stringify({
        question,
        document_id: documentId ? Number(documentId) : null,
      }),
    }),

  getQAHistory: (courseId) =>
    apiFetch(`/courses/${courseId}/qa`, {
      method: "GET",
    }),

  generateQuiz: (courseId, numQuestions = 5, documentId = null, difficulty = "medium") =>
    apiFetch(`/courses/${courseId}/quiz/generate`, {
      method: "POST",
      body: JSON.stringify({
        num_questions: Number(numQuestions),
        document_id: documentId ? Number(documentId) : null,
        difficulty,
      }),
    }),

  deleteQuizAttempt: (courseId, sessionId) =>
    apiFetch(`/courses/${courseId}/quiz/${sessionId}`, { method: "DELETE" }),

  submitQuiz: (sessionId, answers) =>
    apiFetch(`/quiz/${sessionId}/submit`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),

  getQuizResult: (sessionId) =>
    apiFetch(`/quiz/${sessionId}/result`, {
      method: "GET",
    }),

  getQuizHistory: (courseId) =>
    apiFetch(`/courses/${courseId}/quiz/history`, {
      method: "GET",
    }),

  deleteQA: (courseId, qaId) =>
    apiFetch(`/courses/${courseId}/qa/${qaId}`, { method: "DELETE" }),

  clearQAHistory: (courseId) =>
    apiFetch(`/courses/${courseId}/qa`, { method: "DELETE" }),

  getKnowledgeMap: (docId, regenerate = false) =>
    apiFetch(`/documents/${docId}/knowledge-map${regenerate ? "?regenerate=true" : ""}`, { method: "GET" }),

  explainPage: (docId, page) =>
    apiFetch(`/documents/${docId}/pages/${page}/explain`, { method: "GET" }),

  getConcepts: (docId, regenerate = false) =>
    apiFetch(`/documents/${docId}/concepts${regenerate ? "?regenerate=true" : ""}`, { method: "GET" }),
};
