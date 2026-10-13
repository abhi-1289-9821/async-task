# Billing Dispute Resolution Agent — Frontend Workspace

The frontend is a modern, responsive Single Page Application (SPA) built with React 19, Vite, and custom CSS design tokens. It provides human reviewers with a comprehensive audit workspace to inspect disputes, run deterministic calculations, review AI investigation findings, and issue concurrency-safe credit adjustments.

---

## 🎨 Features & Architecture

### 1. Unified Audit Workspace
- **Case Dashboard (`CaseList.jsx`):** Real-time dispute portfolio overview displaying total disputed exposure, active cases, and status filtering (`OPEN`, `AWAITING_INFO`, `RESOLVED`, `REOPENED`).
- **Interactive Preset Scenarios (`CreateCaseModal.jsx`):** One-click demonstration cases for testing:
  - Multi-tier graduated overcharge
  - Ambiguous contract interpretation (competing tier readings)
  - Clean calculation (no discrepancy)
  - Prompt injection attack defense simulation
- **Multi-Tab Investigation Suite (`CaseDetail.jsx`):**
  - **Deterministic Calculation Runner:** Real-time breakdown of invoice line calculations, pricing rules, and cryptographic result IDs (`result_id`).
  - **AI Investigation Panel:** LangGraph workflow execution with cited evidence, reasoning narrative, and suggested resolution options.
  - **Human Review Modal:** Human-in-the-loop review workflow (`ACCEPT`, `EDIT`, `REJECT`) with full attribution and preservation of original AI text.
  - **Credit Approval Gate:** Real-time cumulative cap checks, reason code assignment, and concurrency-safe approval execution.
  - **Append-Only Audit Timeline:** Full history of state transitions, evidence uploads, reviews, and credits.
- **Evidence Management (`EvidenceModal.jsx`):** Upload new usage telemetry batches, automatically bumping evidence versions and invalidating stale findings.

### 2. Role-Based Identity Switcher (`Navbar.jsx`)
- Reviewers and viewers can toggle between identities (`REVIEWER` vs `VIEWER`) directly in the UI.
- Displays live API health status and connectivity indicators.

### 3. Design System & Aesthetics
- Glassmorphism dark mode palette using custom HSL design variables in `index.css`.
- Micro-interactions, animated badges, and responsive data tables.
- Zero bulky external CSS frameworks — pure vanilla CSS for maximum performance and maintainability.

---

## 🛠️ Tech Stack

- **Framework:** React 19
- **Build Tool:** Vite 7
- **Styling:** Vanilla CSS with modern custom properties and responsive layouts
- **Icons:** Lucide React (`lucide-react`)
- **API Client:** Native `fetch` with Bearer token authentication headers

---

## 🚀 Running Locally

### Prerequisites
- Node.js (v18+)
- npm or yarn

### Installation & Development
```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Start Vite development server
npm run dev
```

The application will be accessible at `http://localhost:5173/`.

### Production Build
```bash
# Build production bundle into dist/
npm run build

# Preview production build
npm run preview
```

When deployed in production, the FastAPI backend automatically mounts and serves `frontend/dist` with SPA client routing.
