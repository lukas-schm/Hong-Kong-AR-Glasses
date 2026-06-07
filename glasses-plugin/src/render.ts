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

export type PageKind = 'worklist' | 'patient';

/** Decision carousel: 3 decisions + similar-patients card. */
export const CARD_COUNT = 4;

export interface RenderState {
  page: PageKind;
  patients: PatientRecord[];
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

export function menuItems(st: RenderState): string[] {
  return st.patients.slice(0, 20).map((p) =>
    clip(`${p.nameEn} · ${p.hospitalCode ?? '—'} · ${p.outcomes.recommendedAction}`, 64));
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

function agentText(st: RenderState): string {
  if (st.listening) return '● LISTENING…';
  if (st.reply) {
    const you = st.lastUtterance ? `YOU: ${clip(st.lastUtterance, 60)}\n` : '';
    return clip(`${you}LLM: ${st.reply}`, 500);
  }
  return 'tap: talk · scroll: cards · double-tap: patients';
}

/* ── pages ── */

function worklistPage(st: RenderState) {
  return {
    containerTotalNum: 3,
    textObject: [
      { containerID: ID.hdr, containerName: 'hdr', xPosition: 0, yPosition: 0, width: 576, height: 36, content: worklistHeader(st), isEventCapture: 0 },
      { containerID: ID.ftr, containerName: 'ftr', xPosition: 0, yPosition: 252, width: 576, height: 36, content: st.connected ? 'scroll: move · tap: open patient' : 'CDARS server unreachable — check Wi-Fi / server URL', isEventCapture: 0 },
    ],
    listObject: [
      {
        containerID: ID.menu, containerName: 'menu',
        xPosition: 0, yPosition: 40, width: 576, height: 208,
        paddingLength: 4, isEventCapture: 1,
        itemContainer: {
          itemCount: Math.max(1, Math.min(st.patients.length, 20)),
          itemWidth: 0,
          isItemSelectBorderEn: 1,
          itemName: st.patients.length ? menuItems(st) : ['no active patients'],
        },
      },
    ],
  };
}

function patientPage(st: RenderState) {
  const p = st.current!;
  return {
    containerTotalNum: 4,
    textObject: [
      { containerID: ID.hdr, containerName: 'hdr', xPosition: 0, yPosition: 0, width: 576, height: 44, content: patientHeader(p), isEventCapture: 0 },
      { containerID: ID.flags, containerName: 'flags', xPosition: 0, yPosition: 48, width: 196, height: 160, paddingLength: 4, borderWidth: 1, borderColor: 6, borderRadius: 3, content: flagsText(p), isEventCapture: 0 },
      { containerID: ID.card, containerName: 'card', xPosition: 204, yPosition: 48, width: 372, height: 160, paddingLength: 4, borderWidth: 1, borderColor: 10, borderRadius: 3, content: cardText(st), isEventCapture: 1 },
      { containerID: ID.agent, containerName: 'agent', xPosition: 0, yPosition: 212, width: 576, height: 76, paddingLength: 4, content: agentText(st), isEventCapture: 0 },
    ],
  };
}

/* ── serialized bridge driver ── */

export class Renderer {
  private booted = false;
  private chain: Promise<unknown> = Promise.resolve();
  private lastPage: PageKind | null = null;

  constructor(private bridge: EvenAppBridge) {}

  /** Serialize all bridge UI calls (the glasses require queued sends). */
  private enqueue<T>(fn: () => Promise<T>): Promise<T> {
    const next = this.chain.then(fn, fn);
    this.chain = next.catch(() => {});
    return next;
  }

  /** Full page render: startup on first call, rebuild on page switches. */
  render(st: RenderState) {
    return this.enqueue(async () => {
      const page = st.page === 'patient' && st.current ? patientPage(st) : worklistPage(st);
      if (!this.booted) {
        this.booted = true;
        await this.bridge.createStartUpPageContainer(page as never);
      } else {
        await this.bridge.rebuildPageContainer(page as never);
      }
      this.lastPage = st.page;
    });
  }

  /** Cheap in-place text updates for the patient page (no flicker). */
  update(st: RenderState) {
    if (this.lastPage !== st.page) return this.render(st);
    return this.enqueue(async () => {
      if (st.page === 'patient' && st.current) {
        await this.upgrade(ID.card, 'card', cardText(st));
        await this.upgrade(ID.agent, 'agent', agentText(st));
        await this.upgrade(ID.flags, 'flags', flagsText(st.current));
      } else {
        await this.upgrade(ID.hdr, 'hdr', worklistHeader(st));
      }
    });
  }

  private upgrade(containerID: number, containerName: string, content: string) {
    return this.bridge.textContainerUpgrade({
      containerID, containerName, contentOffset: 0, contentLength: content.length, content,
    } as never);
  }
}
