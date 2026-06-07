/* ────────────────────────────────────────────────────────────────────────
   CDARS REST client — trimmed port of frontend/src/api/cdars.ts.

   Talks to the FastAPI server at an absolute base URL (phone WebView).
   Only what the glasses page needs: the active worklist, single-patient
   refresh, live predictions, cohort outcomes, and the agent command.
   No static fallback here — the G2 surface degrades to a "server
   unreachable" line instead (the desktop demo keeps its own fallback).
   ──────────────────────────────────────────────────────────────────────── */
import { SERVER } from './config';

export interface BilingualText { en: string; zh: string }
export type Arm = 'continue' | 'deescalate' | 'cease';

export interface PatientProfile {
  map?: number; lactate?: number; sofa?: number; spo2?: number;
  vaso?: 'YES' | 'NO'; ventilation?: 'YES' | 'NO'; aki?: number;
  urineOutput?: number; cultureResult?: string;
  [k: string]: unknown;
}

export interface PatientRecord {
  referenceKey: string;
  hkid: string | null;
  nameEn: string;
  nameZh: string;
  age: number;
  sex: 'M' | 'F';
  active: boolean;
  hospitalCode: string | null;
  ward: BilingualText | null;
  subtitle: BilingualText;
  outcomes: {
    continue: number | null; deescalate: number | null; cease: number | null;
    recommendedAction: Arm; recommendation: BilingualText;
  };
  profile: PatientProfile;
}

export interface CohortOutcomes {
  band: string; n: number;
  arms: Array<{ arm: string; n: number; deaths: number; survived: number; mortality: number }>;
}

export interface AgentResult {
  reply: string;
  intent?: string;
  select?: string | null;
  changed?: boolean;
  engine?: string;
}

const BASE = `${SERVER}/api/v1`;

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) throw new Error(`CDARS ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

export async function fetchActivePatients(): Promise<PatientRecord[]> {
  const { patients } = await api<{ patients: Array<{ referenceKey: string }> }>('/cdars/active');
  return Promise.all(patients.map((p) => fetchPatient(p.referenceKey)));
}

export function fetchPatient(ident: string): Promise<PatientRecord> {
  return api<PatientRecord>(`/cdars/patient/${encodeURIComponent(ident)}`);
}

export async function fetchArmPredictions(referenceKey: string): Promise<Record<Arm, number> | null> {
  try {
    const r = await api<{ values: Record<Arm, number> }>(`/cdars/patient/${encodeURIComponent(referenceKey)}/predict`);
    return r.values && Object.keys(r.values).length ? r.values : null;
  } catch { return null; }
}

export async function fetchCohortOutcomes(referenceKey: string): Promise<CohortOutcomes | null> {
  try { return await api<CohortOutcomes>(`/cdars/patient/${encodeURIComponent(referenceKey)}/cohort`); }
  catch { return null; }
}

export function sendAgentCommand(
  text: string,
  opts: { referenceKey?: string | null; lang?: 'en' | 'zh-HK' } = {},
): Promise<AgentResult> {
  return api<AgentResult>('/agent/command', {
    method: 'POST',
    body: JSON.stringify({
      text,
      referenceKey: opts.referenceKey ?? null,
      source: 'glasses',
      lang: opts.lang ?? 'en',
    }),
  });
}
