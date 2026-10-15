import React, { useEffect, useState } from 'react';
import { Subclient, api } from '../api';
import { OwnerKind } from '../snapshotsApi';
import { ErrorBox, Loading, useLoad } from '../ui';

export type Owner = { kind: OwnerKind; id: string; name: string; clientId: string; timezone: string };

// Seleção de dono (cliente principal ou subcliente) compartilhada pelas telas da F05.
export function OwnerPicker({ prefix, onChange }: { prefix: string; onChange: (o: Owner | null) => void }) {
  const clients = useLoad(() => api.listClients({ limit: 200, offset: 0, status: 'all' }), []);
  const [client, setClient] = useState('');
  const [sub, setSub] = useState('');
  const [subs, setSubs] = useState<Subclient[]>([]);

  useEffect(() => {
    setSub('');
    setSubs([]);
    if (client) api.listSubclients(client).then((p) => setSubs(p.items)).catch(() => setSubs([]));
  }, [client]);

  useEffect(() => {
    const c = clients.data?.items.find((x) => x.id === client);
    if (!c) return onChange(null);
    const s = subs.find((x) => x.id === sub);
    onChange(
      s
        ? { kind: 'subclient', id: s.id, name: `${c.name} / ${s.name}`, clientId: c.id, timezone: c.timezone }
        : { kind: 'client', id: c.id, name: c.name, clientId: c.id, timezone: c.timezone },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, sub, subs, clients.data]);

  if (clients.error) return <ErrorBox message={`Falha ao carregar clientes: ${clients.error}`} onRetry={clients.reload} />;
  if (clients.loading && !clients.data) return <Loading label="Carregando clientes…" />;
  return (
    <>
      <div className="field">
        <label htmlFor={`${prefix}-client`}>Cliente</label>
        <select id={`${prefix}-client`} value={client} onChange={(e) => setClient(e.target.value)}>
          <option value="">Selecione…</option>
          {clients.data!.items.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor={`${prefix}-owner`}>Escopo</label>
        <select id={`${prefix}-owner`} value={sub} onChange={(e) => setSub(e.target.value)} disabled={!client}>
          <option value="">Cliente principal</option>
          {subs.map((s) => (
            <option key={s.id} value={s.id}>
              Subcliente: {s.name}
            </option>
          ))}
        </select>
      </div>
    </>
  );
}

export function OperatorField({ id, value, onChange, label = 'Operador (declarado)' }: { id: string; value: string; onChange: (v: string) => void; label?: string }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} value={value} onChange={(e) => onChange(e.target.value)} maxLength={120} aria-describedby={`${id}-hint`} />
      <small id={`${id}-hint`} className="muted">
        Nome declarado, sem autenticação: registrado para rastreabilidade, não comprova identidade.
      </small>
    </div>
  );
}

export const shortValue = (v: unknown): string => {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean') return String(v);
  const o = v as Record<string, unknown>;
  if (typeof o.total === 'number') return `total ${o.total}`;
  if (typeof o.count === 'number') return String(o.count);
  const s = JSON.stringify(v);
  return s.length > 80 ? `${s.slice(0, 77)}…` : s;
};

export const Badge = ({ cls, children, testId }: { cls: string; children: React.ReactNode; testId?: string }) => (
  <span className={`badge ${cls}`} data-testid={testId}>
    {children}
  </span>
);
