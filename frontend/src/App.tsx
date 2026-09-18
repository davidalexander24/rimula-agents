import { useState } from 'react';
import {
  X, RefreshCw, WifiOff, Database, Cpu, Search, ShoppingBag, Activity, Sparkles,
} from 'lucide-react';
import { AppHeader, DataDialogContent } from './components/layout/AppHeader';
import { Tabs, type TabId } from './components/layout/Tabs';
import { DegradedBanner } from './components/layout/DegradedBanner';
import { ExperimentTab } from './components/experiment/ExperimentTab';
import { EvidenceTab } from './components/evidence/EvidenceTab';
import { ResearchTab } from './components/agents/ResearchTab';
import { useHealth } from './hooks/useHealth';

const services = [
  ['db_ready', 'Database Formula', Database],
  ['model_ready', 'Designer (GP-BO)', Sparkles],
  ['llm_ready', 'Orchestrator (Qwen)', Cpu],
  ['scout_ready', 'Scout (Europe PMC)', Search],
  ['market_ready', 'Pasar (BeautyFacts)', ShoppingBag],
  ['evaluation_ready', 'Evaluasi Benchmark', Activity],
] as const;

export default function App() {
  const [active, setActiveTab] = useState<TabId>('experiment');
  const [visited, setVisited] = useState<Record<TabId, boolean>>({ experiment: true, evidence: false, research: false });
  const setActive = (tab: TabId) => { setActiveTab(tab); setVisited(v => (v[tab] ? v : { ...v, [tab]: true })); };
  const [about, setAbout] = useState(false);
  const health = useHealth();
  const current = health.isError ? undefined : health.data;

  return (
    <div className="app-shell">
      <AppHeader result={current} error={health.isError} onAbout={() => setAbout(true)} />

      <main className="main-content">
        <Tabs active={active} onChange={setActive} />
        <DegradedBanner result={current} />

        {/* Tab Panels */}
        <div role="tabpanel" id="panel-experiment" aria-labelledby="tab-experiment" hidden={active !== 'experiment'}>
          <ExperimentTab />
        </div>
        <div role="tabpanel" id="panel-evidence" aria-labelledby="tab-evidence" hidden={active !== 'evidence'}>
          {visited.evidence && <EvidenceTab />}
        </div>
        <div role="tabpanel" id="panel-research" aria-labelledby="tab-research" hidden={active !== 'research'}>
          {visited.research && <ResearchTab />}
        </div>

        {/* System Telemetry Section */}
        <section className="system-section">
          <div className="system-heading">
            <h2>Status Infrastruktur & Layanan</h2>
            <button className="refresh-button" onClick={() => void health.refetch()}>
              <RefreshCw size={12} /> Periksa Status
            </button>
          </div>
          {health.isError && <div className="connection-error"><WifiOff size={16} />Koneksi backend belum terhubung</div>}
          <div className="service-strip">
            {services.map(([k, name, Icon]) => {
              const isReady = current?.data[k] === true;
              return (
                <div className="service-pill" key={k}>
                  <Icon size={14} style={{ color: isReady ? 'var(--status-pass-ink)' : 'var(--ink-faint)' }} />
                  <strong>{name}</strong>
                  <span className="service-pill-state">{isReady ? 'Siap' : 'Inisialisasi…'}</span>
                </div>
              );
            })}
          </div>
        </section>
      </main>

      <footer className="app-footer main-content">
        <div>
          <strong>Rimula Agents</strong>
          <span className="footer-dot">—</span>
          <span>Team Codingbang (Nicholas Edmund, Marshal Aufa, Tubagus Dafa, David Alexander)</span>
        </div>
        <div>
          <span>PT Paragon Technology and Innovation</span>
          <span className="footer-dot">·</span>
          <span>UI Hackathon 2026</span>
        </div>
      </footer>

      {about && (
        <div className="modal-backdrop" onClick={() => setAbout(false)}>
          <div className="modal-container" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true">
            <button className="modal-close-btn" aria-label="Tutup modal" onClick={() => setAbout(false)}>
              <X size={16} />
            </button>
            <DataDialogContent onClose={() => setAbout(false)} />
          </div>
        </div>
      )}
    </div>
  );
}
