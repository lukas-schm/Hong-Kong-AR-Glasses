export interface PatientState {
  currentPatientId: string;
  currentPatientInfo: string;
  loadedPatientProfile: Partial<PatientState>;

  /* ── Core illness severity ── */
  sofa: number;          // 0-24 pts
  sapsii: number;        // 0-100 pts
  lactate: number;       // mmol/L
  vaso: 'YES' | 'NO';
  ventilation: 'YES' | 'NO';
  aki: number;           // AKI stage 0-3
  dialysis: 'YES' | 'NO';

  /* ── Infection / microbiology markers ── */
  pct: number;           // procalcitonin ng/mL
  crp: number;           // CRP mg/L
  wbc: number;           // WBC ×10⁹/L
  temperature: number;   // °C
  cultureResult: 'positive' | 'negative' | 'pending';
  sourceIdentified: 'YES' | 'NO';
  pathogenIdentified: 'YES' | 'NO';
  antibioticDays: number; // days on current antibiotics at 72h decision

  /* ── Demographics ── */
  age: number;
  female: 'YES' | 'NO';
  comorbidity: number;   // CCI score
  immunocompromised: 'YES' | 'NO';

  /* ── Additional vitals ── */
  heartRate: number;
  respRate: number;
  spo2: number;
  map: number;           // Mean Arterial Pressure mmHg
  urineOutput: number;   // mL/24h
  weight: number;        // kg

  /* ── Treatment & UI state ── */
  activeTreatmentId: string;
  treatmentInGraph: boolean;
  extraConfounders: string[];
  chartVisible: boolean;
  selectedNodeId: string | null;
  outcomeLoading: boolean;
  apiOutcomes: ExtendedOutcomes | null;
  apiConnected: boolean;
  dagViewMode: 'compressed' | 'full';
  coefficientMultipliers: Record<string, number>;
  modifiedKeys: string[];
  selectedPatients: SimilarPatient[];
  ghostScenarios: GhostScenario[];
  lastDropPosition: { nodeId: string; clientX: number; clientY: number } | null;
}

export interface GhostScenario {
  withTreatment: number;
  withoutTreatment: number;
}

export interface SimilarPatient {
  id: string;
  age: number;
  sofa: number;
  crp: number;
  cultureResult: 'positive' | 'negative' | 'pending';
  antibioticDays: number;
  vaso: 'YES' | 'NO';
  aki: number;
  treatment: string;
  outcome: 'Survived' | 'Deceased';
  sim: number;
}

export interface TreatmentDef {
  id: string;
  label: string;
  chipLabel: string;
  color: string;
  description: string;
}

export interface DagNode {
  id: string;
  label: string;
  stateKey?: keyof Pick<PatientState,
    'sofa' | 'sapsii' | 'lactate' | 'vaso' | 'ventilation' | 'aki' | 'dialysis' |
    'pct' | 'crp' | 'wbc' | 'temperature' | 'cultureResult' | 'sourceIdentified' |
    'pathogenIdentified' | 'antibioticDays' |
    'age' | 'female' | 'comorbidity' | 'immunocompromised' |
    'heartRate' | 'respRate' | 'spo2' | 'map' | 'urineOutput' | 'weight'
  >;
  type: 'confounder' | 'treatment' | 'outcome';
  x: number;
  y: number;
  unit?: string;
  varType?: 'binary' | 'continuous' | 'categorical';
  min?: number;
  max?: number;
  step?: number;
  observed?: boolean;
  toggleLabels?: { yes: string; no: string };
  category?: string;
  categoricalOptions?: string[];
}

export interface DagEdge {
  source: string;
  target: string;
  style: 'solid' | 'dashed';
  color: string;
}

export interface ExtendedOutcomes {
  /* Primary: 28-day mortality */
  withTreatment: number;
  withoutTreatment: number;
  effect: number;
  ate: number;
  ateLowerBound: number;
  ateUpperBound: number;
  confidence: 'high' | 'moderate' | 'low';

  /* Secondary outcomes */
  vfdDays?: number;            // ventilator-free days
  icuLosDays?: number;         // ICU length of stay (days)
  cdiffRisk?: number;          // C. difficile risk (%)
  resistanceRisk?: number;     // AMR development risk (%)

  /* F23: out-of-distribution check from API */
  ood?: {
    mahalanobis: number;
    trainingP99: number;
    outOfDistribution: boolean;
  };

  patientFeatureImportance?: {
    referenceMortality: number;
    baseMortality: number;
    contributions: Array<{
      feature: string;
      label: string;
      patientValue: boolean | number | string;
      referenceValue: boolean | number | string;
      contribution: number;
      contributionLb?: number;
      contributionUb?: number;
      importance: number;
      direction: 'increase' | 'decrease';
    }>;
  };
  treatmentEffectImportance?: {
    referenceAte: number;
    patientAte: number;
    contributions: Array<{
      feature: string;
      label: string;
      patientValue: boolean | number | string;
      referenceValue: boolean | number | string;
      contribution: number;
      importance: number;
      direction: 'more_benefit' | 'less_benefit';
    }>;
  };
}

export type Action =
  | { type: 'LOAD_PATIENT_PROFILE'; patientId: string; patientInfo: string; profile: Partial<PatientState> }
  | { type: 'SET_VARIABLE'; key: string; value: string | number }
  | { type: 'SET_ACTIVE_TREATMENT'; treatmentId: string }
  | { type: 'SELECT_NODE'; nodeId: string | null }
  | { type: 'TOGGLE_PATIENT'; patient: SimilarPatient }
  | { type: 'PUSH_GHOST'; scenario: GhostScenario }
  | { type: 'ADD_TREATMENT_TO_GRAPH'; treatmentId?: string }
  | { type: 'REMOVE_TREATMENT_FROM_GRAPH' }
  | { type: 'ADD_CONFOUNDER_TO_GRAPH'; confounderId: string }
  | { type: 'REMOVE_CONFOUNDER_FROM_GRAPH'; confounderId: string }
  | { type: 'SET_OUTCOME_READY' }
  | { type: 'SET_OUTCOME_LOADING' }
  | { type: 'SET_API_OUTCOMES'; outcomes: ExtendedOutcomes }
  | { type: 'SET_API_CONNECTED'; connected: boolean }
  | { type: 'SET_DAG_VIEW_MODE'; mode: 'compressed' | 'full' }
  | { type: 'SET_COEFFICIENT_MULTIPLIER'; key: string; value: number }
  | { type: 'RESET_COEFFICIENT_MULTIPLIERS' }
  | { type: 'RESET_PATIENT_PARAMETERS' }
  | { type: 'RESET_VARIABLE'; key: string }
  | { type: 'RESET_STATE' };
