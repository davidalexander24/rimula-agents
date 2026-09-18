import type { ReactNode } from 'react';
import { AlertTriangle, FlaskConical } from 'lucide-react';

export const Loading = ({ label = 'Memuat data…' }: { label?: string }) => (
  <div className="state" style={{ gap: '16px' }}>
    <div className="skeleton-pulse" style={{ width: '48px', height: '48px', borderRadius: 'var(--radius-full)' }} />
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
      <div className="skeleton-pulse" style={{ width: '120px', height: '14px', borderRadius: '4px' }} />
      <div className="skeleton-pulse" style={{ width: '80px', height: '10px', borderRadius: '4px', opacity: 0.7 }} />
    </div>
    <span style={{ fontWeight: 600, color: 'var(--ink-muted)', marginTop: '8px', fontSize: '12px' }}>{label}</span>
  </div>
);

export const Empty = ({ title, children }: { title: string; children?: ReactNode }) => (
  <div className="empty-state">
    <div style={{ width: '52px', height: '52px', borderRadius: 'var(--radius-xs)', background: 'var(--bg-surface-tint)', border: '1.5px solid var(--border-ink)', display: 'grid', placeItems: 'center', color: 'var(--ink-primary)', marginBottom: '12px', boxShadow: 'var(--shadow-paper)' }}>
      <FlaskConical size={24} strokeWidth={1.8} />
    </div>
    <h3>{title}</h3>
    {children && <p>{children}</p>}
  </div>
);

export const ErrorState = ({ error, retry }: { error: unknown; retry?: () => void }) => (
  <div className="state error-state">
    <div style={{ width: '40px', height: '40px', borderRadius: 'var(--radius-xs)', background: 'var(--status-blocked-bg)', border: '1.5px solid var(--status-blocked-border)', display: 'grid', placeItems: 'center', color: 'var(--status-blocked-ink)', marginBottom: '8px' }}>
      <AlertTriangle size={20} />
    </div>
    <span style={{ fontWeight: 700, maxWidth: '440px', lineHeight: 1.5, color: 'var(--status-blocked-ink)' }}>
      {error instanceof Error ? error.message : 'Data belum tersedia.'}
    </span>
    {retry && <button className="secondary-button" style={{ marginTop: '10px' }} onClick={retry}>Coba lagi</button>}
  </div>
);
