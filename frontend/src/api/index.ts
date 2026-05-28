import type { PatientState, ExtendedOutcomes, SimilarPatient } from '../types';

const BASE = '/api/v1';

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

function toApiPayload(state: PatientState, treatmentId: string) {
  return {
    sofa: state.sofa,
    sapsii: state.sapsii,
    lactate: state.lactate,
    vaso: state.vaso === 'YES',
    ventilation: state.ventilation === 'YES',
    aki: state.aki,
    dialysis: state.dialysis === 'YES',
    // PCT is intentionally not sent: the causal model does not use it (F15).
    crp: state.crp,
    wbc: state.wbc,
    temperature: state.temperature,
    culture_result: state.cultureResult,
    source_identified: state.sourceIdentified === 'YES',
    pathogen_identified: state.pathogenIdentified === 'YES',
    antibiotic_days: state.antibioticDays,
    age: state.age,
    female: state.female === 'YES',
    comorbidity: state.comorbidity,
    immunocompromised: state.immunocompromised === 'YES',
    heart_rate: state.heartRate,
    resp_rate: state.respRate,
    spo2: state.spo2,
    map: state.map,
    urine_output: state.urineOutput,
    weight: state.weight,
    treatment_id: treatmentId,
  };
}

export async function fetchPrediction(
  state: PatientState,
  treatmentId: string,
  signal?: AbortSignal,
): Promise<ExtendedOutcomes> {
  return apiFetch<ExtendedOutcomes>('/predict', {
    method: 'POST',
    body: JSON.stringify(toApiPayload(state, treatmentId)),
    signal,
  });
}

export async function fetchSimilarPatients(
  state: PatientState,
  signal?: AbortSignal,
): Promise<{ patients: SimilarPatient[] }> {
  return apiFetch<{ patients: SimilarPatient[] }>('/similar-patients', {
    method: 'POST',
    body: JSON.stringify(toApiPayload(state, state.activeTreatmentId)),
    signal,
  });
}

export async function fetchExemplarPatients(signal?: AbortSignal): Promise<{ patients: unknown[] }> {
  return apiFetch<{ patients: unknown[] }>('/exemplar-patients', { signal });
}

export async function fetchHealth(signal?: AbortSignal): Promise<{ status: string }> {
  return apiFetch<{ status: string }>('/health', { signal });
}

export async function submitSurvey(
  responses: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<void> {
  await apiFetch<void>('/survey', {
    method: 'POST',
    body: JSON.stringify(responses),
    signal,
  });
}
