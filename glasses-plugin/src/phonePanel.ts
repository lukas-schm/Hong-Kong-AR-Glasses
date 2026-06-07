/* ────────────────────────────────────────────────────────────────────────
   Phone-side panel. The plugin's HTML renders inside the Even App's WebView
   on the phone. Instead of an ops console, we show a **live mirror of the
   glasses display**: the same container pages we push over BLE, drawn as a
   scaled 576×288 green-on-black board. (Server URL + log are tucked away.)

   The mirror is fed by the Renderer (drawMirror on every page render,
   upgradeMirror on flicker-free text updates), so it tracks the glasses 1:1.
   ──────────────────────────────────────────────────────────────────────── */
import { SERVER, setServer } from './config';

export interface Controls {
  up: () => void; down: () => void; click: () => void; double: () => void;
}

export interface PhonePanel {
  log: (line: string) => void;
  setConnected: (ok: boolean) => void;
  /** Mirror a full page config (textObject[]/listObject[]) onto the board. */
  drawMirror: (page: any) => void;
  /** Flicker-free in-place text update of one mirrored container. */
  upgradeMirror: (containerID: number, content: string) => void;
  /** Wire the on-screen control buttons to the app's gesture handler. */
  bindControls: (c: Controls) => void;
}

const esc = (s: string) =>
  s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c] as string));

export function mountPhonePanel(): PhonePanel {
  document.body.innerHTML = `
    <div style="font-family:ui-monospace,monospace;background:#0b0b0b;color:#6cff9a;min-height:100vh;margin:0;padding:14px 12px">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px">
        <b style="font-size:15px">CDARS · Even G2 — glasses view</b>
        <span id="conn" style="font-size:12px;opacity:.85">○</span>
      </div>
      <div id="stage" style="width:100%;overflow:hidden;border-radius:10px;box-shadow:0 0 24px rgba(57,255,156,.08)">
        <div id="board" style="position:relative;width:576px;height:288px;background:#03110d;transform-origin:top left;outline:1px solid #1b4d3e"></div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px">
        <button id="cUp"    style="background:#143b2c;color:#cfe;border:1px solid #2a5;border-radius:8px;padding:12px 0;font:inherit;cursor:pointer">▲ up</button>
        <button id="cDown"  style="background:#143b2c;color:#cfe;border:1px solid #2a5;border-radius:8px;padding:12px 0;font:inherit;cursor:pointer">▼ down</button>
        <button id="cClick" style="background:#1d5740;color:#cfe;border:1px solid #2a5;border-radius:8px;padding:12px 0;font:inherit;cursor:pointer">● tap</button>
        <button id="cDbl"   style="background:#143b2c;color:#cfe;border:1px solid #2a5;border-radius:8px;padding:12px 0;font:inherit;cursor:pointer">●● back</button>
      </div>
      <details style="margin-top:12px">
        <summary style="font-size:12px;opacity:.55;cursor:pointer">server &amp; log</summary>
        <div style="display:flex;gap:6px;margin:8px 0">
          <input id="srv" value="${SERVER}" style="flex:1;background:#0a1f10;color:#6cff9a;border:1px solid #2a5;padding:5px;font:inherit;font-size:12px" />
          <button id="save" style="background:#143;color:#6cff9a;border:1px solid #2a5;padding:5px 10px;font:inherit;font-size:12px">save</button>
        </div>
        <pre id="log" style="font-size:10px;opacity:.7;white-space:pre-wrap;max-height:140px;overflow:auto"></pre>
      </details>
    </div>`;

  const board = document.getElementById('board') as HTMLDivElement;
  const stage = document.getElementById('stage') as HTMLDivElement;
  const conn = document.getElementById('conn')!;
  const logEl = document.getElementById('log')!;
  document.getElementById('save')!.addEventListener('click', () => {
    setServer((document.getElementById('srv') as HTMLInputElement).value.trim());
  });

  // Scale the logical 576×288 board to fit the phone width (cap at 2×).
  function fit() {
    const s = Math.min(stage.clientWidth / 576, 2);
    board.style.transform = `scale(${s})`;
    stage.style.height = `${288 * s}px`;
  }
  window.addEventListener('resize', fit);
  setTimeout(fit, 0);

  function box(c: any): HTMLDivElement {
    const el = document.createElement('div');
    el.dataset.cid = String(c.containerID ?? '');
    el.style.cssText =
      `position:absolute;left:${c.xPosition || 0}px;top:${c.yPosition || 0}px;` +
      `width:${c.width || 0}px;height:${c.height || 0}px;box-sizing:border-box;overflow:hidden;` +
      `color:#39ff9c;font:19px/1.32 ui-monospace,monospace;white-space:pre-wrap;padding:${c.paddingLength || 0}px;`;
    if (c.borderWidth) el.style.border = '1px solid #39ff9c';
    if (c.borderRadius) el.style.borderRadius = `${c.borderRadius}px`;
    return el;
  }

  return {
    log(line) {
      logEl.textContent = `${line}\n${logEl.textContent}`.slice(0, 4000);
    },
    setConnected(ok) {
      conn.textContent = ok ? '● connected' : '○ disconnected';
    },
    drawMirror(page) {
      board.innerHTML = '';
      for (const c of (page.textObject || [])) {
        const el = box(c);
        el.textContent = c.content || '';
        board.appendChild(el);
      }
      for (const c of (page.listObject || [])) {
        const el = box(c);
        const items: string[] = c.itemContainer?.itemName || [];
        el.innerHTML = items
          .map((n) => `<div style="padding:3px 2px;border-bottom:1px solid #0c2a22">${esc(n)}</div>`)
          .join('');
        board.appendChild(el);
      }
      fit();
    },
    upgradeMirror(containerID, content) {
      const el = board.querySelector(`[data-cid="${containerID}"]`) as HTMLElement | null;
      if (el) el.textContent = content;
    },
    bindControls(c) {
      (document.getElementById("cUp") as HTMLButtonElement).onclick = c.up;
      (document.getElementById("cDown") as HTMLButtonElement).onclick = c.down;
      (document.getElementById("cClick") as HTMLButtonElement).onclick = c.click;
      (document.getElementById("cDbl") as HTMLButtonElement).onclick = c.double;
    },
  };
}
