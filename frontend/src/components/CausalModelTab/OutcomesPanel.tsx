import { useState, useEffect } from 'react';
import { usePatientState, usePatientDispatch } from '../../hooks/usePatientState';
import { TrajectoryChart } from './TrajectoryChart';
import { PatientFeatureImpact } from './PatientFeatureImpact';
import { SimilarPatients } from './SimilarPatients';
import { fetchSimilarPatients } from '../../api';
import type { SimilarPatient } from '../../types';
import './OutcomesPanel.css';

export function OutcomesPanel() {
  const state = usePatientState();
  const dispatch = usePatientDispatch();
  const [livePatients, setLivePatients] = useState<SimilarPatient[]>([]);

  useEffect(() => {
    if (!state.apiConnected || !state.apiOutcomes) return;
    const ac = new AbortController();
    fetchSimilarPatients(state, ac.signal)
      .then(r => { if (!ac.signal.aborted) setLivePatients(r.patients); })
      .catch(() => {});
    return () => ac.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.apiOutcomes, state.apiConnected]);

  const handleTogglePatient = (p: SimilarPatient) => {
    dispatch({ type: 'TOGGLE_PATIENT', patient: p });
  };

  const displayPatients = state.selectedPatients.length > 0
    ? state.selectedPatients
    : livePatients.length > 0 ? livePatients : SYNTHETIC_SIMILAR_PATIENTS;

  return (
    <div className="outcomes-panel">
      <div className="outcomes-panel__content">
        <TrajectoryChart />

        {state.apiOutcomes?.patientFeatureImportance && (
          <PatientFeatureImpact outcomes={state.apiOutcomes} treatmentId={state.activeTreatmentId} />
        )}

        <SimilarPatients
          patients={displayPatients}
          selectedPatients={state.selectedPatients}
          onTogglePatient={handleTogglePatient}
        />
      </div>
    </div>
  );
}

/* ── Synthetic fallback patients (demo mode) ── */
const SYNTHETIC_SIMILAR_PATIENTS: SimilarPatient[] = [
  { id: 'sp-01', age: 71, sofa: 10, crp: 178, cultureResult: 'pending',  antibioticDays: 3, vaso: 'YES', aki: 2, treatment: 'continue',   outcome: 'Survived', sim: 0.87 },
  { id: 'sp-02', age: 64, sofa: 7,  crp: 241, cultureResult: 'positive', antibioticDays: 3, vaso: 'NO',  aki: 1, treatment: 'deescalate', outcome: 'Survived', sim: 0.82 },
  { id: 'sp-03', age: 80, sofa: 12, crp: 312, cultureResult: 'pending',  antibioticDays: 3, vaso: 'YES', aki: 3, treatment: 'continue',   outcome: 'Deceased', sim: 0.79 },
  { id: 'sp-04', age: 55, sofa: 5,  crp: 34,  cultureResult: 'negative', antibioticDays: 3, vaso: 'NO',  aki: 0, treatment: 'cease',      outcome: 'Survived', sim: 0.74 },
  { id: 'sp-05', age: 67, sofa: 9,  crp: 204, cultureResult: 'positive', antibioticDays: 3, vaso: 'YES', aki: 1, treatment: 'deescalate', outcome: 'Survived', sim: 0.71 },
  { id: 'sp-06', age: 73, sofa: 8,  crp: 118, cultureResult: 'negative', antibioticDays: 4, vaso: 'NO',  aki: 1, treatment: 'cease',      outcome: 'Survived', sim: 0.68 },
  { id: 'sp-07', age: 59, sofa: 6,  crp: 267, cultureResult: 'positive', antibioticDays: 3, vaso: 'YES', aki: 0, treatment: 'deescalate', outcome: 'Survived', sim: 0.65 },
  { id: 'sp-08', age: 82, sofa: 14, crp: 143, cultureResult: 'pending',  antibioticDays: 3, vaso: 'YES', aki: 3, treatment: 'continue',   outcome: 'Deceased', sim: 0.61 },
];
