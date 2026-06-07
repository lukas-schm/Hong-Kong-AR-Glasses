/* ────────────────────────────────────────────────────────────────────────
   CDARS CDSS on Even G2 — plugin entry point.

   Wires together:
     · the Even App bridge (containers on the glasses, temple gestures, mic)
     · the CDARS bus (mirror-synced select/nav with #monitor and #cdars)
     · the CDARS REST API (worklist, live predictions, cohort, agent)

   Interaction model (temple touchpad):
     worklist page: scroll = move cursor (native) · tap = open patient
     patient page : scroll = cycle decision cards · tap = talk (toggle mic)
                    double-tap = back to worklist
   ──────────────────────────────────────────────────────────────────────── */
import { waitForEvenAppBridge, OsEventTypeList } from '@evenrealities/even_hub_sdk';
import { bus, type BusActivity, type BusEvent } from './bus';
import {
  fetchActivePatients, fetchArmPredictions, fetchCohortOutcomes, fetchPatient,
  type PatientRecord,
} from './cdars';
import { CARD_COUNT, Renderer, type RenderState } from './render';
import { G2Voice } from './voice';
import { mountPhonePanel } from './phonePanel';

const st: RenderState = {
  page: 'worklist',
  patients: [],
  worklistIndex: 0,
  current: null,
  predictions: null,
  cohort: null,
  card: 0,
  connected: false,
  listening: false,
  reply: null,
  lastUtterance: null,
};

const keyOf = (p: PatientRecord) => p.referenceKey ?? p.hkid ?? '';

