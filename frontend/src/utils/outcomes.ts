import type { PatientState, ExtendedOutcomes } from '../types';
import { fetchPrediction } from '../api';

/* ── Synthetic fallback outcome model ────────────── */
/* Used only when backend is unavailable */

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}

function sigmoid(x: number) {
  return 1 / (1 + Math.exp(-x));
}

export function computeSyntheticOutcomes(state: PatientState, treatmentId: string): ExtendedOutcomes {
  const {
    sofa, sapsii, lactate, vaso, ventilation, aki,
    pct, crp, cultureResult, antibioticDays,
    age, comorbidity, immunocompromised,
  } = state;

  // Base mortality risk from severity scores
  const severityScore =
    sofa * 0.05 +
    sapsii * 0.004 +
    lactate * 0.025 +
    (vaso === 'YES' ? 0.10 : 0) +
    (ventilation === 'YES' ? 0.08 : 0) +
    aki * 0.03 +
    Math.log1p(crp) * 0.015 +
    Math.log1p(pct) * 0.02 +
    age * 0.004 +
    comorbidity * 0.02 +
    (immunocompromised === 'YES' ? 0.08 : 0);

  const baseMortality = sigmoid(severityScore - 2.2);

  // Treatment effect — depends on infection likelihood
  const infectionLikelihood =
    (cultureResult === 'positive' ? 0.4 : cultureResult === 'negative' ? -0.2 : 0.1) +
    (pct > 2 ? 0.2 : pct > 0.5 ? 0.1 : -0.1) +
    (crp > 100 ? 0.1 : 0);

  let withTreatment: number;
  let withoutTreatment: number;
  let effect: number;

  if (treatmentId === 'continue') {
    // Continue broad-spectrum: beneficial when severe/culture-pending, harmful when culture-negative
    const benefit = infectionLikelihood * 0.12 - 0.02;
    withTreatment = clamp(baseMortality - Math.max(0, benefit), 0.03, 0.92);
    withoutTreatment = clamp(baseMortality + 0.05, 0.03, 0.92);
    effect = withTreatment - withoutTreatment;
  } else if (treatmentId === 'deescalate') {
    // De-escalate: beneficial when culture-positive, source known
    const cultureBonus = cultureResult === 'positive' ? 0.06 : 0;
    const dayPenalty = antibioticDays > 5 ? 0.02 : 0;
    withTreatment = clamp(baseMortality - cultureBonus + dayPenalty, 0.03, 0.92);
    withoutTreatment = clamp(baseMortality + 0.03, 0.03, 0.92);
    effect = withTreatment - withoutTreatment;
  } else {
    // Cease: safe when culture-negative and improving
    const ceaseSafe = cultureResult === 'negative' && pct < 1.0;
    const ceasePenalty = ceaseSafe ? -0.03 : 0.12;
    withTreatment = clamp(baseMortality + ceasePenalty, 0.03, 0.92);
    withoutTreatment = clamp(baseMortality + 0.04, 0.03, 0.92);
    effect = withTreatment - withoutTreatment;
  }

  // Secondary outcomes (synthetic)
  const vfdDays = Math.round(clamp(14 - sofa * 0.8 - (ventilation === 'YES' ? 3 : 0), 0, 21));
  const icuLosDays = Math.round(clamp(4 + sofa * 0.6 + sapsii * 0.05, 2, 30));
  const cdiffRisk = clamp(
    (treatmentId === 'continue' ? 0.08 : treatmentId === 'deescalate' ? 0.04 : 0.01) +
    antibioticDays * 0.005 + comorbidity * 0.005,
    0.005, 0.35,
  );
  const resistanceRisk = clamp(
    (treatmentId === 'continue' ? 0.12 : treatmentId === 'deescalate' ? 0.05 : 0.01) +
    antibioticDays * 0.01,
    0.005, 0.5,
  );

  const ate = effect;
  const margin = 0.03 + Math.abs(effect) * 0.4;
  const confidence: 'high' | 'moderate' | 'low' =
    Math.abs(ate) > 0.08 ? 'high' : Math.abs(ate) > 0.04 ? 'moderate' : 'low';

  return {
    withTreatment: Math.round(withTreatment * 1000) / 10,
    withoutTreatment: Math.round(withoutTreatment * 1000) / 10,
    effect: Math.round(effect * 1000) / 10,
    ate: Math.round(ate * 1000) / 10,
    ateLowerBound: Math.round((ate - margin) * 1000) / 10,
    ateUpperBound: Math.round((ate + margin) * 1000) / 10,
    confidence,
    vfdDays,
    icuLosDays,
    cdiffRisk: Math.round(cdiffRisk * 1000) / 10,
    resistanceRisk: Math.round(resistanceRisk * 1000) / 10,
  };
}

export async function fetchOutcomesFromAPI(
  state: PatientState,
  treatmentId: string,
  signal?: AbortSignal,
  _coefficientMultipliers?: Record<string, number>,
): Promise<ExtendedOutcomes> {
  try {
    return await fetchPrediction(state, treatmentId, signal);
  } catch {
    // Backend unavailable — use synthetic model
    return computeSyntheticOutcomes(state, treatmentId);
  }
}
