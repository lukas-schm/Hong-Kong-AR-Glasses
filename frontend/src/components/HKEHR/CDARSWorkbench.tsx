import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLang, LangToggle, pick } from '../../i18n';
import { bus } from '../../utils/bus';
import { selectPatient as syncSelect } from '../../utils/hudSync';
import {
  fetchCatalog, queryCohortApi, fetchAudit,
  type CDARSCatalog, type CohortResult, type CohortCriteria, type AuditEntry,
} from '../../api/cdars';
import './HKEHR.css';
import './CDARSWorkbench.css';

/* ────────────────────────────────────────────────────────────────────────
   #cdars — the CDARS cohort workbench.

   The territory-wide retrospective surface: warehouse stats, a criteria pane
   (ICD-9-CM / episode type / cluster / age / dates / Death-Registry linkage),
   a de-identified line listing keyed by Reference Key, a live Data-Sharing-
   Portal audit trail, and an "Open on glasses" hand-off for current
   admissions (publishes a select over the bus → glasses + monitor follow).
   ──────────────────────────────────────────────────────────────────────── */

const emptyCriteria: CohortCriteria = {
  dxCode: '995.92', episodeType: '', cluster: '', sex: '',
  ageMin: null, ageMax: null, admittedFrom: '', admittedTo: '', deathsOnly: false,
};

const T = {
  barSub: {
    en: 'Clinical Data Analysis & Reporting System · HA territory-wide warehouse, all public hospitals since 1995',
    zh: '臨床數據分析及報告系統 · 醫管局全港數據倉，涵蓋自1995年起所有公立醫院',
  },
  criteria: { en: 'Define criteria', zh: '設定條件' },
  dx: { en: 'Diagnosis (ICD-9-CM)', zh: '診斷（ICD-9-CM）' },
  type: { en: 'Episode type', zh: '就診類別' },
  cluster: { en: 'HA Cluster', zh: '醫管局聯網' },
  sex: { en: 'Sex', zh: '性別' },
  ageMin: { en: 'Age ≥', zh: '年齡 ≥' },
  ageMax: { en: 'Age ≤', zh: '年齡 ≤' },
  from: { en: 'Admitted from', zh: '入院由' },
  to: { en: 'Admitted to', zh: '入院至' },
  deaths: { en: 'Deaths only (Death Registry linkage)', zh: '只顯示死亡（死亡登記連結）' },
  extract: { en: 'Extract cohort', zh: '提取隊列' },
  listing: { en: 'De-identified line listing', zh: '去識別化清單' },
  runHint: { en: 'Define criteria, then run the extract.', zh: '設定條件後提取資料。' },
  keys: { en: 'distinct Reference Keys', zh: '不重複參考編號' },
  episodes: { en: 'episodes', zh: '就診次數' },
  deathsN: { en: 'deaths', zh: '死亡個案' },
  truncated: { en: 'showing first', zh: '只顯示首' },
  ofN: { en: 'of', zh: '／共' },
  openGlasses: { en: 'Open in Emily', zh: '喺 Emily 開啟' },
  audit: { en: 'Data Sharing Portal — audit trail', zh: '數據共享平台 — 審計記錄' },
  footnote: {
    en: 'Reference Key is a CDARS pseudo-identifier — never the HKID. Real CDARS extracts cannot be re-identified; the "Open in Emily" bridge exists only in this demo for current ICU admissions.',
    zh: '參考編號為 CDARS 假名識別碼，並非身份證號碼。真實 CDARS 提取數據無法重新識別；「喺 Emily 開啟」僅為本示範針對現時深切治療部住院病人而設。',
  },
};

