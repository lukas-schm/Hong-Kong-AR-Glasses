import type { HKPatient } from '../data/hkPatients';
import { hkToPatientState } from './hkAdapter';
import { fetchPrediction } from '../api';

/* ────────────────────────────────────────────────────────────────────────
   Shared model-interaction layer for the HK showcase: one place that
   scores treatment arms against the trained causal model, picks the
   recommended arm, and owns the offline fallback — so dashboard, chatbot
   and HUD can never disagree on the numbers.
   ──────────────────────────────────────────────────────────────────────── */

export const ARMS = ['continue', 'deescalate', 'cease'] as const;
export type Arm = (typeof ARMS)[number];

export interface ArmPredictions {
  values: Record<Arm, number>;
  live: boolean;   // true when served by the trained model API
}

/** Arm with the lowest predicted mortality. */
export function bestArm(values: Record<Arm, number>): Arm {
  return ARMS.reduce((a, b) => (values[a] <= values[b] ? a : b));
}

export function cachedArmValues(patient: HKPatient): Record<Arm, number> {
  return {
    continue: patient.outcomes.continue,
    deescalate: patient.outcomes.deescalate,
    cease: patient.outcomes.cease,
  };
}

/**
 * Score all three arms against the trained model; fall back to cached
 * estimates when the API is unreachable. An abort is rethrown (not masked
 * as an offline fallback) so callers can ignore stale requests.
 */
export async function predictAllArms(patient: HKPatient, signal?: AbortSignal): Promise<ArmPredictions> {
  const state = hkToPatientState(patient);
  try {
    const results = await Promise.all(ARMS.map((arm) => fetchPrediction(state, arm, signal)));
    const values = Object.fromEntries(
      ARMS.map((arm, i) => [arm, Math.round(results[i].withTreatment)]),
    ) as Record<Arm, number>;
    return { values, live: true };
  } catch (err) {
    if (signal?.aborted) throw err;
    return { values: cachedArmValues(patient), live: false };
  }
}
