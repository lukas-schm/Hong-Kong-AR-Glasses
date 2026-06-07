/* ────────────────────────────────────────────────────────────────────────
   CDARS REST client.

   The base retrieval layer: talks to the HA CDARS warehouse server
   (/api/v1/cdars/…) and adapts records into the HKPatient shape the HUD,
   monitor and dashboard already consume. Degrades to the bundled static
   fallback (hkPatients / cdarsEpisodes) when the server is unreachable, so
   the demo always runs.
   ──────────────────────────────────────────────────────────────────────── */
import type {
  BilingualText, CodedItem, HKPatient, LabResult, MicroResult, VitalRow, ClinicalNote,
} from '../data/hkPatients';
import { hkPatients } from '../data/hkPatients';
import type { Arm, ArmPredictions } from '../utils/prediction';

const BASE = '/api/v1/cdars';

/* ── server record shapes (loosely typed; we adapt to HKPatient) ── */
interface ServerCoded { system: string; code: string; rank?: number; status?: string; display: BilingualText; detail?: BilingualText }
interface ServerLab { code: string; name: BilingualText; value: number; unit: string; flag?: string; collected?: string }
interface ServerMicro { specimen: string; organism: BilingualText; result: string }
interface ServerRecord {
  referenceKey: string; hkid: string | null; nameEn: string; nameZh: string; ccc: string | null;
  dob: string | null; sex: 'M' | 'F'; age: number; active: boolean;
  hospitalCode: string | null; cluster: string | null; ward: BilingualText | null;
  sourceSystem: string; subtitle: BilingualText; tags: BilingualText[];
  diagnoses: ServerCoded[]; medications: ServerCoded[]; labs: ServerLab[];
  micro: ServerMicro[]; allergies: { code: string; display: BilingualText }[];
  encounters: Array<{ date: string; discharge: string | null; facility: string; type: BilingualText }>;
  vitals: VitalRow[]; notes: ClinicalNote[];
  outcomes: { continue: number | null; deescalate: number | null; cease: number | null;
              recommendedAction: Arm; recommendation: BilingualText };
  profile: Record<string, unknown>;
}

export interface CDARSStats {
  patients: number; active: number; episodes: number; diagnoses: number;
  prescriptions: number; labs: number; deaths: number; sepsisEpisodes: number;
  clusters: number; hospitals: number; span: { from: string | null; to: string | null };
  byCluster: Array<{ cluster: string; n: number }>;
  byType: Array<{ episode_type: string; n: number }>;
}

export interface CohortRow {
  referenceKey: string; sex: string; age: number; episodeType: string; admissionDate: string;
  cluster: string; hospital: string; specialty: string; dxCode: string; dxDesc: BilingualText;
  arm: string | null; bnf: string; drug: BilingualText; labTest: string | null; labValue: string;
  death: boolean; deathDate: string | null; active: boolean; linkedHkid: string | null;
}
export interface CohortResult {
  counts: { episodes: number; patients: number; deaths: number };
  listing: CohortRow[]; truncated: boolean; cap: number;
}
export interface CohortOutcomes {
  band: string; n: number;
  arms: Array<{ arm: string; n: number; deaths: number; survived: number; mortality: number }>;
}
export interface AuditEntry {
  ts: string; actor: string; action: string; reference_key: string | null; channel: string; detail: string;
}

let serverDown = false;
export function cdarsServerDown() { return serverDown; }

async function api<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    signal,
    ...init,
  });
  if (!res.ok) throw new Error(`CDARS ${res.status}: ${path}`);
  serverDown = false;
  return res.json() as Promise<T>;
}

/* ── server record → HKPatient ── */
function adaptRecord(r: ServerRecord): HKPatient {
  const diagnoses: CodedItem[] = r.diagnoses.map((d) => ({
    system: 'ICD-9-CM', code: d.code, display: d.display,
  }));
  const medications: CodedItem[] = r.medications.map((m) => ({
    system: 'BNF', code: m.code, display: m.display, detail: m.detail, status: m.status,
  }));
  const labs: LabResult[] = r.labs.map((l) => ({
    loinc: l.code, name: l.name, value: String(l.value),
    unit: l.unit, flag: (l.flag || undefined) as LabResult['flag'],
  }));
  const micro: MicroResult[] = (r.micro || []).map((m) => ({
    specimen: m.specimen, organism: m.organism, result: m.result,
  }));
  const allergies: CodedItem[] = (r.allergies || []).map((a) => ({
    system: 'HKCTT', code: a.code, display: a.display,
  }));
  return {
    hkid: r.hkid || r.referenceKey,
    referenceKey: r.referenceKey,
    active: r.active,
    cluster: r.cluster || undefined,
    nameEn: r.nameEn || r.referenceKey,
    nameZh: r.nameZh || '',
    ccc: r.ccc || '',
    dob: r.dob || '',
    sex: r.sex,
    hospitalCode: r.hospitalCode || 'QEH',
    ward: r.ward || { en: '', zh: '' },
    sourceSystem: 'HA-CMS',
    diagnoses, medications, labs, allergies, micro,
    encounters: r.encounters || [],
    vitals: r.vitals || [],
    notes: r.notes || [],
    subtitle: r.subtitle,
    tags: r.tags || [],
    outcomes: {
      continue: r.outcomes.continue ?? 0,
      deescalate: r.outcomes.deescalate ?? 0,
      cease: r.outcomes.cease ?? 0,
      recommendedAction: r.outcomes.recommendedAction,
      recommendation: r.outcomes.recommendation,
    },
    profile: r.profile as HKPatient['profile'],
  };
}

