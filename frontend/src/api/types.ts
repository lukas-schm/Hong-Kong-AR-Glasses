export interface ApiPredictRequest {
  sofa: number;
  sapsii: number;
  lactate: number;
  vaso: boolean;
  ventilation: boolean;
  aki: number;
  dialysis: boolean;
  pct: number;
  crp: number;
  wbc: number;
  temperature: number;
  culture_result: string;
  source_identified: boolean;
  pathogen_identified: boolean;
  antibiotic_days: number;
  age: number;
  female: boolean;
  comorbidity: number;
  immunocompromised: boolean;
  heart_rate: number;
  resp_rate: number;
  spo2: number;
  map: number;
  urine_output: number;
  weight: number;
  treatment_id: string;
}

export interface ApiCoefficientInfo {
  key: string;
  label: string;
  value: number;
  min: number;
  max: number;
}
