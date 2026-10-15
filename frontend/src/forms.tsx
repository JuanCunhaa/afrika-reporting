import React, { useState } from 'react';
import {
  ClientInput, Connection, ConnectionInput, DEFAULT_TIMEZONE, REGION_LABEL, REPORT_MODE_LABEL, Region, ReportMode,
  SubclientInput,
} from './api';
import { Field, FieldErrors, apiFieldErrors } from './ui';

const NAME_MAX = 120;
const DISPLAY_MAX = 200;
const DESCRIPTION_MAX = 2000;
const CREDENTIAL_REF = /^env:[A-Z][A-Z0-9_]{1,62}$/;

function validateNames(v: { name: string; display_name: string }, errors: FieldErrors) {
  if (!v.name.trim()) errors.name = 'Informe o nome.';
  else if (v.name.trim().length > NAME_MAX) errors.name = `Máximo de ${NAME_MAX} caracteres.`;
  if (v.display_name.trim().length > DISPLAY_MAX) errors.display_name = `Máximo de ${DISPLAY_MAX} caracteres.`;
}

type FormShellProps = {
  title: string;
  submitLabel: string;
  busy: boolean;
  general: string;
  onSubmit: () => void;
  onCancel: () => void;
  children: React.ReactNode;
};

function FormShell({ title, submitLabel, busy, general, onSubmit, onCancel, children }: FormShellProps) {
  return (
    <form
      className="panel form"
      aria-label={title}
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <h3>{title}</h3>
      {children}
      {general && (
        <p role="alert" className="field-error">
          {general}
        </p>
      )}
      <div className="actions">
        <button type="submit" className="btn primary" disabled={busy}>
          {busy ? 'Salvando…' : submitLabel}
        </button>
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>
          Cancelar
        </button>
      </div>
    </form>
  );
}

function useSubmit<T>(save: (v: T) => Promise<unknown>) {
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [general, setGeneral] = useState('');
  const submit = async (values: T, localErrors: FieldErrors) => {
    setErrors(localErrors);
    setGeneral('');
    if (Object.keys(localErrors).length) return;
    setBusy(true);
    try {
      await save(values);
    } catch (e) {
      const { fields, general } = apiFieldErrors(e);
      setErrors(fields);
      setGeneral(general);
    } finally {
      setBusy(false);
    }
  };
  return { busy, errors, general, submit };
}

const nullIfBlank = (s: string) => (s.trim() ? s.trim() : null);

// ---------------------------------------------------------------- cliente

