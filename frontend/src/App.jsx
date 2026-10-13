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

  const loadCases = async () => {
    try {
      const data = await getCases();
      setCases(data);
    } catch (err) {
      addToast('error', err.message || 'Failed to load dispute cases');
    }
  };

  useEffect(() => {
    loadCases();
  }, []);

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
            {t.type === 'success' && <CheckCircle2 size={16} color="var(--accent-emerald)" />}
            {t.type === 'error' && <AlertCircle size={16} color="var(--accent-rose)" />}
            {t.type === 'warning' && <AlertTriangle size={16} color="var(--accent-amber)" />}
            {t.type === 'info' && <Info size={16} color="var(--accent-cyan)" />}
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
