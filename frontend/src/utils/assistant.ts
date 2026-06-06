import type { PatientState } from '../types';
import { hkPatients, type HKPatient } from '../data/hkPatients';
import { hkToPatientState } from './hkAdapter';
import { bestArm, cachedArmValues, type Arm, type ArmPredictions } from './prediction';
import { fetchPrediction } from '../api';
import { monitor } from './monitor';

/* ────────────────────────────────────────────────────────────────────────
   Shared assistant engine — the single way to engage with the tool, by
   voice (AR glasses) or by chat. Parses English and written Cantonese /
   Traditional Chinese utterances into intents:

     · open a patient        — just say a name or HKID ("陳大文", "Chan")
     · show all patients     — "show all patients" / 「所有病人」
     · query a vital         — "what's the SOFA score?" / 「乳酸幾多？」
     · simulate intervention — "give albumin" / 「俾白蛋白」(scored live
                               against the trained causal model)
     · mortality overview    — "current mortality?" / 「死亡率係幾多？」
   ──────────────────────────────────────────────────────────────────────── */

export interface AssistantContext {
  patient: HKPatient | null;
  basePredictions: ArmPredictions | null;
  source?: 'voice' | 'chat';
}

/** A dictated value to be written into the patient record (mock DB). */
export interface RecordWrite {
  key: keyof PatientState;
  label: string;
  unit: string;
  value: number;
}

export type AssistantAction =
  | { type: 'open-patient'; patient: HKPatient }
  | { type: 'show-all' }
  | { type: 'write-record'; writes: RecordWrite[] };

export interface AssistantReply {
  text: string;
  action?: AssistantAction;
  intent?: string;
}

/* ── Writable record fields (voice charting → mock DB) ── */

interface FieldDef {
  key: keyof PatientState;
  match: string[];
  label: string;
  unit: string;
}

const FIELD_LEXICON: FieldDef[] = [
  { key: 'sofa', match: ['sofa'], label: 'SOFA', unit: '/24' },
  { key: 'sapsii', match: ['saps'], label: 'SAPS II', unit: '' },
  { key: 'lactate', match: ['lactate', '乳酸'], label: 'Lactate', unit: 'mmol/L' },
  { key: 'map', match: ['map', 'blood pressure', '血壓', '動脈壓'], label: 'MAP', unit: 'mmHg' },
  { key: 'heartRate', match: ['heart rate', 'pulse', '心率', '心跳'], label: 'Heart rate', unit: '/min' },
  { key: 'respRate', match: ['respiratory rate', 'resp rate', '呼吸率', '呼吸'], label: 'Resp rate', unit: '/min' },
  { key: 'spo2', match: ['spo2', 'oxygen', 'saturation', '血氧'], label: 'SpO₂', unit: '%' },
  { key: 'temperature', match: ['temperature', 'temp', '體溫'], label: 'Temperature', unit: '°C' },
  { key: 'wbc', match: ['wbc', 'white cell', '白血球'], label: 'WBC', unit: '×10⁹/L' },
  { key: 'crp', match: ['crp', 'c反應'], label: 'CRP', unit: 'mg/L' },
  { key: 'urineOutput', match: ['urine', '尿量', '尿'], label: 'Urine output', unit: 'mL/24h' },
  { key: 'antibioticDays', match: ['antibiotic day', 'abx day', '抗生素日'], label: 'Antibiotic days', unit: 'd' },
];

const WRITE_TRIGGERS = ['set ', 'record', 'chart', 'update', 'log ', 'is now', '改為', '記低', '記錄', '設定', '更新', '輸入'];

/** Parse a dictated chart entry: "set lactate to 3.2", "record SOFA 9", "乳酸記低 3.2". */
function parseWrite(userText: string, lower: string): RecordWrite | null {
  const isWrite = WRITE_TRIGGERS.some((w) => (hasCJK(w) ? userText.includes(w) : lower.includes(w)));
  if (!isWrite) return null;
  const field = FIELD_LEXICON.find((f) => f.match.some((m) => (hasCJK(m) ? userText.includes(m) : lower.includes(m))));
  if (!field) return null;
  const num = userText.match(/-?\d+(\.\d+)?/);
  if (!num) return null;
  return { key: field.key, label: field.label, unit: field.unit, value: Number(num[0]) };
}

