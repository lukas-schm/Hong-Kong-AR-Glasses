import { createContext, useContext, useReducer, type Dispatch } from 'react';
import type { PatientState, Action } from '../types';

export const initialState: PatientState = {
  currentPatientId: 'Elena Kovacs',
  currentPatientInfo: 'Bed C-02 · 78y · Severe sepsis · ICU Day 3',
  loadedPatientProfile: {},

  sofa: 11,
  sapsii: 58,
  lactate: 4.8,
  vaso: 'YES',
  ventilation: 'YES',
  aki: 2,
  dialysis: 'NO',

  pct: 8.6,
  crp: 312,
  wbc: 18.7,
  temperature: 39.2,
  cultureResult: 'pending',
  sourceIdentified: 'NO',
  pathogenIdentified: 'NO',
  antibioticDays: 3,

  age: 78,
  female: 'YES',
  comorbidity: 6,
  immunocompromised: 'NO',

  heartRate: 118,
  respRate: 27,
  spo2: 90,
  map: 58,
  urineOutput: 540,
  weight: 62,

  activeTreatmentId: 'continue',
  treatmentInGraph: true,
  extraConfounders: [],
  chartVisible: true,
  selectedNodeId: null,
  outcomeLoading: true,
  apiOutcomes: null,
  apiConnected: false,
  dagViewMode: 'compressed',
  coefficientMultipliers: {},
  modifiedKeys: [],
  selectedPatients: [],
  ghostScenarios: [],
  lastDropPosition: null,
};

const PATIENT_PARAMETER_KEYS: Array<keyof PatientState> = [
  'sofa', 'sapsii', 'lactate', 'vaso', 'ventilation', 'aki', 'dialysis',
  'pct', 'crp', 'wbc', 'temperature', 'cultureResult',
  'sourceIdentified', 'pathogenIdentified', 'antibioticDays',
  'age', 'female', 'comorbidity', 'immunocompromised',
  'heartRate', 'respRate', 'spo2', 'map', 'urineOutput', 'weight',
  'treatmentInGraph', 'activeTreatmentId', 'extraConfounders',
];

function reducer(state: PatientState, action: Action): PatientState {
  switch (action.type) {
    case 'LOAD_PATIENT_PROFILE': {
      const overrides = action.profile as Partial<PatientState>;
      const next = { ...state };
      for (const k of PATIENT_PARAMETER_KEYS) {
        if (k in overrides) {
          (next as Record<string, unknown>)[k] = (overrides as Record<string, unknown>)[k];
        } else {
          (next as Record<string, unknown>)[k] = (initialState as Record<string, unknown>)[k];
        }
      }
      return {
        ...next,
        currentPatientId: action.patientId,
        currentPatientInfo: action.patientInfo,
        loadedPatientProfile: action.profile,
        apiOutcomes: null,
        apiConnected: false,
        outcomeLoading: true,
        selectedNodeId: null,
        selectedPatients: [],
        ghostScenarios: [],
        extraConfounders: (overrides.extraConfounders as string[]) ?? [],
        coefficientMultipliers: {},
        modifiedKeys: [],
      };
    }

    case 'SET_VARIABLE': {
      const prevVal = (state as Record<string, unknown>)[action.key];
      const changed = prevVal !== action.value;
      const modifiedKeys = changed
        ? [...new Set([...state.modifiedKeys, action.key])]
        : state.modifiedKeys;
      return {
        ...state,
        [action.key]: action.value,
        modifiedKeys,
        outcomeLoading: changed,
        apiOutcomes: changed ? null : state.apiOutcomes,
      };
    }

    case 'SET_ACTIVE_TREATMENT': {
      if (action.treatmentId === state.activeTreatmentId) return state;
      return {
        ...state,
        activeTreatmentId: action.treatmentId,
        outcomeLoading: true,
        apiOutcomes: null,
      };
    }

    case 'SELECT_NODE':
      return { ...state, selectedNodeId: action.nodeId };

    case 'TOGGLE_PATIENT': {
      const exists = state.selectedPatients.some(p => p.id === action.patient.id);
      return {
        ...state,
        selectedPatients: exists
          ? state.selectedPatients.filter(p => p.id !== action.patient.id)
          : [...state.selectedPatients, action.patient],
      };
    }

    case 'PUSH_GHOST':
      return { ...state, ghostScenarios: [...state.ghostScenarios, action.scenario] };

    case 'ADD_TREATMENT_TO_GRAPH':
      return {
        ...state,
        treatmentInGraph: true,
        chartVisible: true,
        activeTreatmentId: action.treatmentId ?? state.activeTreatmentId,
        outcomeLoading: true,
        apiOutcomes: null,
      };

    case 'REMOVE_TREATMENT_FROM_GRAPH':
      return { ...state, treatmentInGraph: false };

    case 'ADD_CONFOUNDER_TO_GRAPH': {
      if (state.extraConfounders.includes(action.confounderId)) return state;
      return {
        ...state,
        extraConfounders: [...state.extraConfounders, action.confounderId],
        outcomeLoading: true,
        apiOutcomes: null,
      };
    }

    case 'REMOVE_CONFOUNDER_FROM_GRAPH':
      return {
        ...state,
        extraConfounders: state.extraConfounders.filter(id => id !== action.confounderId),
      };

    case 'SET_OUTCOME_LOADING':
      return { ...state, outcomeLoading: true };

    case 'SET_OUTCOME_READY':
      return { ...state, outcomeLoading: false };

    case 'SET_API_OUTCOMES':
      return { ...state, apiOutcomes: action.outcomes, outcomeLoading: false };

    case 'SET_API_CONNECTED':
      return { ...state, apiConnected: action.connected };

    case 'SET_DAG_VIEW_MODE':
      return { ...state, dagViewMode: action.mode };

    case 'SET_COEFFICIENT_MULTIPLIER':
      return {
        ...state,
        coefficientMultipliers: { ...state.coefficientMultipliers, [action.key]: action.value },
        outcomeLoading: true,
        apiOutcomes: null,
      };

    case 'RESET_COEFFICIENT_MULTIPLIERS':
      return { ...state, coefficientMultipliers: {}, outcomeLoading: true, apiOutcomes: null };

    case 'RESET_PATIENT_PARAMETERS': {
      const base = state.loadedPatientProfile as Partial<PatientState>;
      const next = { ...state };
      for (const k of PATIENT_PARAMETER_KEYS) {
        if (k in base) {
          (next as Record<string, unknown>)[k] = (base as Record<string, unknown>)[k];
        } else {
          (next as Record<string, unknown>)[k] = (initialState as Record<string, unknown>)[k];
        }
      }
      return { ...next, modifiedKeys: [], outcomeLoading: true, apiOutcomes: null };
    }

    case 'RESET_VARIABLE': {
      const src = state.loadedPatientProfile as Partial<PatientState>;
      const orig = action.key in src
        ? (src as Record<string, unknown>)[action.key]
        : (initialState as Record<string, unknown>)[action.key];
      return {
        ...state,
        [action.key]: orig,
        modifiedKeys: state.modifiedKeys.filter(k => k !== action.key),
        outcomeLoading: true,
        apiOutcomes: null,
      };
    }

    case 'RESET_STATE':
      return { ...initialState };

    default:
      return state;
  }
}

export const PatientStateContext = createContext<PatientState>(initialState);
export const PatientDispatchContext = createContext<Dispatch<Action>>(() => {});

export function usePatientReducer() {
  return useReducer(reducer, initialState);
}

export function usePatientState() {
  return useContext(PatientStateContext);
}

export function usePatientDispatch() {
  return useContext(PatientDispatchContext);
}
