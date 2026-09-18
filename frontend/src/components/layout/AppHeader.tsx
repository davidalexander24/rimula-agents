import { Info, Layers, FlaskConical, Cpu, BookOpen } from 'lucide-react';
import type { Envelope, Health } from '../../api/types';

export function AppHeader({ result, error, onAbout }: { result?: Envelope<Health>; error: boolean; onAbout: () => void }) {
  const health = error ? undefined : result?.data;
  const mode = error ? undefined : result?.mode;

  return (
    <header className="app-header">
      <a className="brand" href="./" aria-label="Rimula Agents">
        <img src="./logo.png" alt="Rimula Agents" className="brand-logo-img" />
        <div className="brand-title">
          <span className="brand-name">Rimula</span>
          <span className="brand-name-sub">Agents</span>
        </div>
      </a>

      <div className="header-meta" aria-live="polite">
        <div
          className="system-capsule"
          data-tooltip={`LLM: ${health?.llm_ready ? 'Qwen 30B (Lokal)' : 'Degraded'} | Lab: ${health?.virtual_lab_variant ?? 'Emulsi Skincare'}`}
        >
          <span className={`capsule-dot ${mode === 'live' ? 'dot-ready' : 'dot-degraded'}`} />
          <span className="capsule-status">
            {error ? 'Tidak Terhubung' : mode === 'live' ? 'Sistem Siap' : (mode ?? 'Menghubungkan')}
          </span>
          <span className="capsule-sep" />
          <span className="capsule-model">
            {health?.model_version ? health.model_version : 'gp-global-v5'}
          </span>
        </div>

        <button className="ghost-button" onClick={onAbout}>
          <Info size={14} />
          <span>Metodologi</span>
        </button>
      </div>
    </header>
  );
}

export function DataDialogContent({ onClose }: { onClose?: () => void }) {
  return (
    <div className="dialog-content-body">
      <div className="dialog-header">
        <span className="dialog-badge">TRANSPARANSI DATA & SAINS</span>
        <h2 className="dialog-title">Sains Terukur di Balik Setiap Formula</h2>
        <p className="dialog-subtitle">
          Rimula Agents adalah <strong>Decision Support System (DSS)</strong> untuk R&D Formulator Paragon.
          Prediksi matematis dan bukti literatur memandu perencanaan eksperimen, sementara keputusan akhir tetap di tangan formulator.
        </p>
      </div>

      <div className="pillars-grid">
        <div className="pillar-card">
          <div className="pillar-head">
            <span className="pillar-icon"><Layers size={16} /></span>
            <strong>Model & Optimasi</strong>
          </div>
          <p>
            Gaussian Process Regressor dengan Bayesian Optimization (scikit-learn & BoTorch). Memprediksi viskositas, pH, dan droplet D50 dengan interval keyakinan 95% CI.
          </p>
        </div>

        <div className="pillar-card">
          <div className="pillar-head">
            <span className="pillar-icon"><FlaskConical size={16} /></span>
            <strong>Virtual Lab Emulsi</strong>
          </div>
          <p>
            Simulator kinetika formulasi dengan persamaan terbuka untuk viskositas, pH, stabilitas fase, dan ukuran droplet emulsi D50.
          </p>
        </div>

        <div className="pillar-card">
          <div className="pillar-head">
            <span className="pillar-icon"><Cpu size={16} /></span>
            <strong>Infrastruktur Komputasi</strong>
          </div>
          <p>
            Akselerasi hardware NVIDIA L40S GPU (12GB VRAM) dan model lokal Qwen 30B Instruct (llama.cpp) pada platform Lintasarta Cloudeka.
          </p>
        </div>

        <div className="pillar-card">
          <div className="pillar-head">
            <span className="pillar-icon"><BookOpen size={16} /></span>
            <strong>Kurasi Literatur & Pasar</strong>
          </div>
          <p>
            Terhubung dengan Europe PMC REST API untuk validasi bukti ilmiah dan Open Beauty Facts (ODbL) untuk prevalensi bahan kosmetik nyata.
          </p>
        </div>
      </div>

      {onClose && (
        <div className="dialog-footer">
          <button className="primary-button" onClick={onClose}>
            Mengerti & Lanjutkan
          </button>
        </div>
      )}
    </div>
  );
}
