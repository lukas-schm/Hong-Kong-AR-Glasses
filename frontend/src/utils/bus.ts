/* ────────────────────────────────────────────────────────────────────────
   Realtime bus client — one WebSocket to the CDARS server (/api/v1/ws),
   shared by the glasses (#glasses), the monitor (#monitor) and the CDARS
   workbench (#cdars).

   It carries:
     · activity  — plain-language step stream (voice→tool→model→db-write→reply)
     · select    — open this patient everywhere (HUD-sync)
     · nav       — mirror HUD navigation (card / menu) across windows
     · hud       — full HUD snapshot mirror
     · data-change — a record was written; refetch + re-score
     · presence  — which roles are connected

   Auto-reconnects with backoff and degrades silently when the server is
   offline (the app still works against the static fallback data).
   ──────────────────────────────────────────────────────────────────────── */

export type BusRole = 'glasses' | 'monitor' | 'cdars' | 'client';

export interface BusActivity {
  type: 'activity';
  seq: number;
  ts: string;
  kind: 'voice' | 'intent' | 'tool' | 'model' | 'db-write' | 'reply' | 'info';
  text: string;
  textZh?: string | null;
  detail?: string;
  referenceKey?: string | null;
  ok?: boolean | null;
  source?: string;
}

export type BusEvent =
  | BusActivity
  | { type: 'select'; seq: number; ts: string; referenceKey: string; origin?: string }
  | { type: 'nav'; seq: number; ts: string; card?: number; menuOpen?: boolean; menuIndex?: number; origin?: string }
  | { type: 'hud'; seq: number; ts: string; hud: unknown; origin?: string }
  | { type: 'data-change'; seq: number; ts: string; referenceKey: string; fields?: string[] }
  | { type: 'presence'; seq: number; ts: string; clients: string[] }
  | { type: 'welcome'; role: string; clients: string[] }
  | { type: string; [k: string]: unknown };

type Listener = (ev: BusEvent) => void;

const WS_PATH = '/api/v1/ws';

class BusClient {
  private ws: WebSocket | null = null;
  private role: BusRole = 'client';
  private listeners = new Set<Listener>();
  private presenceCbs = new Set<(roles: string[]) => void>();
  private statusCbs = new Set<(connected: boolean) => void>();
  private backoff = 1000;
  private queue: object[] = [];
  private started = false;
  connected = false;
  presence: string[] = [];

  start(role: BusRole) {
    this.role = role;
    if (this.started) return;
    this.started = true;
    this.open();
  }

  private url(): string {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${location.host}${WS_PATH}?role=${this.role}`;
  }

  private open() {
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url());
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.connected = true;
      this.backoff = 1000;
      this.statusCbs.forEach((cb) => cb(true));
      // flush anything queued while offline
      this.queue.forEach((m) => ws.send(JSON.stringify(m)));
      this.queue = [];
    };
    ws.onmessage = (e) => {
      let ev: BusEvent;
      try { ev = JSON.parse(e.data); } catch { return; }
      if (ev.type === 'presence' || ev.type === 'welcome') {
        this.presence = (ev as { clients: string[] }).clients ?? [];
        this.presenceCbs.forEach((cb) => cb(this.presence));
      }
      this.listeners.forEach((l) => l(ev));
    };
    ws.onclose = () => {
      this.connected = false;
      this.statusCbs.forEach((cb) => cb(false));
      this.scheduleReconnect();
    };
    ws.onerror = () => ws.close();
  }

  private scheduleReconnect() {
    this.ws = null;
    setTimeout(() => this.open(), this.backoff);
    this.backoff = Math.min(this.backoff * 1.6, 15000);
  }

  send(msg: object) {
    if (this.ws && this.connected) this.ws.send(JSON.stringify(msg));
    else this.queue.push(msg); // replay on reconnect
  }

  /* relay helpers (mirrored to the other windows server-side) */
  publishNav(nav: { card?: number; menuOpen?: boolean; menuIndex?: number }) {
    this.send({ type: 'nav', ...nav });
  }
  publishSelect(referenceKey: string) {
    this.send({ type: 'select', referenceKey });
  }
  publishHud(hud: unknown) {
    this.send({ type: 'hud', hud });
  }
  publishActivity(a: Partial<BusActivity> & { kind: BusActivity['kind']; text: string }) {
    this.send({ type: 'activity', source: this.role, ...a });
  }

  subscribe(cb: Listener): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }
  onPresence(cb: (roles: string[]) => void): () => void {
    this.presenceCbs.add(cb);
    cb(this.presence);
    return () => this.presenceCbs.delete(cb);
  }
  onStatus(cb: (connected: boolean) => void): () => void {
    this.statusCbs.add(cb);
    cb(this.connected);
    return () => this.statusCbs.delete(cb);
  }
}

export const bus = new BusClient();
