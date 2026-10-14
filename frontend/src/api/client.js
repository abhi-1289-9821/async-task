/**
 * api/client.js
 * =============
 * Centralized API client communicating with FastAPI backend.
 * Supports switching between REVIEWER and VIEWER demo roles with Bearer auth.
 */

const API_BASE = (import.meta.env?.VITE_API_URL || '').replace(/\/$/, '');

// Tokens are strictly user-supplied or loaded from session/localStorage.
// In dev mode only (import.meta.env.DEV), falls back to local demo token for convenience.
// In production builds, import.meta.env.DEV compiles to false and is tree-shaken away with 0 secrets baked in.
export function getToken(role = currentRole) {
  if (role === 'REVIEWER') {
    return localStorage.getItem('billing_reviewer_token') || sessionStorage.getItem('billing_reviewer_token') || (import.meta.env.DEV ? 'demo-reviewer-token-change-me' : '');
  }
  return localStorage.getItem('billing_viewer_token') || sessionStorage.getItem('billing_viewer_token') || (import.meta.env.DEV ? 'demo-viewer-token-change-me' : '');
}

let currentRole = 'REVIEWER';

export function getActiveRole() {
  return currentRole;
}

export function setActiveRole(role) {
  if (role === 'REVIEWER' || role === 'VIEWER') {
    currentRole = role;
    localStorage.setItem('billing_demo_role', role);
  }
}

export function setCustomToken(role, token) {
  const cleanToken = (token || '').trim();
  if (role === 'REVIEWER') {
    localStorage.setItem('billing_reviewer_token', cleanToken);
  } else if (role === 'VIEWER') {
    localStorage.setItem('billing_viewer_token', cleanToken);
  }
}

// Initialize role from storage if present
const savedRole = localStorage.getItem('billing_demo_role');
if (savedRole === 'REVIEWER' || savedRole === 'VIEWER') {
  currentRole = savedRole;
}

async function request(endpoint, options = {}) {
  const token = getToken(currentRole);
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  };

  const url = `${API_BASE}${endpoint}`;
  const response = await fetch(url, {
    ...options,
    headers,
  });

  const contentType = response.headers.get('content-type');
  let data = null;
  if (contentType && contentType.includes('application/json')) {
    data = await response.json();
  } else {
    data = await response.text();
  }

  if (!response.ok) {
    const errorMsg = data?.reason || data?.status_reason || data?.detail || data?.message || response.statusText || 'Request failed';
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

// ── Calculations ────────────────────────────────────────────────────────────
export const runCalculation = (caseId) => request('/api/calculations/run', {
  method: 'POST',
  body: JSON.stringify({ case_id: caseId }),
});
export const getCalculation = (id) => request(`/api/calculations/${id}`);

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
