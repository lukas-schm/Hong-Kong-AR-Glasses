import { useEffect, useState } from 'react';
import { ErrorBoundary } from './components/ErrorBoundary';
import { LangProvider } from './i18n';
import { MonitorApp } from './components/Monitor/MonitorApp';
import { CDARSWorkbench } from './components/HKEHR/CDARSWorkbench';
import './App.css';

/* ────────────────────────────────────────────────────────────────────────
   Two surfaces over one CDARS backend, by hash route:

     #monitor (default) — Emily: the voice-first CDSS. Hosts the live G2 HUD
                          (driven by voice + temple buttons) and a plain-
                          language console of what the system is doing.
     #cdars             — the CDARS cohort workbench (territory-wide extracts,
                          audit trail), with an "Open in Emily" hand-off.
   ──────────────────────────────────────────────────────────────────────── */

type Route = 'monitor' | 'cdars';

function routeFromHash(): Route {
  const h = location.hash.replace('#', '').toLowerCase();
  if (h === 'cdars') return 'cdars';
  return 'monitor';
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash);
  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  return (
    <ErrorBoundary>
      <LangProvider>
        {route === 'cdars' ? <CDARSWorkbench /> : <MonitorApp />}
      </LangProvider>
    </ErrorBoundary>
  );
}