async function main() {
  const panel = mountPhonePanel();
  const bridge = await waitForEvenAppBridge();
  const renderer = new Renderer(bridge, panel);
  const voice = new G2Voice(bridge);
  panel.log('bridge ready');

  /* ── self-diagnosing: render any uncaught error onto the glasses ──
     The desktop sim can't reproduce device-only crashes, so surface the
     actual message on the 576×288 screen instead of white-screening. */
  let showingError = false;
  async function showError(msg: string) {
    if (showingError) return;            // avoid error→render→error loops
    showingError = true;
    panel.log(`ERR: ${msg}`);
    const page = {
      containerTotalNum: 1,
      textObject: [{ containerID: 1, containerName: 'err', xPosition: 8, yPosition: 8, width: 560, height: 272, content: `ERR: ${msg}`.slice(0, 380) }],
    };
    panel.drawMirror(page);              // show the error on the phone preview too
    try { await bridge.rebuildPageContainer(page as never); }
    catch { try { await bridge.createStartUpPageContainer(page as never); } catch { /* ignore */ } }
    setTimeout(() => { showingError = false; }, 1500);
  }
  window.addEventListener('error', (e) => { void showError(`${e.message} @ ${(e.filename || '').split('/').pop()}:${e.lineno}`); });
  window.addEventListener('unhandledrejection', (e) => { void showError(`promise: ${String((e as PromiseRejectionEvent).reason)}`); });

  /* ── model context for the current patient ── */
  async function loadModel(p: PatientRecord) {
    st.predictions = null;
    st.cohort = null;
    const key = keyOf(p);
    const [pred, cohort] = await Promise.all([
      fetchArmPredictions(key), fetchCohortOutcomes(key),
    ]);
    if (st.current && keyOf(st.current) === key) {
      st.predictions = pred;
      st.cohort = cohort;
      void renderer.update(st);
    }
  }

  function openPatient(key: string, broadcast: boolean) {
    const p = st.patients.find((q) => keyOf(q) === key || q.hkid === key);
    if (!p) return;
    st.current = p;
    st.page = 'patient';
    st.card = 0;
    st.reply = null;
    st.lastUtterance = null;
    void renderer.render(st);
    void loadModel(p);
    if (broadcast) {
      bus.publishSelect(keyOf(p));
      bus.publishActivity({
        kind: 'tool',
        text: `Opened ${p.nameEn} on the glasses`,
        referenceKey: keyOf(p),
      });
    }
  }

  function backToWorklist(broadcast: boolean) {
    st.page = 'worklist';
    st.current = null;
    void renderer.render(st);
    if (broadcast) bus.publishNav({ menuOpen: true });
  }

  function setCard(card: number, broadcast: boolean) {
    st.reply = null;                         // scrolling dismisses any voice answer → back to cards
    st.card = ((card % CARD_COUNT) + CARD_COUNT) % CARD_COUNT;
    void renderer.update(st);
    if (broadcast) bus.publishNav({ card: st.card });
  }

  /* ── voice Q&A: tap to ask Gemini about the open patient ── */
  async function toggleTalk() {
    if (voice.listening) {
      st.listening = false;
      st.reply = '…';                       // "thinking" while Gemini answers
      void renderer.update(st);
      const answer = await voice.stopAndAsk(st.current ? keyOf(st.current) : '');
      st.reply = answer ?? 'No answer.';
      void renderer.update(st);
    } else {
      st.reply = null;                       // clear any previous answer; start listening
      st.listening = await voice.start();
      void renderer.update(st);
    }
  }

  /* ── unified input: one place for the touchpad AND the phone buttons ── */
  function moveCursor(delta: number) {
    const n = st.patients.length;
    if (!n) return;
    st.worklistIndex = Math.max(0, Math.min(n - 1, st.worklistIndex + delta));
    void renderer.update(st);
  }

  function gesture(kind: 'up' | 'down' | 'click' | 'double') {
    if (st.page === 'worklist') {
      if (kind === 'up') moveCursor(-1);
      else if (kind === 'down') moveCursor(1);
      else if (kind === 'click') { const p = st.patients[st.worklistIndex]; if (p) openPatient(keyOf(p), true); }
      // double: no-op on the worklist
    } else if (st.page === 'patient') {
      if (kind === 'up') setCard(st.card - 1, true);
      else if (kind === 'down') setCard(st.card + 1, true);
      else if (kind === 'click') void toggleTalk();
      else if (kind === 'double') backToWorklist(true);
    }
  }
  panel.bindControls({
    up: () => gesture('up'), down: () => gesture('down'),
    click: () => gesture('click'), double: () => gesture('double'),
  });

  /* ── touchpad → gestures (scroll = move · tap = click · double-tap = back) ── */
  bridge.onEvenHubEvent((event) => {
   try {
    if (event.audioEvent) { voice.onAudio(event.audioEvent.audioPcm); return; }
    // Worklist + patient are both event-capture text containers now, so the same
    // touchpad mapping works on both. Protobuf omits zero, so CLICK_EVENT (0) and
    // a missing eventType both read as 0 → coalesce.
    const tx = event.textEvent ? (event.textEvent.eventType ?? 0) : -1;
    const sy = event.sysEvent ? (event.sysEvent.eventType ?? 0) : -1;
    if (tx === OsEventTypeList.SCROLL_TOP_EVENT) gesture('up');
    else if (tx === OsEventTypeList.SCROLL_BOTTOM_EVENT) gesture('down');
    else if (sy === OsEventTypeList.DOUBLE_CLICK_EVENT) gesture('double');
    else if (sy === OsEventTypeList.CLICK_EVENT) gesture('click');
   } catch (e) { void showError('evt: ' + String(e)); }
  });

  /* ── inbound bus events (mirror-sync with monitor/cdars) ── */
  bus.subscribe((ev: BusEvent) => {
    if (ev.type === 'select') {
      openPatient((ev as { referenceKey: string }).referenceKey, false);
    } else if (ev.type === 'nav') {
      const n = ev as { card?: number; menuOpen?: boolean };
      if (n.menuOpen === true && st.page !== 'worklist') backToWorklist(false);
      else if (typeof n.card === 'number') setCard(n.card, false);
    } else if (ev.type === 'activity') {
      const a = ev as BusActivity;
      if (a.kind === 'reply' && a.source !== 'glasses') {
        st.reply = a.text;
        void renderer.update(st);
      }
    } else if (ev.type === 'data-change') {
      const rk = (ev as { referenceKey: string }).referenceKey;
      fetchPatient(rk).then((fresh) => {
        st.patients = st.patients.map((p) => (keyOf(p) === rk ? fresh : p));
        if (st.current && keyOf(st.current) === rk) {
          st.current = fresh;
          void renderer.update(st);
          void loadModel(fresh);
        }
      }).catch(() => {});
    }
  });

  bus.onStatus((connected) => {
    st.connected = connected;
    panel.setConnected(connected);
    void renderer.update(st);
  });
  bus.start();

  /* ── initial worklist ── */
  try {
    st.patients = await fetchActivePatients();
    panel.log(`worklist: ${st.patients.length} active patients`);
  } catch (e) {
    panel.log(`CDARS unreachable: ${String(e)}`);
  }
  await renderer.render(st);
  panel.log('glasses UI up');
}

main().catch((e) => {
  document.body.insertAdjacentText('beforeend', `fatal: ${String(e)}`);
});
