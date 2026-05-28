import { usePatientState, usePatientDispatch } from '../../hooks/usePatientState';
import type { PatientState } from '../../types';
import './VariableDrawer.css';

type EditableKey = keyof Pick<PatientState,
  'sofa' | 'sapsii' | 'lactate' | 'vaso' | 'ventilation' | 'aki' | 'dialysis' |
  'crp' | 'wbc' | 'temperature' | 'cultureResult' |
  'sourceIdentified' | 'pathogenIdentified' | 'antibioticDays' |
  'age' | 'female' | 'comorbidity' | 'immunocompromised' |
  'heartRate' | 'respRate' | 'spo2' | 'map' | 'urineOutput' | 'weight'
>;

interface VarDef {
  key: EditableKey;
  label: string;
  type: 'binary' | 'continuous' | 'categorical';
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  toggleLabels?: { yes: string; no: string };
  options?: string[];
}

const SECTIONS: { title: string; vars: VarDef[] }[] = [
  {
    title: 'Illness Severity',
    vars: [
      { key: 'sofa', label: 'SOFA Score', type: 'continuous', unit: 'pts', min: 0, max: 24, step: 1 },
      { key: 'sapsii', label: 'SAPS II', type: 'continuous', unit: 'pts', min: 0, max: 100, step: 1 },
      { key: 'lactate', label: 'Lactate', type: 'continuous', unit: 'mmol/L', min: 0.5, max: 12, step: 0.1 },
      { key: 'vaso', label: 'Vasopressors', type: 'binary' },
      { key: 'ventilation', label: 'Ventilation', type: 'binary' },
      { key: 'aki', label: 'AKI Stage', type: 'continuous', min: 0, max: 3, step: 1 },
      { key: 'dialysis', label: 'Dialysis (RRT)', type: 'binary' },
    ],
  },
  {
    title: 'Infection Markers',
    vars: [
      { key: 'crp', label: 'CRP', type: 'continuous', unit: 'mg/L', min: 1, max: 500, step: 1 },
      { key: 'wbc', label: 'WBC', type: 'continuous', unit: '×10⁹/L', min: 0.5, max: 50, step: 0.1 },
      { key: 'temperature', label: 'Temperature', type: 'continuous', unit: '°C', min: 34, max: 42, step: 0.1 },
    ],
  },
  {
    title: 'Microbiology',
    vars: [
      { key: 'cultureResult', label: 'Blood Culture', type: 'categorical', options: ['positive', 'negative', 'pending'] },
      { key: 'sourceIdentified', label: 'Source Identified', type: 'binary' },
      { key: 'pathogenIdentified', label: 'Pathogen ID', type: 'binary' },
      { key: 'antibioticDays', label: 'Antibiotic Days', type: 'continuous', unit: 'days', min: 1, max: 14, step: 1 },
    ],
  },
  {
    title: 'Demographics',
    vars: [
      { key: 'age', label: 'Age', type: 'continuous', unit: 'yrs', min: 18, max: 95, step: 1 },
      { key: 'female', label: 'Gender', type: 'binary', toggleLabels: { yes: 'Female', no: 'Male' } },
      { key: 'comorbidity', label: 'Comorbidity (CCI)', type: 'continuous', unit: 'pts', min: 0, max: 20, step: 1 },
      { key: 'immunocompromised', label: 'Immunocompromised', type: 'binary' },
    ],
  },
  {
    title: 'Other Vitals',
    vars: [
      { key: 'map', label: 'MAP', type: 'continuous', unit: 'mmHg', min: 40, max: 120, step: 1 },
      { key: 'heartRate', label: 'Heart Rate', type: 'continuous', unit: 'bpm', min: 40, max: 180, step: 1 },
      { key: 'respRate', label: 'Resp. Rate', type: 'continuous', unit: '/min', min: 6, max: 40, step: 1 },
      { key: 'spo2', label: 'SpO₂', type: 'continuous', unit: '%', min: 60, max: 100, step: 1 },
      { key: 'urineOutput', label: 'Urine Output', type: 'continuous', unit: 'mL/24h', min: 0, max: 4000, step: 50 },
      { key: 'weight', label: 'Weight', type: 'continuous', unit: 'kg', min: 30, max: 200, step: 1 },
    ],
  },
];