export function ClientForm(props: {
  initial?: ClientInput;
  connections: Connection[];
  onSave: (v: ClientInput) => Promise<unknown>;
  onCancel: () => void;
}) {
  const [v, setV] = useState({
    name: props.initial?.name ?? '',
    display_name: props.initial?.display_name ?? '',
    description: props.initial?.description ?? '',
    is_active: props.initial?.is_active ?? true,
    report_mode: props.initial?.report_mode ?? ('consolidated' as ReportMode),
    connection_id: props.initial?.connection_id ?? '',
    timezone: props.initial?.timezone ?? DEFAULT_TIMEZONE,
  });
  const { busy, errors, general, submit } = useSubmit(props.onSave);
  const set = (patch: Partial<typeof v>) => setV((old) => ({ ...old, ...patch }));

  const onSubmit = () => {
    const e: FieldErrors = {};
    validateNames(v, e);
    if (v.description.length > DESCRIPTION_MAX) e.description = `Máximo de ${DESCRIPTION_MAX} caracteres.`;
    submit(
      {
        name: v.name.trim(),
        display_name: v.display_name.trim() || v.name.trim(),
        description: nullIfBlank(v.description),
        is_active: v.is_active,
        report_mode: v.report_mode,
        connection_id: v.connection_id || null,
        timezone: v.timezone.trim() || DEFAULT_TIMEZONE,
      },
      e,
    );
  };

  return (
    <FormShell
      title={props.initial ? 'Editar cliente' : 'Novo cliente'}
      submitLabel={props.initial ? 'Salvar alterações' : 'Cadastrar cliente'}
      busy={busy}
      general={general}
      onSubmit={onSubmit}
      onCancel={props.onCancel}
    >
      <Field id="client-name" label="Nome *" error={errors.name}>
        <input value={v.name} onChange={(e) => set({ name: e.target.value })} />
      </Field>
      <Field id="client-display" label="Nome de exibição" error={errors.display_name} hint="Vazio = igual ao nome.">
        <input value={v.display_name} onChange={(e) => set({ display_name: e.target.value })} />
      </Field>
      <Field id="client-description" label="Descrição" error={errors.description}>
        <textarea rows={2} value={v.description} onChange={(e) => set({ description: e.target.value })} />
      </Field>
      <fieldset className="field">
        <legend>Modo de relatório</legend>
        {(Object.keys(REPORT_MODE_LABEL) as ReportMode[]).map((mode) => (
          <label key={mode} className="inline">
            <input
              type="radio"
              name="report_mode"
              value={mode}
              checked={v.report_mode === mode}
              onChange={() => set({ report_mode: mode })}
            />
            {REPORT_MODE_LABEL[mode]}
          </label>
        ))}
      </fieldset>
      <Field id="client-connection" label="Conexão Veracode" error={errors.connection_id}>
        <select value={v.connection_id} onChange={(e) => set({ connection_id: e.target.value })}>
          <option value="">— Nenhuma —</option>
          {props.connections.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </Field>
      <Field
        id="client-timezone"
        label="Fuso horário das competências"
        error={errors.timezone}
        hint="Nome IANA (regras históricas). Padrão: America/Sao_Paulo. Subclientes herdam."
      >
        <input value={v.timezone} onChange={(e) => set({ timezone: e.target.value })} />
      </Field>
      <label className="inline">
        <input type="checkbox" checked={v.is_active} onChange={(e) => set({ is_active: e.target.checked })} />
        Ativo
      </label>
    </FormShell>
  );
}

// ---------------------------------------------------------------- subcliente

export function SubclientForm(props: {
  initial?: SubclientInput;
  clientConnectionName: string | null;
  connections: Connection[];
  onSave: (v: SubclientInput) => Promise<unknown>;
  onCancel: () => void;
}) {
  const [v, setV] = useState({
    name: props.initial?.name ?? '',
    display_name: props.initial?.display_name ?? '',
    is_active: props.initial?.is_active ?? true,
    connection_id: props.initial?.connection_id ?? '',
  });
  const { busy, errors, general, submit } = useSubmit(props.onSave);
  const set = (patch: Partial<typeof v>) => setV((old) => ({ ...old, ...patch }));
  const inheritLabel = props.clientConnectionName
    ? `— Herdar do cliente (${props.clientConnectionName}) —`
    : '— Herdar do cliente (nenhuma) —';

  const onSubmit = () => {
    const e: FieldErrors = {};
    validateNames(v, e);
    submit(
      {
        name: v.name.trim(),
        display_name: v.display_name.trim() || v.name.trim(),
        is_active: v.is_active,
        connection_id: v.connection_id || null,
      },
      e,
    );
  };

  return (
    <FormShell
      title={props.initial ? 'Editar subcliente' : 'Novo subcliente'}
      submitLabel={props.initial ? 'Salvar subcliente' : 'Cadastrar subcliente'}
      busy={busy}
      general={general}
      onSubmit={onSubmit}
      onCancel={props.onCancel}
    >
      <Field id="sub-name" label="Nome *" error={errors.name}>
        <input value={v.name} onChange={(e) => set({ name: e.target.value })} />
      </Field>
      <Field id="sub-display" label="Nome de exibição" error={errors.display_name} hint="Vazio = igual ao nome.">
        <input value={v.display_name} onChange={(e) => set({ display_name: e.target.value })} />
      </Field>
      <Field id="sub-connection" label="Conexão Veracode" error={errors.connection_id}>
        <select value={v.connection_id} onChange={(e) => set({ connection_id: e.target.value })}>
          <option value="">{inheritLabel}</option>
          {props.connections.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </Field>
      <label className="inline">
        <input type="checkbox" checked={v.is_active} onChange={(e) => set({ is_active: e.target.checked })} />
        Ativo
      </label>
    </FormShell>
  );
}

// ---------------------------------------------------------------- conexão

export function ConnectionForm(props: {
  initial?: ConnectionInput;
  onSave: (v: ConnectionInput) => Promise<unknown>;
  onCancel: () => void;
}) {
  const [v, setV] = useState({
    name: props.initial?.name ?? '',
    description: props.initial?.description ?? '',
    region: props.initial?.region ?? ('commercial' as Region),
    credential_ref: props.initial?.credential_ref ?? 'env:',
  });
  const { busy, errors, general, submit } = useSubmit(props.onSave);
  const set = (patch: Partial<typeof v>) => setV((old) => ({ ...old, ...patch }));

  const onSubmit = () => {
    const e: FieldErrors = {};
    validateNames({ name: v.name, display_name: '' }, e);
    if (!CREDENTIAL_REF.test(v.credential_ref.trim()))
      e.credential_ref = 'Use env:NOME_DA_VARIAVEL (letras maiúsculas, dígitos e _).';
    submit(
      {
        name: v.name.trim(),
        description: nullIfBlank(v.description),
        region: v.region,
        credential_ref: v.credential_ref.trim(),
      },
      e,
    );
  };

  return (
    <FormShell
      title={props.initial ? 'Editar conexão' : 'Nova conexão'}
      submitLabel={props.initial ? 'Salvar conexão' : 'Cadastrar conexão'}
      busy={busy}
      general={general}
      onSubmit={onSubmit}
      onCancel={props.onCancel}
    >
      <p className="notice">
        Nunca cole API ID ou API Key aqui. Informe apenas o <strong>nome</strong> da variável de ambiente do backend que
        guardará a credencial. Nenhuma chamada à Veracode é feita nesta fase.
      </p>
      <Field id="conn-name" label="Nome *" error={errors.name}>
        <input value={v.name} onChange={(e) => set({ name: e.target.value })} />
      </Field>
      <Field id="conn-region" label="Região">
        <select value={v.region} onChange={(e) => set({ region: e.target.value as Region })}>
          {(Object.keys(REGION_LABEL) as Region[]).map((r) => (
            <option key={r} value={r}>
              {REGION_LABEL[r]}
            </option>
          ))}
        </select>
      </Field>
      <Field
        id="conn-ref"
        label="Referência da credencial *"
        error={errors.credential_ref}
        hint="Ex.: env:VERACODE_CLIENTE_A"
      >
        <input
          value={v.credential_ref}
          autoComplete="off"
          spellCheck={false}
          onChange={(e) => set({ credential_ref: e.target.value })}
        />
      </Field>
      <Field id="conn-description" label="Descrição" error={errors.description}>
        <textarea rows={2} value={v.description} onChange={(e) => set({ description: e.target.value })} />
      </Field>
    </FormShell>
  );
}
