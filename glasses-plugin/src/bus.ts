/* ────────────────────────────────────────────────────────────────────────
   Realtime bus client — port of frontend/src/utils/bus.ts for the G2
   plugin. Same protocol (one WebSocket to /api/v1/ws), but connects to an
   absolute server URL (the phone WebView is a different origin) and always
   joins as role=glasses.

   Carries: activity · select · nav · hud · data-change · presence.
   Auto-reconnects with backoff; queues sends while offline.
   ──────────────────────────────────────────────────────────────────────── */
import { WS_URL } from './config';

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
  | { type: 'data-change'; seq: number; ts: string; referenceKey: string; fields?: string[] }
  | { type: 'presence'; seq: number; ts: string; clients: string[] }
  | { type: 'welcome'; role: string; clients: string[] }
  | { type: string; [k: string]: unknown };

type Listener = (ev: BusEvent) => void;

class BusClient {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private statusCbs = new Set<(connected: boolean) => void>();
  private backoff = 1000;
  private queue: object[] = [];
  private started = false;
  connected = false;
  presence: string[] = [];

  start() {
    if (this.started) return;
    this.started = true;
    this.open();
  }

  private open() {
    let ws: WebSocket;
    try {
      ws = new WebSocket(WS_URL);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.connected = true;
      this.backoff = 1000;
      this.statusCbs.forEach((cb) => cb(true));
      this.queue.forEach((m) => ws.send(JSON.stringify(m)));
      this.queue = [];
    };
    ws.onmessage = (e) => {
      let ev: BusEvent;
      try { ev = JSON.parse(e.data); } catch { return; }
      if (ev.type === 'presence' || ev.type === 'welcome') {
        this.presence = (ev as { clients: string[] }).clients ?? [];
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
    else this.queue.push(msg);
  }

  publishNav(nav: { card?: number; menuOpen?: boolean; menuIndex?: number }) {
    this.send({ type: 'nav', ...nav });
  }
  publishSelect(referenceKey: string) {
    this.send({ type: 'select', referenceKey });
  }
  publishActivity(a: Partial<BusActivity> & { kind: BusActivity['kind']; text: string }) {
    this.send({ type: 'activity', source: 'glasses', ...a });
  }

  subscribe(cb: Listener): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }
  onStatus(cb: (connected: boolean) => void): () => void {
    this.statusCbs.add(cb);
    cb(this.connected);
    return () => this.statusCbs.delete(cb);
  }
}

export const bus = new BusClient();