const CAT_SHORT: Record<string, string> = {
  positive: 'pos',
  negative: 'neg',
  pending: 'pend',
};

interface VariableDrawerProps {
  isOpen: boolean;
  onToggle: () => void;
}

export function VariableDrawer({ isOpen, onToggle }: VariableDrawerProps) {
  const state = usePatientState();
  const dispatch = usePatientDispatch();

  const handleChange = (key: EditableKey, value: string | number) => {
    dispatch({ type: 'SET_VARIABLE', key, value });
  };

  return (
    <>
      {/* ── Collapsed tab ── */}
      <button
        className={`var-drawer__tab${isOpen ? ' var-drawer__tab--open' : ''}`}
        onClick={onToggle}
        aria-label={isOpen ? 'Close patient data' : 'Open patient data'}
      >
        <span className="var-drawer__tab-label">Patient Data</span>
      </button>

      {/* ── Expanded panel ── */}
      <div className={`var-drawer${isOpen ? ' var-drawer--open' : ''}`}>
        <div className="var-drawer__inner">
          {SECTIONS.map((section, sectionIdx) => (
            <div key={section.title} className="var-drawer__section">
              <div className="var-drawer__section-top-row">
                <span className="var-drawer__section-label">{section.title}</span>
                {sectionIdx === 0 && (
                  <button className="var-drawer__close" onClick={onToggle} aria-label="Close">
                    &#x2715;
                  </button>
                )}
              </div>

              {section.vars.map(v => {
                const val = (state as Record<string, unknown>)[v.key];
                const isModified = state.modifiedKeys.includes(v.key);

                return (
                  <div
                    key={v.key}
                    className={`var-drawer__row${v.type === 'categorical' ? ' var-drawer__row--cat' : ''}`}
                  >
                    <span
                      className="var-drawer__dot"
                      style={{ background: isModified ? 'var(--sienna)' : 'var(--text-dim)' }}
                    />
                    <span className="var-drawer__row-name">{v.label}</span>

                    <span className="var-drawer__row-control">
                      {v.type === 'binary' && (
                        <div className="var-drawer__inline-toggle">
                          <button
                            className={`var-drawer__inline-toggle-btn${val === 'YES' ? ' var-drawer__inline-toggle-btn--active' : ''}`}
                            onClick={() => handleChange(v.key, 'YES')}
                          >
                            {v.toggleLabels?.yes ?? 'YES'}
                          </button>
                          <button
                            className={`var-drawer__inline-toggle-btn${val === 'NO' ? ' var-drawer__inline-toggle-btn--active' : ''}`}
                            onClick={() => handleChange(v.key, 'NO')}
                          >
                            {v.toggleLabels?.no ?? 'NO'}
                          </button>
                        </div>
                      )}

                      {v.type === 'continuous' && (
                        <label className="var-drawer__inline-input-wrap">
                          <input
                            className="var-drawer__inline-input"
                            type="number"
                            step={v.step ?? 1}
                            min={v.min}
                            max={v.max}
                            value={typeof val === 'number' ? val : 0}
                            onChange={e => {
                              const n = parseFloat(e.target.value);
                              if (!Number.isNaN(n)) handleChange(v.key, n);
                            }}
                          />
                          {v.unit && <span className="var-drawer__inline-unit">{v.unit}</span>}
                        </label>
                      )}

                      {v.type === 'categorical' && v.options && (
                        <div className="var-drawer__cat-options">
                          {v.options.map(opt => (
                            <button
                              key={opt}
                              className={`var-drawer__cat-btn var-drawer__cat-btn--${opt}${val === opt ? ' var-drawer__cat-btn--active' : ''}`}
                              onClick={() => handleChange(v.key, opt)}
                            >
                              {CAT_SHORT[opt] ?? opt}
                            </button>
                          ))}
                        </div>
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
