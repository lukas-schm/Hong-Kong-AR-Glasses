/* ────────────────────────────────────────────────────────────────────────
   Glasses renderer — translates CDSS state into Even G2 container pages.

   The G2 doesn't render our DOM: pages are built from Text/List containers
   on a 576×288 canvas (origin top-left), exactly one container per page
   capturing events. Two pages:

     WORKLIST                          PATIENT
     ┌─ hdr (text) ──────────────┐    ┌─ hdr (text) ───────────────┐
     ├─ menu (list, events) ─────┤    ├─ flags ──┬─ card (events) ─┤
     │  active patients          │    │ red flags│ decision detail │
     ├─ ftr (text) ──────────────┤    ├─ agent (text) ─────────────┤
     └───────────────────────────┘    └────────────────────────────┘

   Small text changes go through textContainerUpgrade (no flicker);
   page switches go through rebuildPageContainer. Calls are serialized —
   the glasses choke on concurrent transmissions.
   ──────────────────────────────────────────────────────────────────────── */
import type { EvenAppBridge } from '@evenrealities/even_hub_sdk';
import type { Arm, CohortOutcomes, PatientRecord } from './cdars';
import { deriveDecisions, deriveRedFlags } from './clinical';
import type { PhonePanel } from './phonePanel';

export type PageKind = 'worklist' | 'patient';

/** Decision carousel: 3 decisions + similar-patients card. */
export const CARD_COUNT = 4;

export interface RenderState {
  page: PageKind;
  patients: PatientRecord[];
  worklistIndex: number;        // app-managed worklist cursor (▸)
  current: PatientRecord | null;
  predictions: Record<Arm, number> | null;
  cohort: CohortOutcomes | null;
  card: number;
  connected: boolean;
  listening: boolean;
  reply: string | null;
  lastUtterance: string | null;
}

/* Container IDs are stable so upgrades can target them. */
const ID = { hdr: 1, menu: 2, ftr: 3, flags: 4, card: 5, agent: 6 } as const;

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

/* ── content builders ── */

function worklistHeader(st: RenderState): string {
  const dot = st.connected ? '●' : '○';
  return `CDARS · ACTIVE PATIENTS (${st.patients.length}) ${dot}`;
}

/** App-managed worklist body: one row per patient, ▸ marks the cursor. */
export function worklistBody(st: RenderState): string {
  if (!st.patients.length) {
    return st.connected ? 'no active patients' : 'CDARS server unreachable — check Wi-Fi';
  }
  return st.patients.slice(0, 8).map((p, i) => {
    const cur = i === st.worklistIndex ? '▶ ' : '   ';
    return cur + clip(`${p.nameEn} · ${p.hospitalCode ?? '—'} · ${p.outcomes.recommendedAction}`, 58);
  }).join('\n');
}


function patientHeader(p: PatientRecord): string {
  const ward = p.ward?.en ? ` · ${p.ward.en}` : '';
  return clip(`${p.nameEn} ${p.age}${p.sex}${ward}\n${p.subtitle.en}`, 120);
}

function flagsText(p: PatientRecord): string {
  const flags = deriveRedFlags(p);
  if (!flags.length) return 'No red flags';
  return flags.map((f) => `${f.severity === 'crit' ? '!!' : '!'} ${f.label}${f.value ? ` ${f.value}` : ''}`).join('\n');
}

function cardText(st: RenderState): string {
  const p = st.current!;
  if (st.card === 3) {
    // Similar patients (territory-wide cohort outcomes)
    if (!st.cohort) return 'SIMILAR PATIENTS\nloading…';
    const rows = st.cohort.arms.slice(0, 3)
      .map((a) => `${clip(a.arm, 14)}  ${Math.round(a.mortality)}% mort (n=${a.n})`).join('\n');
    return `SIMILAR PATIENTS · ${st.cohort.band} (n=${st.cohort.n})\n${rows}`;
  }
  const d = deriveDecisions(p, st.predictions)[st.card];
  const rec = d.options.find((o) => o.key === d.recKey)!;
  const others = d.options.filter((o) => o.key !== d.recKey);
  const nextBest = Math.min(...others.map((o) => o.mortality));
  const delta = Math.round(nextBest - rec.mortality);
  const lines = d.options.map((o) =>
    `${o.key === d.recKey ? '>' : ' '} ${o.label.padEnd(7)} ${Math.round(o.mortality)}%`);
  return [
    `${d.axis.toUpperCase()} ${st.card + 1}/${CARD_COUNT}`,
    ...lines,
    delta > 0 ? `${delta}% better than next best` : '',
  ].filter(Boolean).join('\n');
}

type Variant = 'worklist' | 'cards' | 'voice';

/** Which patient-page layout to show: the decision cards, or the voice window. */
function variant(st: RenderState): Variant {
  if (st.page !== 'patient' || !st.current) return 'worklist';
  return st.listening || st.reply ? 'voice' : 'cards';
}

