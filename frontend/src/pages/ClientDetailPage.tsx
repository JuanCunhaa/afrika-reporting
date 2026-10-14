import React, { useState } from 'react';
import { Client, ClientInput, Connection, REPORT_MODE_LABEL, Subclient, SubclientInput, api, errorMessage } from '../api';
import { ClientForm, SubclientForm } from '../forms';
import { Empty, ErrorBox, Loading, StatusBadge, fmtDate, useLoad } from '../ui';

const SOURCE_LABEL: Record<Subclient['connection_source'], string> = {
  subclient: 'Sobrescrita',
  client: 'Herdada do cliente',
  none: 'Sem conexão',
};

export function ClientDetailPage({ id, navigate }: { id: string; navigate: (path: string) => void }) {
  const client = useLoad(() => api.getClient(id), [id]);
  const subclients = useLoad(() => api.listSubclients(id), [id]);
  const connections = useLoad(() => api.listConnections(), [id]);
  const [editing, setEditing] = useState(false);
  const [actionError, setActionError] = useState('');

  if (client.error)
    return (
      <section>
        <a href="#/clients">← Clientes</a>
        <ErrorBox message={`Falha ao carregar cliente: ${client.error}`} onRetry={client.reload} />
      </section>
    );
  if (client.loading && !client.data) return <Loading label="Carregando cliente…" />;
  const c = client.data!;

  const refresh = () => {
    client.reload();
    subclients.reload();
  };
  const run = async (fn: () => Promise<unknown>) => {
    setActionError('');
    try {
      await fn();
      refresh();
    } catch (e) {
      setActionError(errorMessage(e));
    }
  };

  const save = async (v: ClientInput) => {
    await api.updateClient(c.id, v);
    setEditing(false);
    refresh();
  };

  const remove = async () => {
    if (!window.confirm(`Excluir definitivamente o cliente "${c.name}"?`)) return;
    setActionError('');
    try {
      await api.deleteClient(c.id);
      navigate('/clients');
    } catch (e) {
      setActionError(errorMessage(e));
    }
  };

  const deleteBlocked = c.is_active
    ? 'Desative o cliente antes de excluí-lo.'
    : c.subclient_count > 0
      ? 'Cliente possui subclientes: mantenha-o desativado ou exclua os subclientes antes.'
      : '';

  return (
    <section aria-labelledby="client-title">
      <a href="#/clients">← Clientes</a>
      <div className="toolbar">
        <h2 id="client-title">{c.name}</h2>
        <StatusBadge active={c.is_active} />
      </div>
      {actionError && <ErrorBox message={actionError} />}

      {editing ? (
        <ClientForm
          initial={c}
          connections={connections.data?.items ?? []}
          onSave={save}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <article className="panel">
          <dl className="details">
            <dt>Nome de exibição</dt>
            <dd>{c.display_name}</dd>
            <dt>Descrição</dt>
            <dd>{c.description ?? <span className="muted">—</span>}</dd>
            <dt>Modo de relatório</dt>
            <dd data-testid="client-report-mode">{REPORT_MODE_LABEL[c.report_mode]}</dd>
            <dt>Conexão Veracode</dt>
            <dd data-testid="client-connection">{c.connection ? connectionText(c.connection) : 'Nenhuma'}</dd>
            <dt>Subclientes</dt>
            <dd>
              {c.subclient_count} ({c.active_subclient_count} ativos)
            </dd>
            <dt>Criado em</dt>
            <dd>{fmtDate(c.created_at)}</dd>
            <dt>Atualizado em</dt>
            <dd>{fmtDate(c.updated_at)}</dd>
            <dt>ID</dt>
            <dd>
              <code>{c.id}</code>
            </dd>
          </dl>
          {c.report_mode !== 'consolidated' && c.subclient_count === 0 && (
            <p className="notice">Modo inclui relatório por subcliente, mas o cliente ainda não possui subclientes.</p>
          )}
          <div className="actions">
            <button type="button" className="btn" onClick={() => setEditing(true)}>
              Editar
            </button>
            <a className="btn" href={`#/veracode/clients/${c.id}`}>
              Veracode
            </a>
            <button
              type="button"
              className="btn"
              onClick={() => run(() => api.updateClient(c.id, { is_active: !c.is_active }))}
            >
              {c.is_active ? 'Desativar' : 'Ativar'}
            </button>
            <button
              type="button"
              className="btn danger"
              onClick={remove}
              disabled={Boolean(deleteBlocked)}
              title={deleteBlocked || 'Excluir cliente'}
            >
              Excluir
            </button>
          </div>
          {deleteBlocked && <p className="muted">Exclusão indisponível: {deleteBlocked}</p>}
        </article>
      )}

      <SubclientsSection
        client={c}
        subclients={subclients}
        connections={connections.data?.items ?? []}
        onChanged={refresh}
      />
    </section>
  );
}

