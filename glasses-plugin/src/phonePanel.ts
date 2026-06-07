/* ────────────────────────────────────────────────────────────────────────
   Phone-side panel. The plugin's HTML renders inside the Even App's
   WebView on the phone — the glasses only ever see the container pages.
   So this DOM is a small ops surface: server URL, connection state, log.
   ──────────────────────────────────────────────────────────────────────── */
import { SERVER, setServer } from './config';

export interface PhonePanel {
  log: (line: string) => void;
  setConnected: (ok: boolean) => void;
}

export function mountPhonePanel(): PhonePanel {
  document.body.innerHTML = `
    <div style="font-family:ui-monospace,monospace;background:#000;color:#6cff9a;min-height:100vh;padding:16px">
      <h2 style="margin:0 0 4px">CDARS CDSS · Even G2</h2>
      <div id="conn" style="margin-bottom:12px">○ bus disconnected</div>
      <label style="font-size:12px;opacity:.7">CDARS server</label>
      <div style="display:flex;gap:8px;margin:4px 0 16px">
        <input id="srv" value="${SERVER}" style="flex:1;background:#0a1f10;color:#6cff9a;border:1px solid #2a5;padding:6px;font:inherit" />
        <button id="save" style="background:#143;color:#6cff9a;border:1px solid #2a5;padding:6px 12px;font:inherit">save</button>
      </div>
      <pre id="log" style="font-size:11px;opacity:.8;white-space:pre-wrap"></pre>
    </div>`;
  const conn = document.getElementById('conn')!;
  const logEl = document.getElementById('log')!;
  document.getElementById('save')!.addEventListener('click', () => {
    setServer((document.getElementById('srv') as HTMLInputElement).value.trim());
  });
  return {
    log(line) {
      logEl.textContent = `${new Date().toLocaleTimeString()} ${line}\n${logEl.textContent}`.slice(0, 4000);
    },
    setConnected(ok) {
      conn.textContent = ok ? '● bus connected' : '○ bus disconnected';
    },
  };
}
