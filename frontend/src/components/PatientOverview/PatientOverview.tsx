import { useEffect, useMemo, useState } from 'react';
import type { ExemplarPatient } from '../../data/exemplarPatients';
import type { PatientState } from '../../types';
import { fetchPrediction } from '../../api';
import './PatientOverview.css';

interface PatientOverviewProps {
  patients: ExemplarPatient[];
  onSelectPatient: (patient: ExemplarPatient) => void;
}

type TreatmentId = 'continue' | 'deescalate' | 'cease';

interface LiveOutcomes {
  continue: number;
  deescalate: number;
  cease: number;
  recommended: TreatmentId;
  effect: number; // pp difference between best and worst arm
}

const SHORT_LABELS: Record<TreatmentId, string> = {
  continue: 'Continue',
  deescalate: 'De-escalate',
  cease: 'Cease',
};

const TREATMENT_TONE: Record<TreatmentId, string> = {
  continue: 'card__outcome--continue',
  deescalate: 'card__outcome--deescalate',
  cease: 'card__outcome--cease',
};


function profileToState(profile: ExemplarPatient['profile']): PatientState | null {
  const required: Array<keyof PatientState> = [
    'sofa', 'sapsii', 'lactate', 'vaso', 'ventilation', 'aki', 'dialysis',
    'pct', 'crp', 'wbc', 'temperature', 'cultureResult', 'sourceIdentified',
    'pathogenIdentified', 'antibioticDays', 'age', 'female', 'comorbidity',
    'immunocompromised', 'heartRate', 'respRate', 'spo2', 'map', 'urineOutput', 'weight',
  ];
  for (const key of required) {
    if (profile[key] === undefined) return null;
  }
  return profile as PatientState;
}

