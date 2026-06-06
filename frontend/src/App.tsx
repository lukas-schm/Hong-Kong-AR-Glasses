import { ErrorBoundary } from './components/ErrorBoundary';
import { LangProvider } from './i18n';
import { MonitorApp } from './components/Monitor/MonitorApp';
import './App.css';

/* ────────────────────────────────────────────────────────────────────────
   Single view: the model monitor. It hosts the interactive G2 HUD
   (tap to talk — say a patient name, query a vital, chart a value, or
   simulate an intervention) and a live console of the model's I/O.
   ──────────────────────────────────────────────────────────────────────── */

export default function App() {
  return (
    <ErrorBoundary>
      <LangProvider>
        <MonitorApp />
      </LangProvider>
    </ErrorBoundary>
  );
}