const connectionText = (conn: { name: string; credential_ref: string }) => `${conn.name} (${conn.credential_ref})`;

function SubclientsSection(props: {
  client: Client;
  subclients: ReturnType<typeof useLoad<{ items: Subclient[]; total: number }>>;
  connections: Connection[];
  onChanged: () => void;
}) {
  const { client, subclients, connections, onChanged } = props;
  const [form, setForm] = useState<'new' | Subclient | null>(null);
  const [error, setError] = useState('');

  const run = async (fn: () => Promise<unknown>) => {
    setError('');
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const save = async (v: SubclientInput) => {
    if (form === 'new') await api.createSubclient(client.id, v);
    else if (form) await api.updateSubclient(form.id, v);
    setForm(null);
    onChanged();
  };

  return (
    <section aria-labelledby="subclients-title" className="subsection">
      <div className="toolbar">
        <h3 id="subclients-title">Subclientes</h3>
        <button type="button" className="btn primary" onClick={() => setForm('new')} disabled={form !== null}>
          Novo subcliente
        </button>
      </div>
      {error && <ErrorBox message={error} />}
      {form !== null && (
        <SubclientForm
          key={form === 'new' ? 'new' : form.id}
          initial={form === 'new' ? undefined : form}
          clientConnectionName={client.connection?.name ?? null}
          connections={connections}
          onSave={save}
          onCancel={() => setForm(null)}
        />
      )}
      {subclients.error ? (
        <ErrorBox message={`Falha ao carregar subclientes: ${subclients.error}`} onRetry={subclients.reload} />
      ) : subclients.loading && !subclients.data ? (
        <Loading label="Carregando subclientes…" />
      ) : !subclients.data?.items.length ? (
        <Empty>Cliente sem subclientes. Relatórios usam somente o escopo do cliente.</Empty>
      ) : (
        <table aria-label="Lista de subclientes">
          <thead>
            <tr>
              <th>Nome</th>
              <th>Status</th>
              <th>Conexão efetiva</th>
              <th>Ações</th>
            </tr>
          </thead>
          <tbody>
            {subclients.data.items.map((s) => (
              <tr key={s.id} data-testid={`subclient-${s.name}`}>
                <td>
                  {s.name}
                  {s.display_name !== s.name && <div className="muted">{s.display_name}</div>}
                </td>
                <td>
                  <StatusBadge
                    active={s.effective_active}
                    label={s.is_active && !s.effective_active ? 'Inativo (cliente inativo)' : undefined}
                  />
                </td>
                <td>
                  {s.effective_connection ? connectionText(s.effective_connection) : 'Nenhuma'}{' '}
                  <span className={`badge source-${s.connection_source}`}>{SOURCE_LABEL[s.connection_source]}</span>
                </td>
                <td className="row-actions">
                  <a className="btn small" href={`#/veracode/subclients/${s.id}`} aria-label={`Veracode do subcliente ${s.name}`}>
                    Veracode
                  </a>
                  <button type="button" className="btn small" onClick={() => setForm(s)} disabled={form !== null}>
                    Editar
                  </button>
                  <button
                    type="button"
                    className="btn small"
                    onClick={() => run(() => api.updateSubclient(s.id, { is_active: !s.is_active }))}
                  >
                    {s.is_active ? 'Desativar' : 'Ativar'}
                  </button>
                  <button
                    type="button"
                    className="btn small danger"
                    disabled={s.is_active}
                    title={s.is_active ? 'Desative antes de excluir' : 'Excluir subcliente'}
                    onClick={() => {
                      if (window.confirm(`Excluir definitivamente o subcliente "${s.name}"?`))
                        run(() => api.deleteSubclient(s.id));
                    }}
                  >
                    Excluir
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