export function hasCJK(text: string): boolean {
  return /[一-鿿]/.test(text);
}

/* ── Patient matching: name (EN word-boundary / zh substring) or HKID ── */

function matchPatient(text: string): HKPatient | undefined {
  const lower = text.toLowerCase();
  const hkidToken = lower.match(/[a-z]{1,2}\s?\d{6}\s?\(?\s?[a0-9]?\s?\)?/)?.[0]?.replace(/[^a-z0-9]/g, '');
  let best: { p: HKPatient; score: number } | null = null;
  for (const p of hkPatients) {
    let score = 0;
    if (text.includes(p.nameZh)) score += 4;
    const tokens = p.nameEn.toLowerCase().replace(',', '').split(/\s+/); // e.g. ['chan','tai','man']
    const matched = tokens.filter((tk) => new RegExp(`\\b${tk}\\b`).test(lower));
    // Surname alone is enough ("show patient Chan"); given-name tokens alone are too noisy.
    if (matched.includes(tokens[0])) score += 1 + matched.length;
    if (hkidToken && hkidToken.length >= 4 && p.hkid.toLowerCase().replace(/[^a-z0-9]/g, '').startsWith(hkidToken)) score += 4;
    if (score > (best?.score ?? 0)) best = { p, score };
  }
  return best?.p;
}

/* ── Vital / data queries ── */

interface VitalQuery {
  match: string[];
  reply: (p: HKPatient, zh: boolean) => string;
}

const VITAL_QUERIES: VitalQuery[] = [
  { match: ['sofa'], reply: (p, zh) => (zh ? `SOFA 評分：${p.profile.sofa}/24` : `SOFA score: ${p.profile.sofa}/24`) },
  { match: ['saps'], reply: (p) => `SAPS II: ${p.profile.sapsii}` },
  { match: ['lactate', '乳酸'], reply: (p, zh) => (zh ? `乳酸：${p.profile.lactate} mmol/L` : `Lactate: ${p.profile.lactate} mmol/L`) },
  { match: ['blood pressure', 'map', '血壓'], reply: (p, zh) => (zh ? `平均動脈壓：${p.profile.map} mmHg` : `MAP: ${p.profile.map} mmHg`) },
  { match: ['heart rate', 'pulse', '心率', '心跳'], reply: (p, zh) => (zh ? `心率：${p.profile.heartRate}/分鐘` : `Heart rate: ${p.profile.heartRate}/min`) },
  { match: ['temperature', '體溫'], reply: (p, zh) => (zh ? `體溫：${p.profile.temperature}°C` : `Temperature: ${p.profile.temperature}°C`) },
  { match: ['oxygen', 'spo2', 'saturation', '血氧'], reply: (p, zh) => (zh ? `血氧：${p.profile.spo2}%` : `SpO₂: ${p.profile.spo2}%`) },
  { match: ['white cell', 'wbc', '白血球'], reply: (p, zh) => (zh ? `白血球：${p.profile.wbc} ×10⁹/L` : `WBC: ${p.profile.wbc} ×10⁹/L`) },
  { match: ['crp', 'c反應'], reply: (p, zh) => (zh ? `C反應蛋白：${p.profile.crp} mg/L` : `CRP: ${p.profile.crp} mg/L`) },
  { match: ['culture', '培養'], reply: (p, zh) => (zh ? `血液培養：${p.profile.cultureResult}` : `Blood culture: ${p.profile.cultureResult}`) },
  {
    match: ['patient data', 'all data', 'vitals', 'overview', 'summary', '資料', '概覽', '生命表徵'],
    reply: (p, zh) => {
      const pr = p.profile;
      return zh
        ? `${p.nameZh}：SOFA ${pr.sofa}/24 · 乳酸 ${pr.lactate} · MAP ${pr.map} · 心率 ${pr.heartRate} · 血氧 ${pr.spo2}% · 體溫 ${pr.temperature}°C${pr.vaso === 'YES' ? ' · 升壓藥' : ''}${pr.ventilation === 'YES' ? ' · 呼吸機' : ''}`
        : `${p.nameEn}: SOFA ${pr.sofa}/24 · lactate ${pr.lactate} · MAP ${pr.map} · HR ${pr.heartRate} · SpO₂ ${pr.spo2}% · temp ${pr.temperature}°C${pr.vaso === 'YES' ? ' · on vasopressors' : ''}${pr.ventilation === 'YES' ? ' · ventilated' : ''}`;
    },
  },
];

