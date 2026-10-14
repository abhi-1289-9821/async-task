/**
 * api/client.js
 * =============
 * Centralized API client communicating with FastAPI backend.
 * Supports switching between REVIEWER and VIEWER demo roles with Bearer auth.
 */

const API_BASE = (import.meta.env?.VITE_API_URL || '').replace(/\/$/, '');

// Tokens are strictly user-supplied or loaded from session/localStorage.
// In dev mode only (import.meta.env.DEV), falls back to VITE_DEV_REVIEWER_TOKEN / VITE_DEV_VIEWER_TOKEN if present.
export function getToken(role = currentRole) {
  if (role === 'REVIEWER') {
    const saved = localStorage.getItem('billing_reviewer_token') || sessionStorage.getItem('billing_reviewer_token');
    if (saved) return saved;
    if (import.meta.env?.VITE_DEV_REVIEWER_TOKEN) {
      return import.meta.env.VITE_DEV_REVIEWER_TOKEN;
    }
    if (import.meta.env?.DEV) {
      return 'demo-reviewer-token-2026';
    }
    return '';
  }
  const savedViewer = localStorage.getItem('billing_viewer_token') || sessionStorage.getItem('billing_viewer_token');
  if (savedViewer) return savedViewer;
  if (import.meta.env?.VITE_DEV_VIEWER_TOKEN) {
    return import.meta.env.VITE_DEV_VIEWER_TOKEN;
  }
  if (import.meta.env?.DEV) {
    return 'demo-viewer-token-2026';
  }
  return '';
}

export function hasActiveToken(role = currentRole) {
  return Boolean(getToken(role));
}

export function hasUserSavedToken(role = currentRole) {
  if (role === 'REVIEWER') {
    return Boolean((localStorage.getItem('billing_reviewer_token') || sessionStorage.getItem('billing_reviewer_token') || '').trim());
  }
  return Boolean((localStorage.getItem('billing_viewer_token') || sessionStorage.getItem('billing_viewer_token') || '').trim());
}

let currentRole = 'REVIEWER';

export function getActiveRole() {
  return currentRole;
}

export function setActiveRole(role) {
  if (role === 'REVIEWER' || role === 'VIEWER') {
    currentRole = role;
    localStorage.setItem('billing_demo_role', role);
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('roleChanged', { detail: { role } }));
    }
  }
}

export function setCustomToken(role, token) {
  const cleanToken = (token || '').trim();
  if (role === 'REVIEWER') {
    localStorage.setItem('billing_reviewer_token', cleanToken);
  } else if (role === 'VIEWER') {
    localStorage.setItem('billing_viewer_token', cleanToken);
  }
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('tokenChanged', { detail: { role, token: cleanToken } }));
  }
}

// Initialize role from storage if present
const savedRole = localStorage.getItem('billing_demo_role');
if (savedRole === 'REVIEWER' || savedRole === 'VIEWER') {
  currentRole = savedRole;
}

// Support 1-click evaluation access via ?token=...&role=... query parameters
if (typeof window !== 'undefined' && window.location?.search) {
  try {
    const searchParams = new URLSearchParams(window.location.search);
    const paramToken = searchParams.get('token');
    const paramRole = searchParams.get('role');
    if (paramToken) {
      const cleanToken = paramToken.trim();
      const targetRole = (paramRole && paramRole.toUpperCase() === 'VIEWER') ? 'VIEWER' : 'REVIEWER';
      setCustomToken(targetRole, cleanToken);
      setActiveRole(targetRole);
      const cleanUrl = window.location.pathname + window.location.hash;
      window.history.replaceState({}, document.title, cleanUrl);
    }
  } catch (err) {
    console.debug('Failed to parse URL token parameter:', err);
  }
}

