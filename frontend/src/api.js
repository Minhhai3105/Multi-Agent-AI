// REST client for the FastAPI backend (rule R1: the SPA depends only on the REST API).
const TOKEN_KEY = 'maap_token'
const USER_KEY = 'maap_user'

export const auth = {
  get token() { return localStorage.getItem(TOKEN_KEY) },
  get user() {
    try { return JSON.parse(localStorage.getItem(USER_KEY)) } catch { return null }
  },
  save(token, user) {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  },
}

export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

// Last measured server response time (X-Response-Time-ms) - shown in the UI for QA-3/QA-5.
export const metrics = { last: null, listeners: new Set() }

async function request(method, path, body, { form, withMeta } = {}) {
  const headers = {}
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`
  let payload
  if (form) payload = form
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const started = performance.now()
  const res = await fetch(path, { method, headers, body: payload })
  const serverMs = parseFloat(res.headers.get('X-Response-Time-ms'))
  metrics.last = { method, path, status: res.status, serverMs, clientMs: Math.round(performance.now() - started) }
  metrics.listeners.forEach((fn) => fn(metrics.last))

  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    if (res.status === 401 && path !== '/api/auth/login') {
      auth.clear()
      window.location.href = '/login'
    }
    const err = data?.error || {}
    const details = Array.isArray(err.details) ? err.details.map((d) => `${d.field}: ${d.message}`).join('; ') : ''
    throw new ApiError(res.status, err.code, `${err.message || res.statusText}${details ? ' – ' + details : ''}`, err.details)
  }
  return withMeta ? { data, serverMs } : data
}

export const api = {
  get: (p) => request('GET', p),
  post: (p, b) => request('POST', p, b ?? {}),
  put: (p, b) => request('PUT', p, b),
  del: (p) => request('DELETE', p),
  upload: (p, form) => request('POST', p, undefined, { form }),
  timed: (p) => request('GET', p, undefined, { withMeta: true }),
}

export function qs(params) {
  const s = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') s.set(k, v)
  })
  const str = s.toString()
  return str ? `?${str}` : ''
}
