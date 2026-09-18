import { FlaskConical, ChartNoAxesCombined, Network } from 'lucide-react';
import type { KeyboardEvent } from 'react';

export const tabs = [
  { id: 'experiment', label: 'Eksperimen Formulasi', Icon: FlaskConical },
  { id: 'evidence', label: 'Bukti & Evaluasi', Icon: ChartNoAxesCombined },
  { id: 'research', label: 'Agent & Riset Pasar', Icon: Network },
] as const;

export type TabId = typeof tabs[number]['id'];

export function Tabs({ active, onChange }: { active: TabId; onChange: (value: TabId) => void }) {
  function onKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else return;
    event.preventDefault();
    onChange(tabs[next].id);
    document.getElementById('tab-' + tabs[next].id)?.focus();
  }

  return (
    <nav className="tabs-bar" aria-label="Bagian workspace">
      <div role="tablist" aria-label="Workspace Rimula Agents">
        {tabs.map(({ id, label, Icon }, i) => (
          <button
            key={id}
            id={'tab-' + id}
            role="tab"
            aria-selected={active === id}
            aria-controls={'panel-' + id}
            tabIndex={active === id ? 0 : -1}
            onKeyDown={e => onKey(e, i)}
            onClick={() => onChange(id)}
          >
            <Icon size={15} />
            <span>{label}</span>
            {id === 'research' && <span className="priority-label">P1</span>}
          </button>
        ))}
      </div>
    </nav>
  );
}
