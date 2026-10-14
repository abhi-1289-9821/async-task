import React, { useEffect, useState } from 'react';
import Navbar from './components/Navbar';
import CaseList from './components/CaseList';
import CaseDetail from './components/CaseDetail';
import CreateCaseModal from './components/CreateCaseModal';
import { getCases } from './api/client';
import { CheckCircle2, AlertCircle, Info, AlertTriangle } from 'lucide-react';

export default function App() {
  const [cases, setCases] = useState([]);
  const [selectedCaseId, setSelectedCaseId] = useState(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [toasts, setToasts] = useState([]);

  const addToast = (type, message) => {
    const id = Date.now();
    setToasts((prev) => [...prev, { id, type, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4500);
  };

  const loadCases = React.useCallback(async () => {
    try {
      const data = await getCases();
      setCases(data);
    } catch (err) {
      addToast('error', err.message || 'Failed to load dispute cases');
    }
  }, []);

  useEffect(() => {
    let isMounted = true;
    getCases()
      .then((data) => {
        if (isMounted) setCases(data);
      })
      .catch((err) => {
        if (isMounted) addToast('error', err.message || 'Failed to load dispute cases');
      });

    const handleAuthChange = () => {
      loadCases();
    };

    window.addEventListener('tokenChanged', handleAuthChange);
    window.addEventListener('roleChanged', handleAuthChange);
    return () => {
      isMounted = false;
      window.removeEventListener('tokenChanged', handleAuthChange);
      window.removeEventListener('roleChanged', handleAuthChange);
    };
  }, [loadCases]);

  const handleCaseCreated = (newCaseId) => {
    addToast('success', `Dispute case '${newCaseId}' created successfully`);
    loadCases();
    setSelectedCaseId(newCaseId);
  };

  return (
    <div className="app-layout">
      <Navbar onSelectCase={setSelectedCaseId} activeCaseId={selectedCaseId} />

      <main className="main-content">
        {selectedCaseId ? (
          <CaseDetail 
            caseId={selectedCaseId} 
            onBack={() => {
              setSelectedCaseId(null);
              loadCases();
            }} 
            onToast={addToast}
          />
        ) : (
          <CaseList 
            cases={cases} 
            onSelectCase={setSelectedCaseId}
            onOpenCreateModal={() => setCreateModalOpen(true)}
          />
        )}
      </main>

      <CreateCaseModal 
        isOpen={createModalOpen} 
        onClose={() => setCreateModalOpen(false)} 
        onCaseCreated={handleCaseCreated}
      />

      {/* Toast notifications container */}
      <div className="toast-container">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.type}`}>
            {t.type === 'success' && <CheckCircle2 size={16} style={{ color: 'var(--status-green)', flexShrink: 0 }} />}
            {t.type === 'error' && <AlertCircle size={16} style={{ color: 'var(--status-rust)', flexShrink: 0 }} />}
            {t.type === 'warning' && <AlertTriangle size={16} style={{ color: 'var(--status-amber)', flexShrink: 0 }} />}
            {t.type === 'info' && <Info size={16} style={{ color: 'var(--status-teal)', flexShrink: 0 }} />}
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