/* ── public API (each falls back to static data when offline) ── */

export async function fetchActivePatients(signal?: AbortSignal): Promise<HKPatient[]> {
  try {
    const { patients } = await api<{ patients: Array<{ referenceKey: string }> }>('/active', undefined, signal);
    const full = await Promise.all(
      patients.map((p) => api<ServerRecord>(`/patient/${encodeURIComponent(p.referenceKey)}`, undefined, signal)),
    );
    return full.map(adaptRecord);
  } catch (err) {
    if (signal?.aborted) throw err;
    serverDown = true;
    return hkPatients; // static fallback
  }
}

export async function fetchPatient(ident: string, signal?: AbortSignal): Promise<HKPatient | null> {
  try {
    const r = await api<ServerRecord>(`/patient/${encodeURIComponent(ident)}`, undefined, signal);
    return adaptRecord(r);
  } catch (err) {
    if (signal?.aborted) throw err;
    serverDown = true;
    return hkPatients.find((p) => p.hkid === ident || p.referenceKey === ident) ?? null;
  }
}

export async function fetchArmPredictions(referenceKey: string, signal?: AbortSignal): Promise<ArmPredictions | null> {
  try {
    const r = await api<{ values: Record<Arm, number>; live: boolean }>(
      `/patient/${encodeURIComponent(referenceKey)}/predict`, undefined, signal);
    if (!r.values || Object.keys(r.values).length === 0) return null;
    return { values: r.values, live: r.live };
  } catch (err) {
    if (signal?.aborted) throw err;
    return null;
  }
}

export async function fetchCohortOutcomes(referenceKey: string, signal?: AbortSignal): Promise<CohortOutcomes | null> {
  try {
    return await api<CohortOutcomes>(`/patient/${encodeURIComponent(referenceKey)}/cohort`, undefined, signal);
  } catch (err) {
    if (signal?.aborted) throw err;
    return null;
  }
}

export async function fetchStats(signal?: AbortSignal): Promise<CDARSStats | null> {
  try { return await api<CDARSStats>('/stats', undefined, signal); }
  catch { serverDown = true; return null; }
}

export interface CDARSCatalog {
  clusters: Array<{ code: string; name: BilingualText }>;
  hospitals: Array<{ code: string; cluster: string; name: BilingualText; acute: boolean }>;
  episodeTypes: Array<{ code: string; name: BilingualText }>;
  icd9: Array<{ code: string; desc: BilingualText; sepsis: boolean }>;
  bnf: Array<{ code: string; desc: BilingualText }>;
  drugs: Array<{ bnf: string; code: string; name: BilingualText; cls: string }>;
  labs: Array<{ code: string; name: BilingualText; unit: string }>;
}

export async function fetchCatalog(signal?: AbortSignal): Promise<CDARSCatalog | null> {
  try { return await api<CDARSCatalog>('/catalog', undefined, signal); }
  catch { return null; }
}

export interface CohortCriteria {
  dxCode: string; episodeType: string; cluster: string; sex: string;
  ageMin: number | null; ageMax: number | null;
  admittedFrom: string; admittedTo: string; deathsOnly: boolean;
}

export async function queryCohortApi(c: CohortCriteria, signal?: AbortSignal): Promise<CohortResult | null> {
  try {
    return await api<CohortResult>('/query', { method: 'POST', body: JSON.stringify(c) }, signal);
  } catch (err) {
    if (signal?.aborted) throw err;
    serverDown = true;
    return null;
  }
}

export async function fetchAudit(n = 40, signal?: AbortSignal): Promise<AuditEntry[]> {
  try {
    const { entries } = await api<{ entries: AuditEntry[] }>(`/audit?n=${n}`, undefined, signal);
    return entries;
  } catch { return []; }
}

export interface FeedPayload {
  referenceKey: string;
  writes?: Array<{ key: string; label?: string; unit?: string; value: number | string }>;
  prescription?: { action: string; drug: string; dose?: string; route?: string; frequency?: string };
  note?: { text: string; author?: string; lang?: string };
  source?: string;
  actor?: string;
  silent?: boolean;
}

export async function feedCdars(payload: FeedPayload, signal?: AbortSignal): Promise<{ applied: unknown[] } | null> {
  try {
    return await api<{ applied: unknown[] }>('/feed', { method: 'POST', body: JSON.stringify(payload) }, signal);
  } catch (err) {
    if (signal?.aborted) throw err;
    return null;
  }
}
