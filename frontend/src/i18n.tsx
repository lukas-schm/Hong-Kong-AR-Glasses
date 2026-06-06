import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';

/* ────────────────────────────────────────────────────────────────────────
   Lightweight bilingual i18n for the Hong Kong showcase.
   'en'    — English
   'zh-HK' — Traditional Chinese, Hong Kong variant (zh-Hant-HK).
             Written Cantonese conventions where natural for chat.
   ──────────────────────────────────────────────────────────────────────── */

export type Lang = 'en' | 'zh-HK';

const dict = {
  /* ── App / navigation ── */
  appTitle: { en: 'Antibiotic CDSS · HK Clinical Data Gateway', 'zh-HK': '抗生素臨床決策支援 · 香港臨床數據閘道' },
  back: { en: '← Back to record selection', 'zh-HK': '← 返回病歷選擇' },
  glassesHud: { en: 'GLASSES HUD', 'zh-HK': '智能眼鏡顯示' },

  /* ── EHR select page ── */
  ehrssTitle: { en: 'eHRSS · Electronic Health Record Sharing System', 'zh-HK': '醫健通 · 電子健康紀錄互通系統' },
  ehrssSubtitle: {
    en: 'Retrieve patient records from Hospital Authority CMS via the HL7-based eHRSS interface (HKCTT terminology)',
    'zh-HK': '透過 HL7 醫健通介面（HKCTT 術語表）從醫院管理局臨床醫療管理系統擷取病人紀錄',
  },
  mockBadge: { en: 'DEMO · MOCKED INTEGRATION', 'zh-HK': '示範 · 模擬整合' },
  step1: { en: '1 · Select source facility', 'zh-HK': '1 · 選擇來源機構' },
  step2: { en: '2 · Patient lookup', 'zh-HK': '2 · 病人查詢' },
  step3: { en: '3 · Sharing consent', 'zh-HK': '3 · 互通同意' },
  cluster: { en: 'HA Cluster', 'zh-HK': '醫管局聯網' },
  hospital: { en: 'Hospital', 'zh-HK': '醫院' },
  sourceSystem: { en: 'Source system', 'zh-HK': '來源系統' },
  hkidLabel: { en: 'Search by HKID', 'zh-HK': '以香港身份證號碼搜尋' },
  hkidPlaceholder: { en: 'e.g. K523678(A)', 'zh-HK': '例如 K523678(A)' },
  searchBtn: { en: 'Query eHRSS', 'zh-HK': '查詢醫健通' },
  noMatch: { en: 'No enrolled patient found for this HKID at the selected facility.', 'zh-HK': '在所選機構找不到此身份證號碼的登記病人。' },
  inpatients: { en: 'Current ICU admissions at', 'zh-HK': '現時深切治療部住院病人 —' },
  consentTitle: { en: 'Sharing Consent verified', 'zh-HK': '互通同意已核實' },
  consentBody: {
    en: 'Patient has given Sharing Consent under eHRSS. Access is logged and the patient will be notified (need-to-know basis).',
    'zh-HK': '病人已根據醫健通給予互通同意。存取將被記錄，病人會收到通知（按需要知道原則）。',
  },
  retrieveBtn: { en: 'Retrieve record', 'zh-HK': '擷取紀錄' },
  retrieving: { en: 'Retrieving via HL7 interface…', 'zh-HK': '正在透過 HL7 介面擷取…' },
  domainPmi: { en: 'PMI · Demographics', 'zh-HK': '病人總索引 · 個人資料' },
  domainDiagnoses: { en: 'Diagnoses (ICD-10 / HKCTT)', 'zh-HK': '診斷（ICD-10 / HKCTT）' },
  domainMeds: { en: 'Medications', 'zh-HK': '藥物' },
  domainLabs: { en: 'Laboratory results (LOINC)', 'zh-HK': '化驗結果（LOINC）' },
  domainAllergies: { en: 'Allergies & ADR', 'zh-HK': '過敏及藥物不良反應' },
  domainEncounters: { en: 'Encounters', 'zh-HK': '就診紀錄' },

  openMonitor: { en: 'MODEL MONITOR', 'zh-HK': '模型監察' },
  listening: { en: 'Listening…', 'zh-HK': '聆聽中…' },
  voiceHint: {
    en: 'Tap the glasses, then say a name, a vital, a value to chart, or an intervention.',
    'zh-HK': '撳一撳眼鏡，講出姓名、查詢數據、記錄數值或介入治療。',
  },

  /* ── Monitor (clinician view) ── */
  monRecommends: { en: 'Model recommendation', 'zh-HK': '模型建議' },
  monRiskOfDeath: { en: 'predicted 28-day risk of death', 'zh-HK': '預測28日死亡風險' },
  monLowest: { en: 'lowest risk', 'zh-HK': '風險最低' },
  monExplain: { en: 'Of the three options, the model predicts the lowest 28-day risk of death for:', 'zh-HK': '三個方案之中，模型預測28日死亡風險最低嘅係：' },
  monChanged: { en: 'Risk for the recommended option just changed', 'zh-HK': '建議方案嘅風險啱啱改變咗' },
  monAfterUpdate: { en: 'after your last update', 'zh-HK': '（因應你嘅最新更新）' },
  monActivity: { en: 'What just happened', 'zh-HK': '剛才發生咗咩' },
  monYou: { en: 'You', 'zh-HK': '你' },
  monAssistant: { en: 'Model', 'zh-HK': '模型' },
  monCharted: { en: 'Charted to record', 'zh-HK': '已寫入病歷' },
  monStart: { en: 'Tap the glasses and say a patient name to begin — e.g. “Chan Tai Man”.', 'zh-HK': '撳一撳眼鏡，講出病人姓名開始，例如「陳大文」。' },
  monWaiting: { en: 'Waiting for the model…', 'zh-HK': '等待模型…' },
  monTechLog: { en: 'Technical model log', 'zh-HK': '技術記錄' },

  /* ── CDARS ── */
  cdarsOpen: { en: 'CDARS COHORT QUERY', 'zh-HK': 'CDARS 隊列查詢' },
  cdarsBackToEhrss: { en: '← eHRSS patient retrieval', 'zh-HK': '← 醫健通病人查詢' },
  cdarsTitle: { en: 'CDARS · Clinical Data Analysis and Reporting System', 'zh-HK': 'CDARS · 臨床數據分析及報告系統' },
  cdarsSubtitle: {
    en: 'De-identified retrospective extract across all HA hospitals (CMS/ePR upstream) for research & audit — ICD-9-CM diagnoses, BNF drug sections, local lab test names, HK Death Registry linkage',
    'zh-HK': '覆蓋全部醫管局醫院嘅去識別化回顧性數據提取（上游為 CMS/ePR），供研究及審計使用 — ICD-9-CM 診斷、BNF 藥物分類、本地化驗名稱、香港死亡登記連結',
  },
  cdarsDeidBadge: { en: 'DE-IDENTIFIED · REFERENCE KEY', 'zh-HK': '已去識別化 · 參考編號' },
  cdarsCriteria: { en: 'Define criteria', 'zh-HK': '設定條件' },
  cdarsDx: { en: 'Diagnosis', 'zh-HK': '診斷' },
  cdarsEpisodeType: { en: 'Episode type', 'zh-HK': '就診類別' },
  cdarsAgeMin: { en: 'Age ≥', 'zh-HK': '年齡 ≥' },
  cdarsAgeMax: { en: 'Age ≤', 'zh-HK': '年齡 ≤' },
  cdarsAdmittedFrom: { en: 'Admitted from', 'zh-HK': '入院日期由' },
  cdarsAdmittedTo: { en: 'Admitted to', 'zh-HK': '入院日期至' },
  cdarsDeathsOnly: { en: 'Deaths only (Death Registry linkage)', 'zh-HK': '只顯示死亡個案（死亡登記連結）' },
  cdarsExtract: { en: 'Extract cohort', 'zh-HK': '提取隊列' },
  cdarsLineListing: { en: 'De-identified line-listing', 'zh-HK': '去識別化清單' },
  cdarsRunHint: { en: 'Define criteria, then run the extract.', 'zh-HK': '設定條件後提取資料。' },
  cdarsDistinctKeys: { en: 'distinct Reference Keys', 'zh-HK': '不重複參考編號' },
  cdarsEpisodes: { en: 'episodes', 'zh-HK': '就診次數' },
  cdarsDeaths: { en: 'deaths', 'zh-HK': '死亡個案' },
  cdarsReidentify: { en: 'Open in eHRSS', 'zh-HK': '在醫健通開啟' },
  cdarsReidentifyNote: {
    en: 'DEMO ONLY — real CDARS data can never be re-identified.',
    'zh-HK': '僅供示範 — 真實 CDARS 數據無法重新識別。',
  },
  cdarsFootnote: {
    en: 'Reference Key is a CDARS pseudo-identifier — never the HKID. Real CDARS extracts cannot be re-identified; the "Open in eHRSS" bridge exists only in this demo for current ICU admissions.',
    'zh-HK': '參考編號為 CDARS 假名識別碼，並非身份證號碼。真實 CDARS 提取數據無法重新識別；「在醫健通開啟」僅為本示範針對現時深切治療部住院病人而設。',
  },

  /* ── Patient dashboard ── */
  retrievedRecord: { en: 'Retrieved eHRSS record', 'zh-HK': '已擷取醫健通紀錄' },
  hkid: { en: 'HKID', 'zh-HK': '身份證號碼' },
  nameEn: { en: 'Name (EN)', 'zh-HK': '英文姓名' },
  nameZh: { en: 'Name (中文)', 'zh-HK': '中文姓名' },
  ccc: { en: 'Chinese Commercial Code', 'zh-HK': '中文電碼' },
  dob: { en: 'Date of birth', 'zh-HK': '出生日期' },
  sex: { en: 'Sex', 'zh-HK': '性別' },
  male: { en: 'Male', 'zh-HK': '男' },
  female: { en: 'Female', 'zh-HK': '女' },
  ward: { en: 'Ward / Bed', 'zh-HK': '病房／病床' },
  predictionTitle: { en: '28-day mortality prediction', 'zh-HK': '28日死亡率預測' },
  predictionSub: {
    en: 'Causal model trained on historic ICU cohorts (MIMIC-IV), applied to the retrieved HK record',
    'zh-HK': '以歷史深切治療部數據（MIMIC-IV）訓練的因果模型，應用於已擷取的香港病歷',
  },
  armContinue: { en: 'Continue broad-spectrum', 'zh-HK': '繼續廣譜抗生素' },
  armDeescalate: { en: 'De-escalate', 'zh-HK': '降階治療' },
  armCease: { en: 'Cease antibiotics', 'zh-HK': '停用抗生素' },
  recommended: { en: 'RECOMMENDED', 'zh-HK': '建議' },
  mortality: { en: 'mortality', 'zh-HK': '死亡率' },
  liveModel: { en: 'LIVE MODEL', 'zh-HK': '實時模型' },
  fallbackModel: { en: 'CACHED ESTIMATES (API offline)', 'zh-HK': '緩存估算（API 離線）' },
  vitals: { en: 'Vitals & severity', 'zh-HK': '生命表徵及嚴重程度' },

  /* ── Chatbot ── */
  chatTitle: { en: 'Intervention Assistant', 'zh-HK': '介入治療助理' },
  chatPlaceholder: { en: 'e.g. "What if we give albumin?"', 'zh-HK': '例如「俾白蛋白會點？」' },
  chatGreeting: {
    en: 'Hi, I can simulate interventions for this patient — e.g. "give albumin", "fluid bolus", "start vasopressors", "de-escalate antibiotics", or ask "current mortality?". I answer in English or 廣東話.',
    'zh-HK': '你好，我可以為呢位病人模擬介入治療 — 例如「俾白蛋白」、「輸液」、「開始升壓藥」、「抗生素降階」，或者問「而家死亡率係幾多？」。我識講英文同廣東話。',
  },
  chatThinking: { en: 'Running causal model…', 'zh-HK': '正在運行因果模型…' },
  send: { en: 'Send', 'zh-HK': '傳送' },
} as const;

