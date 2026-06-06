import type { PatientState } from '../types';
import type { ExemplarPatient } from '../data/exemplarPatients';
import { initialState } from '../hooks/usePatientState';
import type { HKPatient } from '../data/hkPatients';
import type { Lang } from '../i18n';
import { bestArm, type ArmPredictions } from './prediction';

/** Build a full PatientState from an HK record so the trained model can score it. */
export function hkToPatientState(p: HKPatient): PatientState {
  return {
    ...initialState,
    ...p.profile,
    currentPatientId: p.nameEn,
    currentPatientInfo: p.subtitle.en,
    loadedPatientProfile: p.profile,
  };
}

/**
 * Adapt an HK record to the ExemplarPatient shape consumed by GlassesHUD.
 * When live model predictions are supplied, they override the cached
 * outcome numbers so the HUD agrees with the dashboard.
 */
export function hkToExemplar(p: HKPatient, lang: Lang, preds?: ArmPredictions): ExemplarPatient {
  const zh = lang === 'zh-HK';
  const values = preds?.values ?? {
    continue: p.outcomes.continue,
    deescalate: p.outcomes.deescalate,
    cease: p.outcomes.cease,
  };
  return {
    id: p.hkid,
    name: zh ? p.nameZh : p.nameEn,
    bed: zh ? p.ward.zh : p.ward.en,
    subtitle: zh ? p.subtitle.zh : p.subtitle.en,
    gender: p.sex === 'F' ? 'Female' : 'Male',
    tags: p.tags.map((t) => (zh ? t.zh : t.en)),
    highlights: [],
    outcomes: {
      ...values,
      recommendation: zh ? p.outcomes.recommendation.zh : p.outcomes.recommendation.en,
      recommendedAction: preds ? bestArm(preds.values) : p.outcomes.recommendedAction,
    },
    profile: p.profile,
  };
}