async function request(endpoint, options = {}) {
  const token = getToken(currentRole);
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  };

  const timeoutMs = options.timeout ?? 120000;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const url = `${API_BASE}${endpoint}`;
  let response;
  try {
    response = await fetch(url, {
      ...options,
      headers,
      signal: options.signal || controller.signal,
    });
  } catch (err) {
    if (err.name === 'AbortError') {
      const timeoutError = new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s`);
      timeoutError.status = 504;
      throw timeoutError;
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }

  const contentType = response.headers.get('content-type');
  let data = null;
  if (contentType && contentType.includes('application/json')) {
    data = await response.json();
  } else {
    data = await response.text();
  }

  if (!response.ok) {
    if (response.status === 401 && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('authError', { detail: { status: 401 } }));
    }
    let rawDetail = data?.reason || data?.status_reason || data?.detail || data?.message || response.statusText || 'Request failed';
    let errorMsg = rawDetail;
    if (Array.isArray(rawDetail)) {
      errorMsg = rawDetail
        .map((err) => {
          if (typeof err === 'string') return err;
          const loc = Array.isArray(err?.loc) ? err.loc.filter(x => x !== 'body').join('.') : '';
          const msg = err?.msg || err?.message || JSON.stringify(err);
          return loc ? `${loc}: ${msg}` : msg;
        })
        .join('; ');
    } else if (typeof rawDetail === 'object' && rawDetail !== null) {
      errorMsg = JSON.stringify(rawDetail);
    }
    const error = new Error(errorMsg);
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data;
}

// ── Health ──────────────────────────────────────────────────────────────────
export const checkHealth = () => request('/healthz');

// ── Cases ───────────────────────────────────────────────────────────────────
export const getCases = () => request('/api/cases');
export const getCase = (id) => request(`/api/cases/${id}`);
export const createCase = (payload) => request('/api/cases', {
  method: 'POST',
  body: JSON.stringify(payload),
});
export const transitionCase = (id, targetStatus, note) => request(`/api/cases/${id}/transition`, {
  method: 'POST',
  body: JSON.stringify({ target_status: targetStatus, note }),
});
export const getCaseEvents = (id) => request(`/api/cases/${id}/events`);
export const uploadEvidence = (id, payload) => request(`/api/cases/${id}/evidence`, {
  method: 'POST',
  body: JSON.stringify(payload),
});
export const uploadRulesEvidence = (id, payload) => request(`/api/cases/${id}/evidence/rules`, {
  method: 'POST',
  body: JSON.stringify(payload),
});


// ── Calculations ────────────────────────────────────────────────────────────
export const runCalculation = (caseId) => request('/api/calculations/run', {
  method: 'POST',
  body: JSON.stringify({ case_id: caseId }),
});
export const getCalculation = (id) => request(`/api/calculations/${id}`);
export const getCaseCalculations = (caseId) => request(`/api/calculations/case/${caseId}`);

// ── Investigations (LangGraph) ──────────────────────────────────────────────
export const triggerInvestigation = (caseId) => request(`/api/cases/${caseId}/investigations`, {
  method: 'POST',
});
export const getCaseInvestigations = (caseId) => request(`/api/cases/${caseId}/investigations`);
export const getInvestigation = (id) => request(`/api/investigations/${id}`);

// ── Findings & Human Review ─────────────────────────────────────────────────
export const getCaseFindings = (caseId) => request(`/api/findings/case/${caseId}`);
export const reviewFinding = (findingId, payload) => request(`/api/findings/${findingId}/review`, {
  method: 'POST',
  body: JSON.stringify(payload),
});

// ── Credits ─────────────────────────────────────────────────────────────────
export const approveCredit = (payload) => request('/api/credits/approve', {
  method: 'POST',
  body: JSON.stringify(payload),
});
export const getCaseCredits = (caseId) => request(`/api/credits/case/${caseId}`);
export const getCreditCap = (caseId, invoiceLineId) =>
  request(`/api/credits/case/${caseId}/cap?invoice_line_id=${encodeURIComponent(invoiceLineId)}`);
export const resetDemoCases = () => request('/api/cases/reset-demo', { method: 'POST' });

