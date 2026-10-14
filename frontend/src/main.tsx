import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import { ClientDetailPage } from './pages/ClientDetailPage';
import { ClientsPage } from './pages/ClientsPage';
import { ConnectionsPage } from './pages/ConnectionsPage';

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

  let page: React.ReactNode;
  if (path === '/connections') page = <ConnectionsPage />;
  else if (clientMatch) page = <ClientDetailPage key={clientMatch[1]} id={clientMatch[1]} navigate={navigate} />;
  else page = <ClientsPage navigate={navigate} />;

  return (
    <main>
      <header>
        <small>AFRIKA / REPORTING</small>
        <h1>Central de relatórios AppSec</h1>
        <p>F01 — cadastro de clientes, subclientes e conexões. Sem conexão Veracode nesta fase.</p>
        <nav aria-label="Principal">
          <a href="#/clients" aria-current={path.startsWith('/clients') ? 'page' : undefined}>
            Clientes
          </a>
          <a href="#/connections" aria-current={path === '/connections' ? 'page' : undefined}>
            Conexões
          </a>
        </nav>
      </header>
      {page}
      <footer>F01 • API local sem autenticação — não expor publicamente • Nenhuma métrica oficial</footer>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
