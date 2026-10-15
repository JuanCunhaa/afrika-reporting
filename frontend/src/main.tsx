import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import { ClientDetailPage } from './pages/ClientDetailPage';
import { ClientsPage } from './pages/ClientsPage';
import { ConnectionsPage } from './pages/ConnectionsPage';
import { HistoryPage } from './pages/HistoryPage';
import { MetricsPage } from './pages/MetricsPage';
import { PresentationEditorPage } from './pages/PresentationEditorPage';
import { PresentationsPage } from './pages/PresentationsPage';
import { ReportingPage } from './pages/ReportingPage';
import { ScopesPage } from './pages/ScopesPage';
import { SnapshotsPage } from './pages/SnapshotsPage';
import { VeracodePage } from './pages/VeracodePage';

const currentPath = () => window.location.hash.replace(/^#/, '') || '/clients';

function useHashPath(): [string, (path: string) => void] {
  const [path, setPath] = useState(currentPath);
  useEffect(() => {
    const onChange = () => setPath(currentPath());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return [path, (p: string) => (window.location.hash = p)];
}

function App() {
  const [path, navigate] = useHashPath();
  const clientMatch = path.match(/^\/clients\/([0-9a-f-]{36})$/i);
  const veracodeMatch = path.match(/^\/veracode\/(clients|subclients)\/([0-9a-f-]{36})$/i);
  const scopesMatch = path.match(/^\/scopes\/clients\/([0-9a-f-]{36})$/i);
  const metricsMatch = path.match(/^\/metrics(?:\/clients\/([0-9a-f-]{36}))?$/i);
  const snapshotsMatch = path.match(/^\/snapshots(?:\/([0-9a-f-]{36})(?:\/(\d+))?)?$/i);
  const presentationMatch = path.match(/^\/presentations\/([0-9a-f-]{36})$/i);

  let page: React.ReactNode;
  if (path === '/connections') page = <ConnectionsPage />;
  else if (metricsMatch) page = <MetricsPage key={path} clientId={metricsMatch[1]} navigate={navigate} />;
  else if (snapshotsMatch)
    page = (
      <SnapshotsPage
        key={path}
        cid={snapshotsMatch[1]}
        n={snapshotsMatch[2] ? Number(snapshotsMatch[2]) : undefined}
        navigate={navigate}
      />
    );
  else if (path === '/history') page = <HistoryPage />;
  else if (path === '/presentations') page = <PresentationsPage navigate={navigate} />;
  else if (presentationMatch) page = <PresentationEditorPage key={presentationMatch[1]} pid={presentationMatch[1]} />;
  else if (path === '/reporting') page = <ReportingPage />;
  else if (veracodeMatch) {
    const kind = veracodeMatch[1] as 'clients' | 'subclients';
    page = <VeracodePage key={path} kind={kind} id={veracodeMatch[2]} />;
  }
  else if (scopesMatch) page = <ScopesPage key={path} clientId={scopesMatch[1]} />;
  else if (clientMatch) page = <ClientDetailPage key={clientMatch[1]} id={clientMatch[1]} navigate={navigate} />;
  else page = <ClientsPage navigate={navigate} />;

  return (
    <main>
      <header>
        <small>AFRIKA / REPORTING</small>
        <h1>Central de relatórios AppSec</h1>
        <p>F06A — cadastro, descoberta Veracode somente leitura, escopos, indicadores, snapshots aprovados, histórico e apresentações (tema provisório).</p>
        <nav aria-label="Principal">
          <a href="#/clients" aria-current={path.startsWith('/clients') || path.startsWith('/veracode') || path.startsWith('/scopes') ? 'page' : undefined}>
            Clientes
          </a>
          <a href="#/connections" aria-current={path === '/connections' ? 'page' : undefined}>
            Conexões
          </a>
          <a href="#/metrics" aria-current={path.startsWith('/metrics') ? 'page' : undefined}>
            Indicadores
          </a>
          <a href="#/snapshots" aria-current={path.startsWith('/snapshots') ? 'page' : undefined}>
            Competências
          </a>
          <a href="#/history" aria-current={path === '/history' ? 'page' : undefined}>
            Histórico
          </a>
          <a href="#/reporting" aria-current={path === '/reporting' ? 'page' : undefined}>
            Reporting
          </a>
          <a href="#/presentations" aria-current={path.startsWith('/presentations') ? 'page' : undefined}>
            Apresentações
          </a>
        </nav>
      </header>
      {page}
      <footer>F06A • API local (loopback) sem autenticação — operador/aprovador são declarados, não autenticados • Indicadores não homologados contra o dashboard</footer>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