export function PatientOverview({ patients, onSelectPatient }: PatientOverviewProps) {
  const [liveOutcomes, setLiveOutcomes] = useState<Record<string, LiveOutcomes>>({});
  const [loading, setLoading] = useState(true);
  const [alertThreshold, setAlertThreshold] = useState(40);

  useEffect(() => {
    let active = true;
    const ac = new AbortController();
    const treatmentIds: TreatmentId[] = ['continue', 'deescalate', 'cease'];

    async function load() {
      setLoading(true);
      const entries = await Promise.all(
        patients.map(async (patient) => {
          const state = profileToState(patient.profile);
          if (!state) return [patient.id, null] as const;
          try {
            const results = await Promise.all(
              treatmentIds.map((tid) => fetchPrediction(state, tid, ac.signal)),
            );
            const continueVal = results[0].withTreatment;
            const deescalateVal = results[1].withTreatment;
            const ceaseVal = results[2].withTreatment;
            const arms: Array<[TreatmentId, number]> = [
              ['continue', continueVal],
              ['deescalate', deescalateVal],
              ['cease', ceaseVal],
            ];
            const sorted = [...arms].sort((a, b) => a[1] - b[1]);
            const best = sorted[0][0];
            const worst = sorted[sorted.length - 1][1];
            const bestVal = sorted[0][1];
            return [
              patient.id,
              {
                continue: continueVal,
                deescalate: deescalateVal,
                cease: ceaseVal,
                recommended: best,
                effect: worst - bestVal,
              },
            ] as const;
          } catch {
            return [patient.id, null] as const;
          }
        }),
      );
      if (!active) return;
      const next: Record<string, LiveOutcomes> = {};
      for (const [id, outcome] of entries) {
        if (outcome) next[id] = outcome;
      }
      setLiveOutcomes(next);
      setLoading(false);
    }

    load();
    return () => {
      active = false;
      ac.abort();
    };
  }, [patients]);

  const totalHighRisk = useMemo(() => {
    return patients.reduce((acc, p) => {
      const live = liveOutcomes[p.id];
      const minMortality = live
        ? Math.min(live.continue, live.deescalate, live.cease)
        : Math.min(p.outcomes.continue, p.outcomes.deescalate, p.outcomes.cease);
      return acc + (minMortality >= alertThreshold ? 1 : 0);
    }, 0);
  }, [patients, liveOutcomes, alertThreshold]);

  return (
    <section className="overview">
      <header className="overview__header">
        <div className="overview__heading">
          <h1 className="overview__title">ICU Overview</h1>
          <p className="overview__desc">
            Patients awaiting an antibiotic continuation decision at 72&nbsp;hours.
            Each card shows the causal 28-day mortality estimate under three treatment strategies.
          </p>
        </div>

        <div className="overview__meta">
          <div className="overview__meta-stat">
            <span className="overview__meta-stat-value">{patients.length}</span>
            <span className="overview__meta-stat-label">Patients</span>
          </div>
          <div className="overview__meta-stat overview__meta-stat--risk">
            <span className="overview__meta-stat-value">{totalHighRisk}</span>
            <span className="overview__meta-stat-label">High risk</span>
          </div>

          <label className="overview__threshold">
            <span className="overview__threshold-label">High-risk threshold</span>
            <div className="overview__threshold-control">
              <input
                className="overview__threshold-slider"
                type="range"
                min={0}
                max={100}
                step={1}
                value={alertThreshold}
                style={{
                  background: `linear-gradient(to right, var(--continue-color) ${alertThreshold}%, rgba(46, 139, 255, 0.18) ${alertThreshold}%)`,
                }}
                onChange={(e) => {
                  const next = Number(e.target.value);
                  if (Number.isNaN(next)) return;
                  setAlertThreshold(Math.max(0, Math.min(100, next)));
                }}
              />
              <span className="overview__threshold-value">{alertThreshold}%</span>
            </div>
            <div className="overview__threshold-scale" aria-hidden="true">
              <span>0%</span>
              <span>100%</span>
            </div>
          </label>
        </div>
      </header>

      <div className="overview__grid">
        {patients.map((patient) => {
          const live = liveOutcomes[patient.id];
          const cont = live?.continue ?? patient.outcomes.continue;
          const dees = live?.deescalate ?? patient.outcomes.deescalate;
          const ceas = live?.cease ?? patient.outcomes.cease;
          const recommended: TreatmentId = live?.recommended ?? patient.outcomes.recommendedAction;
          const minMortality = Math.min(cont, dees, ceas);
          const showAlert = minMortality >= alertThreshold;
          const ageBadge = patient.profile.age !== undefined ? `${patient.profile.age}y` : '';
          const sex = patient.profile.female === 'YES' ? 'F' : patient.profile.female === 'NO' ? 'M' : '';

          return (
            <button
              key={patient.id}
              className="card"
              onClick={() => onSelectPatient(patient)}
            >
              <div className="card__head">
                <div className="card__head-top">
                  <div className="card__title">
                    <span className="card__name">{patient.name}</span>
                    {ageBadge && <span className="card__age">· {ageBadge}{sex ? ` · ${sex}` : ''}</span>}
                  </div>
                  <span className="card__id">#{patient.id}</span>
                </div>
                <div className="card__head-row">
                  <span className="card__bed">{patient.bed}</span>
                  <span className={`card__alert ${showAlert ? '' : 'card__alert--placeholder'}`}>
                    <span className="card__alert-icon">!</span>
                    HIGH RISK
                  </span>
                </div>
                <span className="card__subtitle">{patient.subtitle}</span>
              </div>

              <div className="card__tags">
                {patient.tags.map((t) => (
                  <span key={t} className="card__tag">{t}</span>
                ))}
              </div>

              <div className="card__highlights">
                {patient.highlights.map((h) => (
                  <div key={h.label} className="card__hl">
                    <span className="card__hl-label">{h.label}</span>
                    <span className="card__hl-value">{h.value}</span>
                  </div>
                ))}
              </div>

              <div className="card__outcome-row">
                {(['continue', 'deescalate', 'cease'] as TreatmentId[]).map((tid) => {
                  const val = tid === 'continue' ? cont : tid === 'deescalate' ? dees : ceas;
                  const isRec = tid === recommended;
                  return (
                    <div
                      key={tid}
                      className={`card__outcome ${TREATMENT_TONE[tid]} ${isRec ? 'card__outcome--recommended' : ''}`}
                    >
                      <span className="card__outcome-label">{SHORT_LABELS[tid]}</span>
                      <span className="card__outcome-value">
                        {loading && !live ? '…' : `${val.toFixed(1)}%`}
                      </span>
                      <span className="card__outcome-sub">28-day mortality</span>
                    </div>
                  );
                })}
              </div>

              <div className="card__cta">Open patient →</div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
