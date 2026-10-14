import React, { useState } from 'react';
import { Connection, ConnectionInput, REGION_LABEL, api, errorMessage } from '../api';
import { ConnectionForm } from '../forms';
import { Empty, ErrorBox, Loading, useLoad } from '../ui';

export function ConnectionsPage() {
  const connections = useLoad(() => api.listConnections(), []);
  const [form, setForm] = useState<'new' | Connection | null>(null);
  const [error, setError] = useState('');

  const save = async (v: ConnectionInput) => {
    if (form === 'new') await api.createConnection(v);
    else if (form) await api.updateConnection(form.id, v);
    setForm(null);
    connections.reload();
  };

  const remove = async (c: Connection) => {
    if (!window.confirm(`Excluir a conexão "${c.name}"?`)) return;
    setError('');
    try {
      await api.deleteConnection(c.id);
      connections.reload();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <section aria-labelledby="connections-title">
      <div className="toolbar">
        <h2 id="connections-title">Conexões Veracode</h2>
        <button type="button" className="btn primary" onClick={() => setForm('new')} disabled={form !== null}>
          Nova conexão
        </button>
      </div>
      <p className="muted">
        Somente metadados e a referência da credencial. Segredos ficam fora do banco e nunca trafegam pela interface.
      </p>
      {error && <ErrorBox message={error} />}
      {form !== null && (
        <ConnectionForm
          key={form === 'new' ? 'new' : form.id}
          initial={form === 'new' ? undefined : form}
          onSave={save}
          onCancel={() => setForm(null)}
        />
      )}
      {connections.error ? (
        <ErrorBox message={`Falha ao carregar conexões: ${connections.error}`} onRetry={connections.reload} />
      ) : connections.loading && !connections.data ? (
        <Loading label="Carregando conexões…" />
      ) : !connections.data?.items.length ? (
        <Empty>Nenhuma conexão cadastrada.</Empty>
      ) : (
        <table aria-label="Lista de conexões">
          <thead>
            <tr>
              <th>Nome</th>
              <th>Região</th>
              <th>Referência da credencial</th>
              <th>Em uso</th>
              <th>Ações</th>
            </tr>
          </thead>
          <tbody>
            {connections.data.items.map((c) => {
              const inUse = c.client_count + c.subclient_count > 0;
              return (
                <tr key={c.id}>
                  <td>
                    {c.name}
                    {c.description && <div className="muted">{c.description}</div>}
                  </td>
                  <td>{REGION_LABEL[c.region]}</td>
                  <td>
                    <code>{c.credential_ref}</code>
                  </td>
                  <td>
                    {c.client_count} cliente(s), {c.subclient_count} subcliente(s)
                  </td>
                  <td className="row-actions">
                    <button type="button" className="btn small" onClick={() => setForm(c)} disabled={form !== null}>
                      Editar
                    </button>
                    <button
                      type="button"
                      className="btn small danger"
                      disabled={inUse}
                      title={inUse ? 'Conexão em uso: remova as referências antes' : 'Excluir conexão'}
                      onClick={() => remove(c)}
                    >
                      Excluir
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
