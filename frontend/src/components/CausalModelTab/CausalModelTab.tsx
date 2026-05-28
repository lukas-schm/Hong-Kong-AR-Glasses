import { useState, useEffect, useCallback } from 'react';
import { DAG } from './DAG';
import { VariableDrawer } from './VariableDrawer';
import { NodeEditor } from './NodeEditor';
import { OutcomesPanel } from './OutcomesPanel';
import { usePatientState, usePatientDispatch } from '../../hooks/usePatientState';
import './CausalModelTab.css';

interface EditorPosition { x: number; y: number }

export function CausalModelTab() {
  const state = usePatientState();
  const dispatch = usePatientDispatch();
  const { outcomeLoading, dagViewMode, coefficientMultipliers } = state;
  const [drawerOpen, setDrawerOpen] = useState(true);
  const [editorNodeId, setEditorNodeId] = useState<string | null>(null);
  const [editorPos, setEditorPos] = useState<EditorPosition>({ x: 0, y: 0 });

  const multipliersKey = JSON.stringify(coefficientMultipliers);
  void multipliersKey;
  const isFullView = dagViewMode === 'full';
  const hasModifiedParams = state.modifiedKeys.length > 0;

  /* ── Fetch outcomes when state changes ── */
  useEffect(() => {
    if (!outcomeLoading) return;
    const ac = new AbortController();
    const MIN_DELAY = 600;

    async function load() {
      const startedAt = Date.now();
      try {
        const { fetchOutcomesFromAPI } = await import('../../utils/outcomes');
        const outcomes = await fetchOutcomesFromAPI(
          state,
          state.activeTreatmentId,
          ac.signal,
          Object.keys(state.coefficientMultipliers).length > 0 ? state.coefficientMultipliers : undefined,
        );
        const elapsed = Date.now() - startedAt;
        const delay = Math.max(0, MIN_DELAY - elapsed);
        setTimeout(() => {
          if (!ac.signal.aborted) {
            dispatch({ type: 'SET_API_CONNECTED', connected: true });
            dispatch({ type: 'SET_API_OUTCOMES', outcomes });
          }
        }, delay);
      } catch {
        if (!ac.signal.aborted) {
          const delay = Math.max(MIN_DELAY - (Date.now() - startedAt), 0);
          setTimeout(() => {
            if (!ac.signal.aborted) {
              dispatch({ type: 'SET_API_CONNECTED', connected: false });
              dispatch({ type: 'SET_OUTCOME_READY' });
            }
          }, delay);
        }
      }
    }

    load();
    return () => ac.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    outcomeLoading, dispatch,
    state.sofa, state.sapsii, state.lactate, state.vaso, state.ventilation, state.aki,
    state.crp, state.wbc, state.temperature,
    state.cultureResult, state.sourceIdentified, state.pathogenIdentified, state.antibioticDays,
    state.age, state.female, state.comorbidity, state.immunocompromised,
    state.heartRate, state.respRate, state.spo2, state.map, state.urineOutput, state.weight,
    state.activeTreatmentId, dagViewMode,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    multipliersKey,
  ]);

  const handleNodeClick = useCallback((nodeId: string, clientX: number, clientY: number) => {
    if (editorNodeId === nodeId) {
      setEditorNodeId(null);
    } else {
      setEditorNodeId(nodeId);
      setEditorPos({ x: clientX + 12, y: clientY + 12 });
    }
  }, [editorNodeId]);

  const handleCloseEditor = useCallback(() => {
    setEditorNodeId(null);
    dispatch({ type: 'SELECT_NODE', nodeId: null });
  }, [dispatch]);

  const handleToggleView = useCallback(() => {
    dispatch({ type: 'SET_DAG_VIEW_MODE', mode: isFullView ? 'compressed' : 'full' });
  }, [dispatch, isFullView]);

  return (
    <div className="causal-tab">
      <div className="causal-tab__main">
        <div className="causal-tab__header">
          <div className="causal-tab__header-dag">
            <span className="causal-tab__title-pill">
              <span className="causal-tab__patient-dot" />
              <span className="causal-tab__patient-name">{state.currentPatientId}</span>
              <span className="causal-tab__patient-info">{state.currentPatientInfo}</span>
            </span>
            <div className="causal-tab__header-actions">
              {hasModifiedParams && (
                <button
                  className="causal-tab__reset-btn"
                  onClick={() => dispatch({ type: 'RESET_PATIENT_PARAMETERS' })}
                >
                  Reset parameters
                </button>
              )}
              <button
                className={`dag-view-toggle${isFullView ? ' dag-view-toggle--full' : ''}`}
                onClick={handleToggleView}
                title={isFullView ? 'Switch to compressed view' : 'Switch to full DAG view'}
              >
                <span className={`dag-view-toggle__option${!isFullView ? ' dag-view-toggle__option--active' : ''}`}>
                  Key Variables
                </span>
                <span className={`dag-view-toggle__option${isFullView ? ' dag-view-toggle__option--active' : ''}`}>
                  Full Model
                </span>
              </button>
            </div>
          </div>
          <div className="causal-tab__header-panel" aria-hidden="true" />
        </div>

        <div className="causal-tab__body">
          <VariableDrawer isOpen={drawerOpen} onToggle={() => setDrawerOpen(v => !v)} />
          <div className="causal-tab__dag-wrap">
            <DAG onNodeClick={handleNodeClick} />
          </div>
          <div className="causal-tab__outcomes">
            <OutcomesPanel />
          </div>
        </div>
      </div>

      {editorNodeId && (
        <NodeEditor
          nodeId={editorNodeId}
          position={editorPos}
          onClose={handleCloseEditor}
        />
      )}
    </div>
  );
}