/* ── Interventions (scored live against the trained model) ── */

interface Intervention {
  id: string;
  match: string[];
  /** State perturbation; omitted for pure antibiotic-arm switches. */
  apply?: (s: PatientState) => PatientState;
  arm?: Arm;
  describe: { en: string; zh: string };
  caveat?: { en: string; zh: string };
}

const INTERVENTIONS: Intervention[] = [
  {
    id: 'albumin',
    match: ['albumin', '白蛋白'],
    apply: (s) => ({ ...s, map: s.map + 5, urineOutput: s.urineOutput + 150 }),
    describe: {
      en: 'Giving albumin (simulated as MAP +5 mmHg, urine output +150 mL/24h)',
      zh: '俾白蛋白（模擬為平均動脈壓 +5 mmHg、尿量 +150 mL/24小時）',
    },
    caveat: {
      en: 'Albumin is not a node in the causal graph — its effect is simulated through expected haemodynamic response.',
      zh: '白蛋白並非因果圖中嘅節點 — 其效果係透過預期血流動力學反應模擬。',
    },
  },
  {
    id: 'fluids',
    match: ['fluid', 'bolus', 'crystalloid', '輸液', '補液', '俾水', '生理鹽水'],
    apply: (s) => ({ ...s, map: s.map + 6, lactate: Math.max(0.5, s.lactate - 0.4), urineOutput: s.urineOutput + 200 }),
    describe: {
      en: 'Fluid bolus (simulated as MAP +6 mmHg, lactate −0.4 mmol/L, urine output +200 mL/24h)',
      zh: '輸液（模擬為平均動脈壓 +6 mmHg、乳酸 −0.4 mmol/L、尿量 +200 mL/24小時)',
    },
  },
  {
    id: 'vasopressor',
    match: ['vasopressor', 'pressor', 'noradrenaline', 'norepinephrine', '升壓藥', '升壓', '去甲腎'],
    apply: (s) => ({ ...s, vaso: 'YES', map: s.map + 10 }),
    describe: {
      en: 'Starting/escalating vasopressors (simulated as vasopressors ON, MAP +10 mmHg)',
      zh: '開始／加大升壓藥（模擬為升壓藥開啟、平均動脈壓 +10 mmHg）',
    },
  },
  {
    id: 'ventilation',
    match: ['ventilat', 'intubat', '呼吸機', '插喉'],
    apply: (s) => ({ ...s, ventilation: 'YES', spo2: Math.min(99, s.spo2 + 5) }),
    describe: {
      en: 'Mechanical ventilation (simulated as ventilation ON, SpO₂ +5%)',
      zh: '機械通氣（模擬為呼吸機開啟、血氧 +5%）',
    },
  },
  {
    id: 'deescalate',
    match: ['de-escalate', 'deescalate', 'narrow', '降階', '收窄'],
    arm: 'deescalate',
    describe: { en: 'De-escalating to narrow-spectrum antibiotics', zh: '抗生素降階至窄譜治療' },
  },
  {
    id: 'cease',
    match: ['stop antibiotic', 'cease', 'stop abx', '停抗生素', '停藥'],
    arm: 'cease',
    describe: { en: 'Ceasing antibiotics', zh: '停用抗生素' },
  },
  {
    id: 'continue',
    match: ['continue antibiotic', 'keep antibiotic', 'broad-spectrum', '繼續抗生素', '繼續廣譜'],
    arm: 'continue',
    describe: { en: 'Continuing broad-spectrum antibiotics', zh: '繼續廣譜抗生素' },
  },
];

const MORTALITY_QUERY = ['mortality', 'risk', 'prognosis', '死亡率', '風險', '預後', '幾多'];
const SHOW_ALL = ['all patients', 'patient list', 'every patient', 'show patients', 'list patients', '所有病人', '全部病人', '病人名單'];

