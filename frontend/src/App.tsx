import { useState } from 'react';
import { PatientStateContext, PatientDispatchContext, usePatientReducer } from './hooks/usePatientState';
import { ErrorBoundary } from './components/ErrorBoundary';
import { TopBar } from './components/TopBar/TopBar';
import { CausalModelTab } from './components/CausalModelTab/CausalModelTab';
import { PatientOverview } from './components/PatientOverview/PatientOverview';
import { exemplarPatients, type ExemplarPatient } from './data/exemplarPatients';
import './App.css';

function AppContent() {
  const [state, dispatch] = usePatientReducer();
  const [selectedPatient, setSelectedPatient] = useState<ExemplarPatient | null>(null);

  const handleSelectPatient = (patient: ExemplarPatient) => {
    dispatch({
      type: 'LOAD_PATIENT_PROFILE',
      patientId: patient.name,
      patientInfo: `${patient.bed} · ${patient.subtitle}`,
      profile: patient.profile,
    });
    setSelectedPatient(patient);
  };

  const handleBackToOverview = () => {
    setSelectedPatient(null);
  };

  return (
    <PatientStateContext.Provider value={state}>
      <PatientDispatchContext.Provider value={dispatch}>
        <div className="app">
          <TopBar
            overviewOpen={!selectedPatient}
            onBackToOverview={handleBackToOverview}
            patientId={selectedPatient?.name}
            patientInfo={selectedPatient ? `${selectedPatient.bed} · ${selectedPatient.subtitle}` : undefined}
          />
          <div className="content">
            {!selectedPatient ? (
              <PatientOverview
                patients={exemplarPatients}
                onSelectPatient={handleSelectPatient}
              />
            ) : (
              <CausalModelTab />
            )}
          </div>
        </div>
      </PatientDispatchContext.Provider>
    </PatientStateContext.Provider>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <AppContent />
    </ErrorBoundary>
  );
}