/** Text shown in the patient-page voice window: listening / thinking / answer. */
function voiceBody(st: RenderState): string {
  if (st.listening) return '● LISTENING…\n\ntap again to send your question';
  if (st.reply === '…') return 'Thinking…';
  return clip(st.reply ?? '', 1000);
}

const CARDS_HINT = 'tap: talk · scroll: cards · double-tap: patients';
const VOICE_HINT = 'tap: ask again · scroll: cards · double-tap: back';

/* ── pages ── */

function worklistPage(st: RenderState) {
  // App-managed list (text container) so the ▸ cursor is driven by the app —
  // moved identically by the physical touchpad and the phone control buttons.
  return {
    containerTotalNum: 3,
    textObject: [
      { containerID: ID.hdr, containerName: 'hdr', xPosition: 10, yPosition: 0, width: 556, height: 38, content: worklistHeader(st), isEventCapture: 0 },
      { containerID: ID.menu, containerName: 'menu', xPosition: 10, yPosition: 44, width: 556, height: 200, content: worklistBody(st), isEventCapture: 1 },
      { containerID: ID.ftr, containerName: 'ftr', xPosition: 10, yPosition: 250, width: 556, height: 38, content: st.connected ? 'scroll: move · tap: open' : 'CDARS server unreachable — check Wi-Fi / server URL', isEventCapture: 0 },
    ],
  };
}

function patientPage(st: RenderState) {
  const p = st.current!;
  const hdr = { containerID: ID.hdr, containerName: 'hdr', xPosition: 10, yPosition: 0, width: 556, height: 60, content: patientHeader(p), isEventCapture: 0 };

  // Voice window: full-width text answer/status. The answer box captures events
  // (tap = ask again, scroll = back to cards, double-tap = worklist).
  if (st.listening || st.reply) {
    return {
      containerTotalNum: 3,
      textObject: [
        hdr,
        { containerID: ID.card, containerName: 'card', xPosition: 10, yPosition: 64, width: 556, height: 150, content: voiceBody(st), isEventCapture: 1 },
        { containerID: ID.agent, containerName: 'agent', xPosition: 10, yPosition: 216, width: 556, height: 72, content: VOICE_HINT, isEventCapture: 0 },
      ],
    };
  }

  // Default: red-flags box + decision card carousel.
  return {
    containerTotalNum: 4,
    textObject: [
      hdr,
      { containerID: ID.flags, containerName: 'flags', xPosition: 0, yPosition: 64, width: 196, height: 150, paddingLength: 4, borderWidth: 1, borderColor: 6, borderRadius: 3, content: flagsText(p), isEventCapture: 0 },
      { containerID: ID.card, containerName: 'card', xPosition: 204, yPosition: 64, width: 372, height: 150, paddingLength: 4, borderWidth: 1, borderColor: 10, borderRadius: 3, content: cardText(st), isEventCapture: 1 },
      { containerID: ID.agent, containerName: 'agent', xPosition: 10, yPosition: 216, width: 556, height: 72, content: CARDS_HINT, isEventCapture: 0 },
    ],
  };
}

/* ── serialized bridge driver ── */

export class Renderer {
  private booted = false;
  private chain: Promise<unknown> = Promise.resolve();
  private lastVariant: Variant | null = null;

  constructor(private bridge: EvenAppBridge, private panel?: PhonePanel) {}

  /** Serialize all bridge UI calls (the glasses require queued sends). */
  private enqueue<T>(fn: () => Promise<T>): Promise<T> {
    const next = this.chain.then(fn, fn);
    this.chain = next.catch(() => {});
    return next;
  }

  /** Full page render: startup on first call, rebuild on layout (variant) switches. */
  render(st: RenderState) {
    return this.enqueue(async () => {
      const page = st.page === 'patient' && st.current ? patientPage(st) : worklistPage(st);
      this.panel?.drawMirror(page);                 // mirror onto the phone preview
      if (!this.booted) {
        this.booted = true;
        await this.bridge.createStartUpPageContainer(page as never);
      } else {
        await this.bridge.rebuildPageContainer(page as never);
      }
      this.lastVariant = variant(st);
    });
  }

  /** In-place text updates (no flicker). Rebuilds only when the layout variant changes. */
  update(st: RenderState) {
    const v = variant(st);
    if (v !== this.lastVariant) return this.render(st);
    return this.enqueue(async () => {
      if (v === 'cards' && st.current) {
        await this.upgrade(ID.card, 'card', cardText(st));
        await this.upgrade(ID.flags, 'flags', flagsText(st.current));
      } else if (v === 'voice') {
        await this.upgrade(ID.card, 'card', voiceBody(st));
      } else {
        await this.upgrade(ID.hdr, 'hdr', worklistHeader(st));
        await this.upgrade(ID.menu, 'menu', worklistBody(st));   // move the ▶ cursor
      }
    });
  }

  private upgrade(containerID: number, containerName: string, content: string) {
    this.panel?.upgradeMirror(containerID, content);   // keep the phone preview in sync
    return this.bridge.textContainerUpgrade({
      containerID, containerName, contentOffset: 0, contentLength: content.length, content,
    } as never);
  }
}