export function CDARSWorkbench() {
  const { lang } = useLang();
  const p = pick(lang);
  const [catalog, setCatalog] = useState<CDARSCatalog | null>(null);
  const [criteria, setCriteria] = useState<CohortCriteria>(emptyCriteria);
  const [result, setResult] = useState<CohortResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [audit, setAudit] = useState<AuditEntry[]>([]);

  useEffect(() => {
    const ctrl = new AbortController();
    fetchCatalog(ctrl.signal).then(setCatalog).catch(() => {});
    return () => ctrl.abort();
  }, []);

  const refreshAudit = useCallback(() => { fetchAudit(14).then(setAudit).catch(() => {}); }, []);
  useEffect(() => {
    refreshAudit();
    bus.start('cdars');
    // Any write/data-change anywhere refreshes the audit trail.
    const off = bus.subscribe((ev) => {
      if (ev.type === 'data-change' || (ev.type === 'activity' && (ev as { kind?: string }).kind === 'db-write')) {
        refreshAudit();
      }
    });
    return off;
  }, [refreshAudit]);

  const set = <K extends keyof CohortCriteria>(k: K, v: CohortCriteria[K]) =>
    setCriteria((c) => ({ ...c, [k]: v }));

  const runExtract = async () => {
    setBusy(true);
    try {
      const r = await queryCohortApi(criteria);
      setResult(r);
      refreshAudit();
    } finally { setBusy(false); }
  };

  const openInEmily = (referenceKey: string) => {
    syncSelect(referenceKey);
    bus.publishActivity({ kind: 'tool', text: `CDARS workbench → opened ${referenceKey} in Emily`,
      textZh: `CDARS 工作台 → 喺 Emily 開啟 ${referenceKey}`, referenceKey });
    location.hash = '#monitor';
  };

  const icd9 = catalog?.icd9 ?? [];
  const clusters = catalog?.clusters ?? [];
  const episodeTypes = catalog?.episodeTypes ?? [];

  const counts = result?.counts;

  const auditRows = useMemo(() => audit.slice(0, 14), [audit]);

  return (
    <div className="cdars-workbench">
      <div className="hkehr-page cdars-page">
        <header className="cdars-bar">
          <span className="cdars-logo">CDARS</span>
          <span className="cdars-bar__sub">{p(T.barSub)}</span>
          <span className="cdars-deid-badge">{lang === 'zh-HK' ? '已去識別化 · 參考編號' : 'DE-IDENTIFIED · REFERENCE KEY'}</span>
          <a className="cdars-jump" href="#monitor">← Emily</a>
          <LangToggle />
        </header>

        <div className="cdars-grid">
          {/* ── Criteria pane ── */}
          <section className="hkehr-card cdars-criteria">
            <h2>{p(T.criteria)}</h2>

            <label className="hkehr-field">
              <span>{p(T.dx)}</span>
              <select value={criteria.dxCode} onChange={(e) => set('dxCode', e.target.value)}>
                <option value="">— any —</option>
                {icd9.map((d) => <option key={d.code} value={d.code}>{d.code} · {p(d.desc)}</option>)}
              </select>
            </label>

            <label className="hkehr-field">
              <span>{p(T.type)}</span>
              <select value={criteria.episodeType} onChange={(e) => set('episodeType', e.target.value)}>
                <option value="">— all —</option>
                {episodeTypes.map((et) => <option key={et.code} value={et.code}>{et.code} · {p(et.name)}</option>)}
              </select>
            </label>

            <label className="hkehr-field">
              <span>{p(T.cluster)}</span>
              <select value={criteria.cluster} onChange={(e) => set('cluster', e.target.value)}>
                <option value="">— all clusters —</option>
                {clusters.map((c) => <option key={c.code} value={c.code}>{c.code} · {p(c.name)}</option>)}
              </select>
            </label>

            <div className="cdars-field-row">
              <label className="hkehr-field">
                <span>{p(T.sex)}</span>
                <select value={criteria.sex} onChange={(e) => set('sex', e.target.value)}>
                  <option value="">—</option><option value="M">M</option><option value="F">F</option>
                </select>
              </label>
              <label className="hkehr-field">
                <span>{p(T.ageMin)}</span>
                <input type="number" value={criteria.ageMin ?? ''} onChange={(e) => set('ageMin', e.target.value === '' ? null : Number(e.target.value))} />
              </label>
              <label className="hkehr-field">
                <span>{p(T.ageMax)}</span>
                <input type="number" value={criteria.ageMax ?? ''} onChange={(e) => set('ageMax', e.target.value === '' ? null : Number(e.target.value))} />
              </label>
            </div>

            <div className="cdars-field-row">
              <label className="hkehr-field">
                <span>{p(T.from)}</span>
                <input type="date" value={criteria.admittedFrom} onChange={(e) => set('admittedFrom', e.target.value)} />
              </label>
              <label className="hkehr-field">
                <span>{p(T.to)}</span>
                <input type="date" value={criteria.admittedTo} onChange={(e) => set('admittedTo', e.target.value)} />
              </label>
            </div>

            <label className="cdars-check">
              <input type="checkbox" checked={criteria.deathsOnly} onChange={(e) => set('deathsOnly', e.target.checked)} />
              <span>{p(T.deaths)}</span>
            </label>

            <button className="hkehr-btn hkehr-btn--primary cdars-extract" onClick={runExtract} disabled={busy}>
              {busy ? '…' : p(T.extract)}
            </button>

            {/* ── Audit trail ── */}
            <div className="cdars-audit">
              <h3>{p(T.audit)}</h3>
              <div className="cdars-audit__list">
                {auditRows.length === 0 && <div className="hkehr-empty">—</div>}
                {auditRows.map((a, i) => (
                  <div key={i} className={`cdars-audit__row cdars-audit__row--${a.action}`}>
                    <span className="cdars-audit__time">{a.ts.slice(11, 19)}</span>
                    <span className="cdars-audit__act">{a.action}</span>
                    <span className="cdars-audit__chan">{a.channel}</span>
                    <span className="cdars-audit__detail">{a.detail}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* ── Results ── */}
          <section className="hkehr-card cdars-results">
            <h2>{p(T.listing)}</h2>
            {!result ? (
              <p className="hkehr-empty">{p(T.runHint)}</p>
            ) : (
              <>
                <div className="cdars-counts">
                  <div><strong>{counts!.patients.toLocaleString()}</strong><span>{p(T.keys)}</span></div>
                  <div><strong>{counts!.episodes.toLocaleString()}</strong><span>{p(T.episodes)}</span></div>
                  <div><strong>{counts!.deaths.toLocaleString()}</strong><span>{p(T.deathsN)}</span></div>
                </div>
                {result.truncated && (
                  <p className="cdars-trunc">{p(T.truncated)} {result.cap} {p(T.ofN)} {counts!.episodes.toLocaleString()} {p(T.episodes)}.</p>
                )}
                <div className="cdars-table-wrap">
                  <table className="cdars-table">
                    <thead>
                      <tr>
                        <th>Ref. Key</th><th>Sex</th><th>Age</th><th>Type</th><th>Adm. Date</th>
                        <th>Cluster/Hosp</th><th>Spec</th><th>ICD-9-CM</th><th>Drug (BNF)</th><th>Lab</th><th>Death</th><th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.listing.map((e, i) => (
                        <tr key={e.referenceKey + e.admissionDate + i} className={e.death ? 'cdars-row--death' : (e.active ? 'cdars-row--active' : '')}>
                          <td className="hkehr-mono">{e.referenceKey}</td>
                          <td>{e.sex}</td><td>{e.age}</td><td>{e.episodeType}</td>
                          <td className="hkehr-mono">{e.admissionDate.slice(0, 10)}</td>
                          <td>{e.cluster}/{e.hospital}</td><td>{e.specialty}</td>
                          <td className="hkehr-mono" title={p(e.dxDesc)}>{e.dxCode}</td>
                          <td title={`BNF ${e.bnf}`}>{p(e.drug)}</td>
                          <td className="hkehr-mono">{e.labTest} {e.labValue}</td>
                          <td>{e.death ? `✝ ${e.deathDate?.slice(0, 10) ?? ''}` : '—'}</td>
                          <td>{e.linkedHkid && (
                            <button className="cdars-link" onClick={() => openInEmily(e.referenceKey)} title={p(T.footnote)}>
                              {p(T.openGlasses)}
                            </button>
                          )}</td>
                        </tr>
                      ))}
                      {result.listing.length === 0 && <tr><td colSpan={12} className="hkehr-empty">0 episodes</td></tr>}
                    </tbody>
                  </table>
                </div>
                <p className="cdars-footnote">{p(T.footnote)}</p>
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
