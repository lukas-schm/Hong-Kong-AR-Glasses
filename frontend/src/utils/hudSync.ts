/* ────────────────────────────────────────────────────────────────────────
   Synced HUD state.

   One small shared store for the *navigational* state of the G2 HUD —
   which patient is loaded, which card is showing, and the patients-menu
   cursor. Every mutation is broadcast over the bus, and inbound bus events
   (select / nav) apply without re-broadcasting, so the glasses (#glasses)
   and the monitor's embedded HUD (#monitor) stay mirror-synced live across
   windows and devices.
   ──────────────────────────────────────────────────────────────────────── */
import { useSyncExternalStore } from 'react';
import { bus, type BusEvent } from './bus';

export interface HudSyncState {
  referenceKey: string | null;  // current patient (CDARS ref key or hkid)
  card: number;                 // active card index in the HUD
  menuOpen: boolean;            // patients-menu overlay open
  menuIndex: number;            // cursor in the patients menu
}

let state: HudSyncState = { referenceKey: null, card: 0, menuOpen: false, menuIndex: 0 };
const subs = new Set<() => void>();

function emit() { subs.forEach((s) => s()); }

function apply(patch: Partial<HudSyncState>): boolean {
  const next = { ...state, ...patch };
  if (
    next.referenceKey === state.referenceKey && next.card === state.card &&
    next.menuOpen === state.menuOpen && next.menuIndex === state.menuIndex
  ) return false;
  state = next;
  emit();
  return true;
}

/* ── local mutations (broadcast to the other windows) ── */
export function selectPatient(referenceKey: string | null, opts: { broadcast?: boolean } = {}) {
  const changed = apply({ referenceKey, menuOpen: false });
  if (changed && opts.broadcast !== false && referenceKey) bus.publishSelect(referenceKey);
}
export function setCard(card: number, opts: { broadcast?: boolean } = {}) {
  if (apply({ card }) && opts.broadcast !== false) bus.publishNav({ card });
}
export function setMenu(menuOpen: boolean, menuIndex = state.menuIndex, opts: { broadcast?: boolean } = {}) {
  if (apply({ menuOpen, menuIndex }) && opts.broadcast !== false) bus.publishNav({ menuOpen, menuIndex });
}
export function setMenuIndex(menuIndex: number, opts: { broadcast?: boolean } = {}) {
  if (apply({ menuIndex }) && opts.broadcast !== false) bus.publishNav({ menuIndex });
}

export function getHudState(): HudSyncState { return state; }

/* ── inbound bus events apply without re-broadcasting ── */
function onBus(ev: BusEvent) {
  if (ev.type === 'select') {
    apply({ referenceKey: (ev as { referenceKey: string }).referenceKey, menuOpen: false });
  } else if (ev.type === 'nav') {
    const n = ev as { card?: number; menuOpen?: boolean; menuIndex?: number };
    const patch: Partial<HudSyncState> = {};
    if (typeof n.card === 'number') patch.card = n.card;
    if (typeof n.menuOpen === 'boolean') patch.menuOpen = n.menuOpen;
    if (typeof n.menuIndex === 'number') patch.menuIndex = n.menuIndex;
    apply(patch);
  }
}
let wired = false;
function ensureWired() {
  if (wired) return;
  wired = true;
  bus.subscribe(onBus);
}

export function useHudSync(): HudSyncState {
  ensureWired();
  return useSyncExternalStore(
    (cb) => { subs.add(cb); return () => subs.delete(cb); },
    () => state,
  );
}
