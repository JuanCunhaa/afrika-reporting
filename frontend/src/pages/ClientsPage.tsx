import React, { useState } from 'react';
import { ClientInput, REPORT_MODE_LABEL, StatusFilter, api } from '../api';
import { ClientForm } from '../forms';
import { Empty, ErrorBox, Loading, StatusBadge, useLoad } from '../ui';

const PAGE_SIZE = 20;

export function ClientsPage({ navigate }: { navigate: (path: string) => void }) {
  const [status, setStatus] = useState<StatusFilter>('all');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);

  const clients = useLoad(
    () => api.listClients({ limit: PAGE_SIZE, offset, status, q: query.trim() || undefined }),
    [offset, status, query],
  );
  const connections = useLoad(() => api.listConnections(), [creating]);

  const create = async (v: ClientInput) => {
    const c = await api.createClient(v);
    navigate(`/clients/${c.id}`);
  };

  const page = clients.data;
  const filtered = status !== 'all' || query.trim() !== '';

  return (
    <section aria-labelledby="clients-title">
      <div className="toolbar">
        <h2 id="clients-title">Clientes</h2>
        <button type="button" className="btn primary" onClick={() => setCreating(true)} disabled={creating}>
          Novo cliente
        </button>
      </div>

      {creating &&
        (connections.error ? (
          <ErrorBox message={connections.error} onRetry={connections.reload} />
        ) : connections.loading || !connections.data ? (
          <Loading label="Carregando conexões…" />
        ) : (
          <ClientForm connections={connections.data.items} onSave={create} onCancel={() => setCreating(false)} />
        ))}

      <div className="filters">
        <label>
          Buscar
          <input
            type="search"
            value={query}
            placeholder="Nome ou nome de exibição"
            onChange={(e) => {
              setQuery(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        <label>
          Status
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as StatusFilter);
              setOffset(0);
            }}
          >
            <option value="all">Todos</option>
            <option value="active">Ativos</option>
            <option value="inactive">Inativos</option>
          </select>
        </label>
      </div>

      {clients.error ? (
        <ErrorBox message={`Falha ao carregar clientes: ${clients.error}`} onRetry={clients.reload} />
      ) : clients.loading && !page ? (
        <Loading label="Carregando clientes…" />
      ) : !page || page.total === 0 ? (
        <Empty>
          {filtered
            ? 'Nenhum cliente encontrado para os filtros aplicados.'
            : 'Nenhum cliente cadastrado. Use “Novo cliente” para começar.'}
        </Empty>
      ) : (
        <>
          <table aria-label="Lista de clientes">
            <thead>
              <tr>
                <th>Nome</th>
                <th>Status</th>
                <th>Modo de relatório</th>
                <th>Subclientes</th>
                <th>Conexão</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((c) => (
                <tr key={c.id}>
                  <td>
                    <a href={`#/clients/${c.id}`}>{c.name}</a>
                    {c.display_name !== c.name && <div className="muted">{c.display_name}</div>}
                  </td>
                  <td>
                    <StatusBadge active={c.is_active} />
                  </td>
                  <td>{REPORT_MODE_LABEL[c.report_mode]}</td>
                  <td>{c.subclient_count || 'Sem subclientes'}</td>
                  <td>{c.connection?.name ?? <span className="muted">Nenhuma</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pager">
            <span>
              {page.offset + 1}–{page.offset + page.items.length} de {page.total}
            </span>
            <button
              type="button"
              className="btn"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Anterior
            </button>
            <button
              type="button"
              className="btn"
              disabled={offset + PAGE_SIZE >= page.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Próxima
            </button>
          </div>
        </>
      )}
    </section>
  );
}
