import React, { useEffect, useState, useRef } from 'react';
import { Eye, ShieldCheck, Activity, Cpu, Key, AlertCircle } from 'lucide-react';
import { getActiveRole, setActiveRole, checkHealth, getToken, setCustomToken, hasUserSavedToken } from '../api/client';

export default function Navbar({ onSelectCase, activeCaseId: _activeCaseId }) {
  const [role, setRole] = useState(getActiveRole());
  const [isHealthy, setIsHealthy] = useState(true);
  const [showTokenModal, setShowTokenModal] = useState(false);
  const [tokenInput, setTokenInput] = useState('');
  const [authRequiredPrompt, setAuthRequiredPrompt] = useState(false);
  const modalRef = useRef(null);

  useEffect(() => {
    checkHealth()
      .then(() => setIsHealthy(true))
      .catch(() => setIsHealthy(false));

    const handleAuthError = () => {
      setAuthRequiredPrompt(true);
      setShowTokenModal(true);
      setTokenInput(getToken(role));
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
    setTokenInput(getToken(role));
    setShowTokenModal(true);
  };

  const handleSaveToken = () => {
    setCustomToken(role, tokenInput);
    setShowTokenModal(false);
    setAuthRequiredPrompt(false);
    setRole((r) => r);
  };

  const isTokenActive = hasUserSavedToken(role);

  return (
    <header className="navbar">
      <button 
        type="button"
        className="navbar-brand" 
        onClick={() => onSelectCase(null)}
        style={{ background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', padding: 0 }}
        aria-label="FairBill Home"
      >
        <div className="brand-icon">
          <Cpu size={22} />
        </div>
        <div>
          <div className="brand-title">FairBill</div>
          <div className="brand-subtitle">Autonomous Billing Audit & Governance</div>
        </div>
      </button>

      <div className="navbar-actions">
        {/* API Health indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.78rem', color: isHealthy ? '#34d399' : '#f87171' }}>
          <Activity size={14} className={isHealthy ? 'pulse' : ''} />
          <span>{isHealthy ? 'API Online' : 'API Disconnected'}</span>
        </div>

        {/* Token Management */}
        <button
          type="button"
          className="role-pill-btn"
          style={{ borderColor: isTokenActive ? '#34d399' : '#f59e0b', color: isTokenActive ? '#34d399' : '#f59e0b' }}
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
      </div>

      {showTokenModal && (
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
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Key size={18} color="#38bdf8" />
                <h3 id="token-modal-title" className="modal-title">Configure {role} Session Token</h3>
              </div>
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
                  <strong>Enter your token:</strong> Authentication failed (401). Please enter a valid token.
                </div>
              )}
              <p style={{ fontSize: '0.82rem', color: '#94a3b8', marginBottom: '1rem', lineHeight: '1.4' }}>
                Bearer tokens authenticate reviewer and viewer actions. Tokens are stored only in your local browser session and are never baked into client code bundles.
              </p>
              <div className="form-group">
                <label htmlFor="personal-bearer-token-input" className="form-label">Personal Bearer Token</label>
                <input
                  id="personal-bearer-token-input"
                  type="text"
                  className="form-input"
                  placeholder={`Enter ${role.toLowerCase()} token...`}
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  autoFocus
                />
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ fontSize: '0.75rem', padding: '0.3rem 0.6rem', color: '#f87171' }}
                  onClick={() => setTokenInput('')}
                >
                  Clear Token
                </button>
              </div>
            </div>
            <div className="modal-footer">
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
      )}
    </header>
  );
}
