import React, { useEffect, useState, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Eye, ShieldCheck, Activity, Key, AlertCircle, X, Trash2, Sun, Moon } from 'lucide-react';
import { getActiveRole, setActiveRole, checkHealth, getToken, setCustomToken, hasActiveToken, isDemoMode } from '../api/client';

export default function Navbar({ onSelectCase, activeCaseId: _activeCaseId }) {
  const [role, setRole] = useState(getActiveRole());
  const [isHealthy, setIsHealthy] = useState(true);
  const [showTokenModal, setShowTokenModal] = useState(false);
  const [tokenInput, setTokenInput] = useState('');
  const [authRequiredPrompt, setAuthRequiredPrompt] = useState(false);
  const [theme, setTheme] = useState(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('fairbill_theme');
      if (saved) return saved;
      if (typeof window.matchMedia === 'function') {
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
      }
    }
    return 'light';
  });
  const modalRef = useRef(null);

  useEffect(() => {
    if (typeof document !== 'undefined') {
      document.documentElement.setAttribute('data-theme', theme);
      localStorage.setItem('fairbill_theme', theme);
    }
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  };

  useEffect(() => {
    checkHealth()
      .then(() => setIsHealthy(true))
      .catch(() => setIsHealthy(false));

    const handleAuthError = () => {
      const defaultTok = isDemoMode ? (role === 'REVIEWER' ? 'demo-reviewer-token-2026' : 'demo-viewer-token-2026') : '';
      setAuthRequiredPrompt(true);
      setShowTokenModal(true);
      setTokenInput(getToken(role) || defaultTok);
    };

    window.addEventListener('authError', handleAuthError);
    return () => window.removeEventListener('authError', handleAuthError);
  }, [role]);

  // Escape key handler & focus trap for modal
  useEffect(() => {
    if (!showTokenModal) return;

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setShowTokenModal(false);
        return;
      }
      if (e.key === 'Tab' && modalRef.current) {
        const focusables = modalRef.current.querySelectorAll(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showTokenModal]);

  const handleRoleToggle = (newRole) => {
    setActiveRole(newRole);
    setRole(newRole);
  };

  const openTokenModal = () => {
    const defaultTok = isDemoMode ? (role === 'REVIEWER' ? 'demo-reviewer-token-2026' : 'demo-viewer-token-2026') : '';
    setTokenInput(getToken(role) || defaultTok);
    setShowTokenModal(true);
  };

  const handleSaveToken = () => {
    const defaultTok = isDemoMode ? (role === 'REVIEWER' ? 'demo-reviewer-token-2026' : 'demo-viewer-token-2026') : '';
    const effectiveToken = (tokenInput || '').trim() || defaultTok;
    setCustomToken(role, effectiveToken);
    setShowTokenModal(false);
    setAuthRequiredPrompt(false);
    setRole((r) => r);
  };

  const isTokenActive = hasActiveToken(role);

  return (
    <header className="navbar">
      <button 
        type="button"
        className="navbar-brand" 
        onClick={() => onSelectCase(null)}
        aria-label="FairBill Home"
      >
        <img 
          src="/logo.png" 
          alt="FairBill Logo" 
          style={{ 
            width: 34, 
            height: 34, 
            borderRadius: 'var(--radius-sm)', 
            objectFit: 'contain',
            boxShadow: '0 2px 8px rgba(0, 0, 0, 0.2)'
          }} 
        />
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', textAlign: 'left' }}>
          <span className="brand-title">FairBill</span>
          <span className="brand-subtitle">Audit & Governance</span>
        </div>
      </button>

      <div className="navbar-actions">
        {/* API Health indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.78rem', color: isHealthy ? 'var(--status-green)' : 'var(--status-rust)' }}>
          <Activity size={13} />
          <span>{isHealthy ? 'API Online' : 'API Offline'}</span>
        </div>

        {/* Token Management */}
        <button
          type="button"
          className="role-pill-btn"
          style={{ 
            borderColor: isTokenActive ? 'var(--status-green-border)' : 'var(--line)', 
            color: isTokenActive ? 'var(--status-green)' : 'var(--ink-secondary)',
            background: isTokenActive ? 'var(--status-green-bg)' : 'transparent',
            border: '1px solid'
          }}
          onClick={openTokenModal}
          title="Configure personal Bearer token (never stored in bundle)"
        >
          <Key size={13} />
          <span>{isTokenActive ? 'Token Active' : 'Set Token'}</span>
        </button>

        {/* Demo Role Switcher */}
        <div className="role-pill-group" title="Switch Role Identity">
          <button
            type="button"
            className={`role-pill-btn ${role === 'REVIEWER' ? 'active-reviewer' : ''}`}
            onClick={() => handleRoleToggle('REVIEWER')}
          >
            <ShieldCheck size={13} />
            <span>Reviewer</span>
          </button>
          <button
            type="button"
            className={`role-pill-btn ${role === 'VIEWER' ? 'active-viewer' : ''}`}
            onClick={() => handleRoleToggle('VIEWER')}
          >
            <Eye size={13} />
            <span>Viewer (Read-Only)</span>
          </button>
        </div>

        {/* Theme Toggle Button */}
        <button
          type="button"
          className="theme-toggle-btn"
          onClick={toggleTheme}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
        >
          {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
        </button>
      </div>

      {showTokenModal && typeof document !== 'undefined' && createPortal(
        <div 
          className="modal-overlay" 
          onClick={() => setShowTokenModal(false)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="token-modal-title"
        >
          <div 
            ref={modalRef}
            className="modal-content" 
            style={{ maxWidth: '480px' }} 
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                <div style={{
                  width: 32,
                  height: 32,
                  borderRadius: 'var(--radius-sm)',
                  background: 'rgba(56, 189, 248, 0.12)',
                  border: '1px solid rgba(56, 189, 248, 0.3)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}>
                  <Key size={16} color="#38bdf8" />
                </div>
                <h3 id="token-modal-title" className="modal-title">Configure {role} Session Token</h3>
              </div>
              <button
                type="button"
                onClick={() => setShowTokenModal(false)}
                className="btn btn-secondary btn-sm"
                aria-label="Close dialog"
                style={{ borderRadius: '50%', width: 30, height: 30, padding: 0 }}
              >
                <X size={15} />
              </button>
            </div>

            <div className="modal-body">
              {authRequiredPrompt && (
                <div style={{
                  background: 'rgba(239, 68, 68, 0.1)',
                  border: '1px solid rgba(239, 68, 68, 0.35)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '0.65rem 0.85rem',
                  marginBottom: '1rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  fontSize: '0.82rem',
                  color: '#fca5a5'
                }}>
                  <AlertCircle size={16} color="var(--accent-rose)" />
                  <div><strong>Enter your token:</strong> Authentication failed (401). Please enter a valid token.</div>
                </div>
              )}
              <p style={{ fontSize: '0.82rem', color: '#94a3b8', marginBottom: '1.25rem', lineHeight: '1.5' }}>
                Bearer tokens authenticate reviewer and viewer actions. Tokens are stored only in your local browser session and are never baked into client code bundles.
              </p>

              <div className="form-group" style={{ marginBottom: 0 }}>
                <label htmlFor="personal-bearer-token-input" className="form-label" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>Personal Bearer Token</span>
                  {isDemoMode && (
                    <button
                      type="button"
                      style={{
                        background: 'rgba(56, 189, 248, 0.12)',
                        border: '1px solid rgba(56, 189, 248, 0.35)',
                        borderRadius: '4px',
                        color: 'var(--accent-cyan)',
                        fontSize: '0.72rem',
                        fontWeight: 500,
                        padding: '0.15rem 0.5rem',
                        cursor: 'pointer'
                      }}
                      onClick={() => setTokenInput(role === 'REVIEWER' ? 'demo-reviewer-token-2026' : 'demo-viewer-token-2026')}
                      title="Click to insert default demo token"
                    >
                      Click to Use Default: {role === 'REVIEWER' ? 'demo-reviewer-token-2026' : 'demo-viewer-token-2026'}
                    </button>
                  )}
                </label>
                <div style={{ position: 'relative' }}>
                  <input
                    id="personal-bearer-token-input"
                    type="text"
                    className="form-input"
                    style={{ paddingRight: tokenInput ? '2.5rem' : '0.85rem' }}
                    placeholder={`Enter ${role.toLowerCase()} token...`}
                    value={tokenInput}
                    onChange={(e) => setTokenInput(e.target.value)}
                    autoFocus
                  />
                  {tokenInput && (
                    <button
                      type="button"
                      onClick={() => setTokenInput('')}
                      aria-label="Clear input text"
                      title="Clear input"
                      style={{
                        position: 'absolute',
                        right: '0.6rem',
                        top: '50%',
                        transform: 'translateY(-50%)',
                        background: 'transparent',
                        border: 'none',
                        color: 'var(--text-muted)',
                        cursor: 'pointer',
                        padding: '0.2rem',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        borderRadius: '4px'
                      }}
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
              </div>
            </div>

            <div className="modal-footer">
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ 
                    fontSize: '0.8rem', 
                    padding: '0.5rem 0.85rem', 
                    color: '#f87171',
                    borderColor: 'rgba(248, 113, 113, 0.25)',
                    background: 'rgba(248, 113, 113, 0.06)'
                  }}
                  onClick={() => setTokenInput('')}
                  disabled={!tokenInput}
                >
                  <Trash2 size={13} />
                  <span>Clear</span>
                </button>
                {isDemoMode && (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    style={{
                      fontSize: '0.8rem',
                      padding: '0.5rem 0.85rem',
                      color: 'var(--accent-cyan)',
                      borderColor: 'rgba(56, 189, 248, 0.3)'
                    }}
                    onClick={() => {
                      const defTok = role === 'REVIEWER' ? 'demo-reviewer-token-2026' : 'demo-viewer-token-2026';
                      setTokenInput(defTok);
                    }}
                  >
                    Fill Default
                  </button>
                )}
              </div>
              <div className="modal-footer-end">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowTokenModal(false)}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={handleSaveToken}
                >
                  Save Token
                </button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}
    </header>
  );
}
