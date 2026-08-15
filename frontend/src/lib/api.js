export const BACKEND_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, { method = 'GET', body, token } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${BACKEND_URL}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 204) return null;

  let data = null;
  try {
    data = await res.json();
  } catch {
    // no JSON body
  }

  if (!res.ok) {
    throw new ApiError(data?.error || `Request failed (${res.status})`, res.status);
  }
  return data;
}

export const api = {
  signup: (name, email, password) =>
    request('/api/auth/signup', { method: 'POST', body: { name, email, password } }),
  login: (email, password) =>
    request('/api/auth/login', { method: 'POST', body: { email, password } }),
  me: (token) => request('/api/auth/me', { token }),

  listReminders: (token) => request('/api/reminders', { token }),
  createReminder: (token, reminder) =>
    request('/api/reminders', { method: 'POST', body: reminder, token }),
  updateReminder: (token, id, reminder) =>
    request(`/api/reminders/${id}`, { method: 'PUT', body: reminder, token }),
  deleteReminder: (token, id) =>
    request(`/api/reminders/${id}`, { method: 'DELETE', token }),

  chat: (message, answers, token, state) =>
    request('/api/chat', { method: 'POST', body: { message, answers, state }, token }),
  getSymptoms: () => request('/api/symptoms'),
  getTip: () => request('/api/tips'),

  // Real, DB-derived counts for homepage copy — never hardcode a number
  // here instead of fetching it live, the whole point is that it's true.
  getStats: async () => {
    const [diseases, symptoms] = await Promise.all([
      request('/api/diseases?page_size=1'),
      request('/api/symptoms'),
    ]);
    return { diseaseCount: diseases.total, symptomCount: symptoms.symptoms.length };
  },
};

export { ApiError };
