import { useEffect, useRef } from 'react';
import { usePatientState, usePatientDispatch } from '../../hooks/usePatientState';
import { dagNodes, extraConfounderPool } from '../../data/dag';
import type { DagNode } from '../../types';
import './NodeEditor.css';

interface NodeEditorProps {
  nodeId: string;
  position: { x: number; y: number };
  onClose: () => void;
}

const allNodes: DagNode[] = [...dagNodes, ...extraConfounderPool];

export function NodeEditor({ nodeId, position, onClose }: NodeEditorProps) {
  const state = usePatientState();
  const dispatch = usePatientDispatch();
  const ref = useRef<HTMLDivElement>(null);

  const node = allNodes.find(n => n.id === nodeId);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    function onOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    window.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onOutside);
    return () => {
      window.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onOutside);
    };
  }, [onClose]);

  if (!node || !node.stateKey) return null;

  const val = (state as unknown as Record<string, unknown>)[node.stateKey];

  const handleChange = (value: string | number) => {
    dispatch({ type: 'SET_VARIABLE', key: node.stateKey!, value });
  };

  const left = Math.min(position.x, window.innerWidth - 220);
  const top = Math.min(position.y, window.innerHeight - 180);

  return (
    <div
      ref={ref}
      className="node-editor"
      style={{ left, top }}
    >
      <div className="node-editor__header">
        <span className="node-editor__label">{node.label.replace(/\n/g, ' ')}</span>
        <button className="node-editor__close" onClick={onClose}>✕</button>
      </div>

      <div className="node-editor__body">
        {node.varType === 'binary' && (
          <div className="node-editor__toggle-row">
            <button
              className={`node-editor__toggle-btn ${val === 'YES' ? 'node-editor__toggle-btn--active' : ''}`}
              onClick={() => handleChange('YES')}
            >
              {node.toggleLabels?.yes ?? 'Yes'}
            </button>
            <button
              className={`node-editor__toggle-btn ${val === 'NO' ? 'node-editor__toggle-btn--active' : ''}`}
              onClick={() => handleChange('NO')}
            >
              {node.toggleLabels?.no ?? 'No'}
            </button>
          </div>
        )}

        {node.varType === 'continuous' && (
          <>
            <div className="node-editor__value-display">
              <span className="node-editor__num">{typeof val === 'number' && node.step && node.step < 1 ? (val as number).toFixed(1) : String(val)}</span>
              {node.unit && <span className="node-editor__unit">{node.unit}</span>}
            </div>
            <input
              type="range"
              className="node-editor__slider"
              min={node.min}
              max={node.max}
              step={node.step}
              value={val as number}
              onChange={e => handleChange(parseFloat(e.target.value))}
            />
            <div className="node-editor__range-labels">
              <span>{node.min}</span>
              <span>{node.max}</span>
            </div>
          </>
        )}

        {node.varType === 'categorical' && node.categoricalOptions && (
          <div className="node-editor__cat-options">
            {node.categoricalOptions.map(opt => (
              <button
                key={opt}
                className={`node-editor__cat-btn node-editor__cat-btn--${opt} ${val === opt ? 'node-editor__cat-btn--active' : ''}`}
                onClick={() => handleChange(opt)}
              >
                {opt}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
