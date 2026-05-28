import { useRef, useEffect, useCallback } from 'react';
import * as d3Force from 'd3-force';
import * as d3Selection from 'd3-selection';
import 'd3-transition';
import { getActiveNodes, getActiveEdges } from '../../data/dag';
import { usePatientState, usePatientDispatch } from '../../hooks/usePatientState';
import type { DagNode, DagEdge, PatientState } from '../../types';
import './DAG.css';

/* ── Constants ─────────────────────────────────────── */

const NODE_RADIUS: Record<DagNode['type'], number> = {
  confounder: 36,
  treatment: 44,
  outcome: 48,
};

const NODE_RADIUS_FULL: Record<DagNode['type'], number> = {
  confounder: 24,
  treatment: 38,
  outcome: 46,
};

const NODE_FILL: Record<DagNode['type'], string> = {
  confounder: '#1e3e64',
  treatment: '#ffffff',
  outcome: '#16563f',
};

const NODE_STROKE: Record<DagNode['type'], string> = {
  confounder: '#4f90cf',
  treatment: '#ffffff',
  outcome: '#23d18b',
};

const EXTRA_NODE_FILL = '#1a3352';
const EXTRA_NODE_STROKE = '#6f9dc9';

const BINARY_YES = '#2f89ff';
const BINARY_NO = '#22486f';
const BINARY_YES_EXTRA = '#5aa3f2';
const BINARY_NO_EXTRA = '#1a3352';

const ARROW_MARGIN = 6;
const CURVE_OFFSET = 20;

/* ── Sim types ─────────────────────────────────────── */

interface SimNode extends d3Force.SimulationNodeDatum {
  id: string;
  label: string;
  stateKey?: DagNode['stateKey'];
  type: DagNode['type'];
  xPct: number;
  yPct: number;
  unit?: string;
  varType?: DagNode['varType'];
  min?: number;
  max?: number;
  step?: number;
  toggleLabels?: { yes: string; no: string };
  __isExtra?: boolean;
  __isUnobserved?: boolean;
}

interface SimLink extends d3Force.SimulationLinkDatum<SimNode> {
  style: DagEdge['style'];
  color: string;
  __markerId?: string;
  __isTreatmentEdge?: boolean;
  __sourceId?: string;
  __targetId?: string;
}

/* ── Helpers ───────────────────────────────────────── */

function nodeRadius(type: DagNode['type'], viewMode: 'compressed' | 'full' = 'compressed'): number {
  return viewMode === 'full' ? NODE_RADIUS_FULL[type] : NODE_RADIUS[type];
}

function lerpColor(hex1: string, hex2: string, t: number): string {
  const c = Math.max(0, Math.min(1, t));
  const r1 = parseInt(hex1.slice(1, 3), 16);
  const g1 = parseInt(hex1.slice(3, 5), 16);
  const b1 = parseInt(hex1.slice(5, 7), 16);
  const r2 = parseInt(hex2.slice(1, 3), 16);
  const g2 = parseInt(hex2.slice(3, 5), 16);
  const b2 = parseInt(hex2.slice(5, 7), 16);
  return `rgb(${Math.round(r1 + (r2 - r1) * c)},${Math.round(g1 + (g2 - g1) * c)},${Math.round(b1 + (b2 - b1) * c)})`;
}

function getNodeFillByValue(node: SimNode, ps: PatientState): string {
  const isExtra = !!node.__isExtra;

  if (node.type === 'treatment') return NODE_FILL.treatment;

  if (node.type === 'outcome') {
    if (ps.outcomeLoading || !ps.apiOutcomes) return NODE_FILL.outcome;
    const t = Math.max(0, Math.min(1, ps.apiOutcomes.withTreatment / 60));
    return lerpColor('#17533d', '#23d18b', t);
  }

  if (node.varType === 'binary' && node.stateKey) {
    const val = ps[node.stateKey];
    if (val === 'YES') return isExtra ? BINARY_YES_EXTRA : BINARY_YES;
    return isExtra ? BINARY_NO_EXTRA : BINARY_NO;
  }

  if (node.varType === 'continuous' && node.stateKey && node.min != null && node.max != null) {
    const t = (Number(ps[node.stateKey]) - node.min) / (node.max - node.min);
    return lerpColor(
      isExtra ? '#1a3352' : '#1f3a5a',
      isExtra ? '#5aa3f2' : '#2f89ff',
      t,
    );
  }

  return isExtra ? EXTRA_NODE_FILL : NODE_FILL[node.type];
}

