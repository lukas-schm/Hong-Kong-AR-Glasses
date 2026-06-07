/* ────────────────────────────────────────────────────────────────────────
   Agent client — server-first, with a local fallback.

   The single entry point the glasses and the monitor use to talk to the
   CDARS agent. It POSTs to /api/v1/agent/command (the deterministic planner,
   or Claude when ANTHROPIC_API_KEY is set on the server). If the server is
   unreachable it falls back to the in-browser runAssistant engine so the
   demo still answers offline.
   ──────────────────────────────────────────────────────────────────────── */
import type { Arm } from './prediction';
import type { ArmPredictions } from './prediction';
import type { HKPatient } from '../data/hkPatients';
import { runAssistant } from './assistant';

export interface AgentResult {
  reply: string;
  intent?: string;
  referenceKey?: string | null;
  select?: string | null;       // open this patient everywhere
  changed?: boolean;            // a record was written → refetch + re-score
  simulated?: boolean;          // a what-if (no write)
  predictions?: { values: Record<Arm, number>; live: boolean };
  engine?: string;              // 'planner' | 'llm' | 'local'
  lang?: string;
  offline?: boolean;
}

export interface AgentOpts {
  referenceKey?: string | null;
  source?: 'voice' | 'chat' | 'glasses';
  lang?: 'en' | 'zh-HK';
  /** Offline fallback context (current patient + base predictions). */
  fallback?: { patient: HKPatient | null; basePredictions: ArmPredictions | null };
}

export async function sendAgentCommand(text: string, opts: AgentOpts = {}): Promise<AgentResult> {
  try {
    const res = await fetch('/api/v1/agent/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        referenceKey: opts.referenceKey ?? null,
        source: opts.source ?? 'voice',
        lang: opts.lang ?? 'en',
      }),
    });
    if (!res.ok) throw new Error(`agent ${res.status}`);
    return (await res.json()) as AgentResult;
  } catch {
    // ── offline fallback: in-browser assistant ──
    const ctx = opts.fallback;
    const reply = await runAssistant(text, {
      patient: ctx?.patient ?? null,
      basePredictions: ctx?.basePredictions ?? null,
      source: opts.source === 'chat' ? 'chat' : 'voice',
    });
    let select: string | null = null;
    let changed = false;
    if (reply.action?.type === 'open-patient') {
      select = reply.action.patient.referenceKey ?? reply.action.patient.hkid;
    } else if (reply.action?.type === 'write-record') {
      changed = true;
    }
    return {
      reply: reply.text,
      intent: reply.intent,
      referenceKey: opts.referenceKey ?? null,
      select,
      changed,
      engine: 'local',
      offline: true,
      lang: opts.lang,
      // Carry the local write-record action so the caller can mutate state.
      ...(reply.action?.type === 'write-record' ? { localWrites: reply.action.writes } : {}),
    } as AgentResult & { localWrites?: unknown };
  }
}