function includesAny(userText: string, lower: string, keys: string[]): boolean {
  return keys.some((k) => (hasCJK(k) ? userText.includes(k) : lower.includes(k)));
}

async function scoreScenario(
  patient: HKPatient,
  state: PatientState,
  arm: Arm,
  signal?: AbortSignal,
): Promise<{ value: number; live: boolean }> {
  try {
    const res = await fetchPrediction(state, arm, signal);
    return { value: Math.round(res.withTreatment), live: true };
  } catch (err) {
    if (signal?.aborted) throw err;
    // Offline fallback: heuristic perturbation of the cached estimate.
    const cached = patient.outcomes[arm];
    const mapDelta = state.map - (patient.profile.map ?? state.map);
    const vasoStarted = state.vaso === 'YES' && patient.profile.vaso !== 'YES';
    const hypotensive = (patient.profile.map ?? 99) < 65;
    let adj = 0;
    if (mapDelta > 0) adj -= hypotensive ? Math.min(3, mapDelta * 0.4) : 0.5;
    if (vasoStarted) adj += hypotensive ? -1.5 : 2;
    return { value: Math.max(1, Math.round(cached + adj)), live: false };
  }
}

export async function runAssistant(
  userText: string,
  ctx: AssistantContext,
  signal?: AbortSignal,
): Promise<AssistantReply> {
  const zh = hasCJK(userText);
  const lower = userText.toLowerCase();
  const { patient, basePredictions } = ctx;

  // Mirror the raw input on the monitor; each branch reports its intent + reply.
  monitor({ kind: 'input', source: ctx.source ?? 'chat', text: userText, lang: zh ? 'zh-HK' : 'en' });
  const finish = (intent: string, detail: string, reply: AssistantReply): AssistantReply => {
    monitor({ kind: 'intent', intent, detail });
    monitor({ kind: 'reply', text: reply.text });
    return { ...reply, intent };
  };

  /* 1 ── open a patient: just say a name or HKID */
  const found = matchPatient(userText);
  if (found && found.hkid !== patient?.hkid) {
    monitor({ kind: 'patient', name: found.nameEn, hkid: found.hkid });
    return finish('open-patient', `${found.nameEn} (${found.hkid})`, {
      text: zh
        ? `開啟病人紀錄：${found.nameZh}（${found.hkid}）`
        : `Opening patient record: ${found.nameEn} ${found.nameZh} (${found.hkid})`,
      action: { type: 'open-patient', patient: found },
    });
  }

  /* 2 ── show all patients */
  if (includesAny(userText, lower, SHOW_ALL)) {
    const list = hkPatients
      .map((p) => (zh ? `${p.nameZh} · ${p.subtitle.zh}` : `${p.nameEn} · ${p.subtitle.en}`))
      .join('\n');
    return finish('show-all', `${hkPatients.length} patients`, {
      text: zh ? `現時深切治療部病人：\n${list}` : `Current ICU patients:\n${list}`,
      action: { type: 'show-all' },
    });
  }

  if (patient) {
    /* 2.5 ── voice charting: write a dictated value into the record (DB) */
    const write = parseWrite(userText, lower);
    if (write) {
      const from = patient.profile[write.key];
      return finish('write-record', `${write.label} ${from ?? '—'} → ${write.value}`, {
        text: zh
          ? `已記錄：${write.label} = ${write.value} ${write.unit}（已寫入病歷，模型重新計算中）。`
          : `Recorded: ${write.label} = ${write.value} ${write.unit} (written to the chart; model re-running).`,
        action: { type: 'write-record', writes: [write] },
      });
    }

    /* 3 ── intervention intents (re-scored against the trained model) */
    const hit = INTERVENTIONS.find((iv) => includesAny(userText, lower, iv.match));
    if (hit) {
      const arm = hit.arm ?? (basePredictions ? bestArm(basePredictions.values) : patient.outcomes.recommendedAction);

      // Pure arm switches reuse the predictions already on screen — no extra model call.
      let result: { value: number; live: boolean };
      if (!hit.apply && basePredictions) {
        result = { value: basePredictions.values[arm], live: basePredictions.live };
      } else {
        const scenarioState = (hit.apply ?? ((s: PatientState) => s))(hkToPatientState(patient));
        result = await scoreScenario(patient, scenarioState, arm, signal);
      }

      // Compare like with like: baseline must come from the same regime
      // (live model vs cached fallback) as the scenario value.
      let baseline: number | null = null;
      if (result.live && basePredictions?.live) {
        baseline = basePredictions.values[bestArm(basePredictions.values)];
      } else if (!result.live) {
        const cached = cachedArmValues(patient);
        baseline = cached[bestArm(cached)];
      }
      const delta = baseline === null ? null : result.value - baseline;
      const deltaStr = delta === null ? '' : `${delta > 0 ? '+' : ''}${delta}`;

      const lines = zh
        ? [
            `${hit.describe.zh}。`,
            delta === null
              ? `模型預測28日死亡率：${result.value}%（基線仍在計算中）。`
              : `模型預測28日死亡率：${result.value}%（基線 ${baseline}%，變化 ${deltaStr} 個百分點）。`,
            ...(delta === null ? [] : [delta < 0 ? '✓ 呢個介入喺模型入面顯示有改善。' : delta === 0 ? '— 模型顯示無明顯變化。' : '⚠ 模型顯示風險上升，建議重新考慮。']),
            ...(hit.caveat ? [`註：${hit.caveat.zh}`] : []),
            ...(result.live ? [] : ['（API 離線 — 使用緩存估算）']),
          ]
        : [
            `${hit.describe.en}.`,
            delta === null
              ? `Model-predicted 28-day mortality: ${result.value}% (baseline still loading).`
              : `Model-predicted 28-day mortality: ${result.value}% (baseline ${baseline}%, change ${deltaStr} pp).`,
            ...(delta === null ? [] : [delta < 0 ? '✓ The model suggests this intervention improves the outlook.' : delta === 0 ? '— No meaningful change predicted.' : '⚠ The model predicts increased risk — reconsider.']),
            ...(hit.caveat ? [`Note: ${hit.caveat.en}`] : []),
            ...(result.live ? [] : ['(API offline — using cached estimates)']),
          ];
      return finish('intervention', `${hit.id} → ${result.value}%`, { text: lines.join('\n') });
    }

    /* 4 ── vital / data queries */
    const vital = VITAL_QUERIES.find((v) => includesAny(userText, lower, v.match));
    if (vital) {
      const text = vital.reply(patient, zh);
      return finish('vital-query', text, { text });
    }

    /* 5 ── mortality overview */
    if (includesAny(userText, lower, MORTALITY_QUERY)) {
      const vals = basePredictions?.values ?? cachedArmValues(patient);
      return finish('mortality', `C${vals.continue}/D${vals.deescalate}/X${vals.cease}`, {
        text: zh
          ? `${patient.nameZh} 而家嘅模型預測28日死亡率：\n• 繼續廣譜抗生素：${vals.continue}%\n• 降階治療：${vals.deescalate}%\n• 停用抗生素：${vals.cease}%\n建議方案：${patient.outcomes.recommendation.zh}`
          : `Current model-predicted 28-day mortality for ${patient.nameEn}:\n• Continue broad-spectrum: ${vals.continue}%\n• De-escalate: ${vals.deescalate}%\n• Cease antibiotics: ${vals.cease}%\nRecommendation: ${patient.outcomes.recommendation.en}`,
      });
    }
  }

  /* 6 ── help */
  const names = hkPatients.map((p) => (zh ? p.nameZh : p.nameEn.split(',')[0])).join(', ');
  return finish('help', '', {
    text: patient
      ? zh
        ? '我可以：查詢數據（「SOFA評分」）、記錄數據入病歷（「乳酸記低 3.2」）、模擬介入（「俾白蛋白」「降階」）、報告死亡率，或者講出另一位病人嘅姓名。'
        : 'I can: query vitals ("SOFA score"), chart a value into the record ("set lactate to 3.2"), simulate interventions ("give albumin", "de-escalate"), report mortality, or open another patient — just say a name.'
      : zh
        ? `講出病人姓名或者身份證號碼嚟開啟紀錄，例如：${names}。亦可以講「所有病人」。`
        : `Say a patient name or HKID to open a record, e.g. ${names}. You can also say "show all patients".`,
  });
}
