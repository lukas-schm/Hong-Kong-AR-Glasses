/* ────────────────────────────────────────────────────────────────────────
   Server base resolution.

   The plugin runs in the Even App's WebView on the phone, so the CDARS
   server must be reachable over the network (LAN IP or Tailscale) — not
   `localhost`. Resolution order:

     1. ?server=http://… query param (baked into the sideload QR by
        `npm run qr`, then persisted)
     2. localStorage('cdars_server')
     3. VITE_CDARS_SERVER build-time env
     4. http://localhost:8002 (simulator / desktop preview only)
   ──────────────────────────────────────────────────────────────────────── */

const KEY = 'cdars_server';

function resolve(): string {
  const qp = new URLSearchParams(location.search).get('server');
  if (qp) {
    try { localStorage.setItem(KEY, qp); } catch { /* private mode */ }
    return qp;
  }
  try {
    const saved = localStorage.getItem(KEY);
    if (saved) return saved;
  } catch { /* private mode */ }
  return import.meta.env.VITE_CDARS_SERVER ?? 'http://localhost:8002';
}

export const SERVER = resolve().replace(/\/$/, '');
export const WS_URL = `${SERVER.replace(/^http/, 'ws')}/api/v1/ws?role=glasses`;

export function setServer(url: string) {
  try { localStorage.setItem(KEY, url.replace(/\/$/, '')); } catch { /* ignore */ }
  location.search = `?server=${encodeURIComponent(url)}`;
}
