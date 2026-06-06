/* ────────────────────────────────────────────────────────────────────────
   Monitor bus — a live feed of what the system is doing while the
   clinician talks to the glasses. Every voice input, parsed intent,
   model request/response, and database write is emitted here.

   Transport: BroadcastChannel so a SEPARATE browser window/tab
   (the laptop "monitor app" at #monitor) receives the same stream in
   real time, plus an in-page EventTarget so same-window subscribers work
   too. Degrades silently when BroadcastChannel is unavailable.
   ──────────────────────────────────────────────────────────────────────── */

import type { ExemplarPatient } from '../data/exemplarPatients';

/** Everything needed to mirror the G2 HUD in another window. */
export interface HudSnapshot {
  open: boolean;
  patient: ExemplarPatient | null;
  listening: boolean;
  interim: string;
  reply: string | null;
  lastUtterance: string | null;
  busy: boolean;
}

export type MonitorEvent =
  | { kind: 'input'; seq: number; ts: number; source: 'voice' | 'chat'; text: string; lang: string }
  | { kind: 'intent'; seq: number; ts: number; intent: string; detail: string }
  | { kind: 'patient'; seq: number; ts: number; name: string; hkid: string }
  | { kind: 'model-req'; seq: number; ts: number; arm: string; features: Record<string, unknown> }
  | { kind: 'model-res'; seq: number; ts: number; arm: string; mortality: number }
  | { kind: 'db-write'; seq: number; ts: number; field: string; label: string; from: string; to: string }
  | { kind: 'reply'; seq: number; ts: number; text: string }
  | { kind: 'hud'; seq: number; ts: number; hud: HudSnapshot };

// Distributive Omit so each discriminated member keeps its own fields.
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;
type RawEvent = DistributiveOmit<MonitorEvent, 'seq' | 'ts'>;

const CHANNEL = 'cdss-monitor';
let seq = 0;
let monoClock = 0; // Date.now() is unavailable in some sandboxes; a counter is enough for ordering.

const channel: BroadcastChannel | null =
  typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel(CHANNEL) : null;
const local = typeof EventTarget !== 'undefined' ? new EventTarget() : null;

/** Emit a monitor event to every listener (this window + other windows). */
export function monitor(ev: RawEvent): void {
  seq += 1;
  monoClock += 1;
  const full = { ...ev, seq, ts: monoClock } as MonitorEvent;
  channel?.postMessage(full);
  local?.dispatchEvent(new CustomEvent<MonitorEvent>('ev', { detail: full }));
}

/** Subscribe to the live stream. Returns an unsubscribe function. */
export function subscribeMonitor(cb: (ev: MonitorEvent) => void): () => void {
  const onChannel = (e: MessageEvent<MonitorEvent>) => cb(e.data);
  const onLocal = (e: Event) => cb((e as CustomEvent<MonitorEvent>).detail);
  channel?.addEventListener('message', onChannel);
  local?.addEventListener('ev', onLocal);
  return () => {
    channel?.removeEventListener('message', onChannel);
    local?.removeEventListener('ev', onLocal);
  };
}
