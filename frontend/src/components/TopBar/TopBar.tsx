import './TopBar.css';

interface TopBarProps {
  overviewOpen: boolean;
  onBackToOverview: () => void;
  patientInfo?: string;
  patientId?: string;
}

export function TopBar({ overviewOpen, onBackToOverview, patientInfo, patientId }: TopBarProps) {
  return (
    <div className="top-bar">
      <div className="top-bar__logo">Causal CDSS</div>

      <div className="top-bar__separator" />

      {overviewOpen ? (
        <span className="top-bar__overview-label">ICU Overview</span>
      ) : (
        <button className="top-bar__back-btn" onClick={onBackToOverview}>
          ← Back to Patients
        </button>
      )}

      {!overviewOpen && patientId && (
        <div className="top-bar__patient-pill">
          <span className="top-bar__blink-dot" />
          <span className="top-bar__patient-name">{patientId}</span>
          {patientInfo && <span className="top-bar__patient-info">{patientInfo}</span>}
        </div>
      )}

      <span className="top-bar__question">
        After 72h of broad-spectrum antibiotics — Continue, De-escalate, or Cease?
      </span>

      <div className="top-bar__spacer" />

      <span className="top-bar__badge">28-day mortality · ICU Day 3</span>
    </div>
  );
}