function getNodeValue(node: SimNode, state: PatientState): string {
  if (node.type === 'treatment') return '';
  if (node.type === 'outcome') {
    if (state.outcomeLoading) return '...';
    if (!state.apiOutcomes) return '';
    return `${state.apiOutcomes.withTreatment.toFixed(1)}%`;
  }
  if (node.stateKey) {
    const val = state[node.stateKey];
    if (typeof val === 'number') return node.step != null && node.step < 1 ? val.toFixed(1) : String(val);
    if (node.toggleLabels) return val === 'YES' ? node.toggleLabels.yes : node.toggleLabels.no;
    return String(val ?? '');
  }
  return '';
}

function wrapLabelLines(label: string, maxChars: number): string[] {
  return label
    .split('\n')
    .flatMap(segment => {
      const words = segment.split(' ');
      const wrapped: string[] = [];
      let current = '';
      for (const word of words) {
        const next = current ? `${current} ${word}` : word;
        if (next.length <= maxChars) { current = next; continue; }
        if (current) wrapped.push(current);
        current = word;
      }
      if (current) wrapped.push(current);
      return wrapped.length > 0 ? wrapped : [''];
    })
    .slice(0, 4);
}

function setNodeValueText(
  sel: d3Selection.Selection<SVGTextElement, SimNode, any, any>,
  value: string,
) {
  sel.selectAll('tspan').remove();
  if (!value) return;
  sel.append('tspan').attr('x', 0).attr('dy', 0).text(value);
}

function computeEdgePath(sx: number, sy: number, tx: number, ty: number, sr: number, tr: number): string {
  const dx = tx - sx, dy = ty - sy;
  const dist = Math.sqrt(dx * dx + dy * dy) || 1;
  const ux = dx / dist, uy = dy / dist;
  const x1 = sx + ux * (sr + ARROW_MARGIN), y1 = sy + uy * (sr + ARROW_MARGIN);
  const x2 = tx - ux * (tr + ARROW_MARGIN), y2 = ty - uy * (tr + ARROW_MARGIN);
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
  return `M${x1},${y1} Q${mx - uy * CURVE_OFFSET},${my + ux * CURVE_OFFSET} ${x2},${y2}`;
}

/* ── Component ─────────────────────────────────────── */

interface DAGProps {
  onNodeClick?: (nodeId: string, clientX: number, clientY: number) => void;
}

