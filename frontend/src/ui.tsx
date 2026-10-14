import React, { useCallback, useEffect, useState } from 'react';
import { ApiError, errorMessage } from './api';

export function useLoad<T>(load: () => Promise<T>, deps: React.DependencyList) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError('');
    load()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(errorMessage(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { data, error, loading, reload };
}

export const Loading = ({ label }: { label: string }) => (
  <p role="status" className="muted">
    {label}
  </p>
);

export const ErrorBox = ({ message, onRetry }: { message: string; onRetry?: () => void }) => (
  <div role="alert" className="error-box">
    <span>{message}</span>
    {onRetry && (
      <button type="button" className="btn" onClick={onRetry}>
        Tentar novamente
      </button>
    )}
  </div>
);

export const Empty = ({ children }: { children: React.ReactNode }) => <p className="empty">{children}</p>;

export const StatusBadge = ({ active, label }: { active: boolean; label?: string }) => (
  <span className={`badge ${active ? 'ok' : 'off'}`}>{label ?? (active ? 'Ativo' : 'Inativo')}</span>
);

export type FieldErrors = Record<string, string>;

// Converte erro da API em mensagens por campo (422/409) + mensagem geral.
export function apiFieldErrors(e: unknown): { fields: FieldErrors; general: string } {
  if (!(e instanceof ApiError)) return { fields: {}, general: errorMessage(e) };
  const fields: FieldErrors = {};
  for (const d of e.details) {
    const name = d.field.split('.').pop() ?? '';
    if (name) fields[name] = d.message;
  }
  if (e.code === 'duplicate_name') fields.name = e.message;
  if (e.code === 'connection_not_found') fields.connection_id = e.message;
  return { fields, general: Object.keys(fields).length ? '' : e.message };
}

type FieldProps = {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  children: React.ReactElement<{ id?: string; 'aria-invalid'?: boolean; 'aria-describedby'?: string }>;
};

export function Field({ id, label, error, hint, children }: FieldProps) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ') || undefined;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {React.cloneElement(children, { id, 'aria-invalid': Boolean(error), 'aria-describedby': describedBy })}
      {hint && (
        <small id={`${id}-hint`} className="muted">
          {hint}
        </small>
      )}
      {error && (
        <small id={`${id}-error`} className="field-error">
          {error}
        </small>
      )}
    </div>
  );
}

export const fmtDate = (iso: string) => new Date(iso).toLocaleString('pt-BR');