export type TKey = keyof typeof dict;

export function translate(lang: Lang, key: TKey): string {
  return dict[key][lang];
}

/**
 * Curried picker for bilingual data fields ({ en, zh } shape used by the
 * mocked eHRSS records). One shared implementation so components don't
 * re-declare `zh ? x.zh : x.en` ternaries.
 */
export function pick(lang: Lang) {
  return <T extends { en: string; zh: string }>(b: T): string => (lang === 'zh-HK' ? b.zh : b.en);
}

interface LangContextValue {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: TKey) => string;
}

const LangContext = createContext<LangContextValue>({
  lang: 'en',
  setLang: () => {},
  t: (key) => dict[key].en,
});

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>('en');
  // Stable context value: consumers only re-render when the language changes.
  const value = useMemo<LangContextValue>(
    () => ({ lang, setLang, t: (key: TKey) => translate(lang, key) }),
    [lang],
  );
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useLang() {
  return useContext(LangContext);
}

export function LangToggle() {
  const { lang, setLang } = useLang();
  return (
    <div className="lang-toggle" role="group" aria-label="Language">
      <button className={lang === 'en' ? 'active' : ''} onClick={() => setLang('en')}>EN</button>
      <button className={lang === 'zh-HK' ? 'active' : ''} onClick={() => setLang('zh-HK')}>繁</button>
    </div>
  );
}