export function DAG({ onNodeClick }: DAGProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const simRef = useRef<d3Force.Simulation<SimNode, SimLink> | null>(null);
  const sizeRef = useRef<{ w: number; h: number }>({ w: 600, h: 400 });
  const state = usePatientState();
  const dispatch = usePatientDispatch();
  const { extraConfounders, activeTreatmentId, dagViewMode } = state;
  const extraKey = extraConfounders.join(',');

  const initSimulation = useCallback(
    (extras: string[], treatmentId: string, vMode: 'compressed' | 'full') => {
      const svg = svgRef.current;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      const w = rect.width || 600;
      const h = rect.height || 400;
      sizeRef.current = { w, h };

      // Treatment is always in the graph
      const activeNodes = getActiveNodes(true, extras, treatmentId, vMode);
      const activeEdges = getActiveEdges(true, extras, vMode);
      const extraSet = new Set(extras);
      const isFull = vMode === 'full';

      const nodes: SimNode[] = activeNodes.map(n => ({
        id: n.id,
        label: n.label,
        stateKey: n.stateKey,
        type: n.type,
        xPct: n.x,
        yPct: n.y,
        unit: n.unit,
        varType: n.varType,
        min: n.min,
        max: n.max,
        step: n.step,
        toggleLabels: n.toggleLabels,
        x: (n.x / 100) * w,
        y: (n.y / 100) * h,
        __isExtra: !isFull && extraSet.has(n.id),
        __isUnobserved: n.observed === false,
      }));

      const links: SimLink[] = activeEdges.map(e => ({
        source: e.source,
        target: e.target,
        style: e.style,
        color: e.color,
        __isTreatmentEdge: e.source === 'treatment' || e.target === 'treatment',
        __sourceId: e.source,
        __targetId: e.target,
      }));

      const sim = d3Force
        .forceSimulation<SimNode>(nodes)
        .force('x', d3Force.forceX<SimNode>(d => (d.xPct / 100) * w).strength(isFull ? 1.0 : 0.8))
        .force('y', d3Force.forceY<SimNode>(d => (d.yPct / 100) * h).strength(isFull ? 1.0 : 0.8))
        .force('link', d3Force.forceLink<SimNode, SimLink>(links).id(d => d.id).strength(isFull ? 0.05 : 0.1))
        .force('charge', d3Force.forceManyBody().strength(isFull ? -40 : -80))
        .force('collide', d3Force.forceCollide<SimNode>(d => nodeRadius(d.type, vMode) + (isFull ? 4 : 8)))
        .alphaDecay(isFull ? 0.08 : 0.05);

      simRef.current = sim;
      return { sim, nodes, links };
    },
    [],
  );

  /* ── Main render effect ─────────────────────────── */
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    const sel = d3Selection.select(svg);
    sel.selectAll('*').remove();

    const result = initSimulation(extraConfounders, activeTreatmentId, dagViewMode);
    if (!result) return;
    const { sim, nodes, links } = result;
    const isFull = dagViewMode === 'full';

    /* ── Per-edge arrowhead markers ── */
    const defs = sel.append('defs');
    links.forEach((link, i) => {
      const sId = typeof link.source === 'string' ? link.source : (link.source as SimNode).id;
      const tId = typeof link.target === 'string' ? link.target : (link.target as SimNode).id;
      const markerId = `arrow-${sId}-${tId}-${i}`;
      link.__markerId = markerId;
      defs.append('marker')
        .attr('id', markerId)
        .attr('viewBox', '0 0 10 6')
        .attr('refX', 9).attr('refY', 3)
        .attr('markerWidth', 8).attr('markerHeight', 6)
        .attr('markerUnits', 'userSpaceOnUse')
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,0 L10,3 L0,6 Z')
        .attr('fill', link.color);
    });

    /* ── Edge paths ── */
    const edgeGroup = sel.append('g').attr('class', 'dag-edges').attr('pointer-events', 'none');
    const edgePaths = edgeGroup.selectAll<SVGPathElement, SimLink>('path')
      .data(links).enter().append('path')
      .attr('class', 'dag-edge')
      .attr('stroke', d => d.color)
      .attr('stroke-width', 1.5)
      .attr('stroke-dasharray', d => d.style === 'dashed' ? '4,3' : '')
      .attr('marker-end', d => `url(#${d.__markerId})`)
      .attr('opacity', d => (isFull ? 0.7 : (d.__isTreatmentEdge ? 0 : 1)));

    // Fade in treatment edges
    edgePaths.filter(d => !!d.__isTreatmentEdge)
      .transition('fade-in').duration(600).attr('opacity', 1);

    /* ── Node groups ── */
    const nodeGroups = sel.selectAll<SVGGElement, SimNode>('g.dag-node')
      .data(nodes, d => d.id).enter().append('g')
      .attr('class', 'dag-node')
      .style('cursor', d => {
        if (d.type === 'treatment') return 'default';
        if (isFull) return d.stateKey ? 'pointer' : 'default';
        return 'pointer';
      });

    const innerGroups = nodeGroups.append('g')
      .attr('class', 'dag-node__inner')
      .style('transition', 'transform 0.15s ease');

    // Selection ring
    innerGroups.append('circle')
      .attr('class', 'dag-node__selection-ring')
      .attr('r', d => nodeRadius(d.type, dagViewMode) + 4)
      .attr('fill', 'none')
      .attr('stroke', 'var(--sienna)')
      .attr('stroke-width', 3)
      .attr('opacity', 0);

    // Main circle
    innerGroups.append('circle')
      .attr('class', 'dag-node__circle')
      .attr('r', d => nodeRadius(d.type, dagViewMode))
      .attr('fill', d => d.__isUnobserved ? '#2b3443' : getNodeFillByValue(d, state))
      .attr('stroke', d => {
        if (d.__isUnobserved) return '#5c6f88';
        return d.__isExtra ? EXTRA_NODE_STROKE : NODE_STROKE[d.type];
      })
      .attr('stroke-width', d => d.__isUnobserved ? 1 : 1.5)
      .attr('stroke-dasharray', d => d.__isUnobserved ? '3,2' : '');

    // Node label
    innerGroups.each(function(d) {
      const group = d3Selection.select(this);
      const compact = sizeRef.current.w < 820;
      const lines = wrapLabelLines(d.label, compact ? (isFull ? 8 : 10) : (isFull ? 10 : 12));
      const lh = compact ? (isFull ? 8 : 10) : (isFull ? 9 : 12);
      const hasValue = d.type === 'outcome' || (!!d.stateKey && d.type !== 'treatment');
      const labelOffsetY = hasValue
        ? -(lines.length * lh) / 2 - (compact ? 0 : isFull ? 1 : 2)
        : -((lines.length - 1) * lh) / 2;

      const text = group.append('text')
        .attr('class', 'dag-node__label')
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'central')
        .style('font-family', 'var(--font-mono)')
        .style('font-size', compact ? (isFull ? '7.5px' : '8.5px') : (isFull ? '9px' : '10px'))
        .style('fill', d.__isUnobserved ? '#d4e1f4' : (d.type === 'treatment' ? '#000000' : '#ffffff'))
        .style('font-style', d.__isUnobserved ? 'italic' : 'normal')
        .style('pointer-events', 'none')
        .style('user-select', 'none');

      lines.forEach((line, i) => {
        text.append('tspan').attr('x', 0).attr('dy', i === 0 ? labelOffsetY : lh).text(line);
      });
    });

    // Value text
    innerGroups.append('text')
      .attr('class', 'dag-node__value')
      .attr('text-anchor', 'middle')
      .attr('y', d => {
        if (d.type === 'outcome') return isFull ? 15 : 19;
        const compact = sizeRef.current.w < 820;
        const lines = wrapLabelLines(d.label, compact ? (isFull ? 8 : 10) : (isFull ? 10 : 12));
        return isFull ? (lines.length > 1 ? 7 : 6) : (lines.length > 1 ? 10 : 8);
      })
      .attr('dominant-baseline', 'central')
      .style('font-family', 'var(--font-mono)')
      .style('font-size', d => {
        const compact = sizeRef.current.w < 820;
        if (d.type === 'outcome') return compact ? (isFull ? '7px' : '8px') : (isFull ? '8.5px' : '9px');
        return compact ? (isFull ? '7.5px' : '10px') : (isFull ? '9px' : '12px');
      })
      .style('font-weight', '700')
      .style('fill', d => d.type === 'treatment' ? '#000000' : '#ffffff')
      .style('pointer-events', 'none')
      .style('user-select', 'none')
      .each(function(d) {
        setNodeValueText(
          d3Selection.select<SVGTextElement, SimNode>(this),
          getNodeValue(d, state),
        );
      });

    /* ── Hover ── */
    nodeGroups
      .on('mouseenter', function() {
        d3Selection.select(this).select('.dag-node__inner').style('transform', 'scale(1.08)');
      })
      .on('mouseleave', function() {
        d3Selection.select(this).select('.dag-node__inner').style('transform', 'scale(1)');
      });

    /* ── Click ── */
    nodeGroups.on('click', function(event: PointerEvent, d: SimNode) {
      event.stopPropagation();
      if (d.type === 'treatment') return;
      if (isFull && !d.stateKey) return;

      const circle = (this as SVGGElement).querySelector('.dag-node__circle') as SVGCircleElement | null;
      if (!circle) return;
      const box = circle.getBoundingClientRect();
      dispatch({ type: 'SELECT_NODE', nodeId: d.id });
      onNodeClick?.(d.id, box.left + box.width / 2 + nodeRadius(d.type) + 12, box.top + box.height / 2 - 20);
    });

    /* ── Tick ── */
    sim.on('tick', () => {
      nodeGroups.attr('transform', d => `translate(${d.x},${d.y})`);
      edgePaths.attr('d', d => {
        const s = d.source as SimNode;
        const t = d.target as SimNode;
        return computeEdgePath(s.x!, s.y!, t.x!, t.y!, nodeRadius(s.type, dagViewMode), nodeRadius(t.type, dagViewMode));
      });
    });

    return () => { sim.stop(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initSimulation, dispatch, onNodeClick, extraKey, activeTreatmentId, dagViewMode]);

  /* ── Update fills + values + selection ring on state change ── */
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const sel = d3Selection.select(svg);
    sel.selectAll<SVGGElement, SimNode>('g.dag-node').each(function(d) {
      const g = d3Selection.select(this);
      setNodeValueText(g.select<SVGTextElement>('.dag-node__value'), getNodeValue(d, state));
      g.select('.dag-node__circle').transition().duration(300).attr('fill', getNodeFillByValue(d, state));
      g.select('.dag-node__selection-ring').attr('opacity', state.selectedNodeId === d.id ? 1 : 0);
    });
  }, [state]);

  /* ── Resize ── */
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || !svg.parentElement) return;
    const observer = new ResizeObserver(entries => {
      for (const entry of entries) {
        const { width: w, height: h } = entry.contentRect;
        if (w < 10 || h < 10) return;
        sizeRef.current = { w, h };
        const sim = simRef.current;
        if (!sim) return;
        sim
          .force('x', d3Force.forceX<SimNode>(d => (d.xPct / 100) * w).strength(0.8))
          .force('y', d3Force.forceY<SimNode>(d => (d.yPct / 100) * h).strength(0.8));
        sim.alpha(0.3).restart();
      }
    });
    observer.observe(svg.parentElement);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="dag" onContextMenu={e => e.preventDefault()}>
      <svg ref={svgRef} />
    </div>
  );
}
