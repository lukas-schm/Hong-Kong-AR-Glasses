"""
Loader for causal_graph.yaml — single source of truth for all pipeline variables.

Usage
-----
    from antibiotic_pipeline.definitions.loader import CausalGraph, CAUSAL_GRAPH

    # Access all confounder names
    print(CAUSAL_GRAPH.all_confounder_names)

    # Get confounders by type
    print(CAUSAL_GRAPH.numerical_confounders)
    print(CAUSAL_GRAPH.binary_confounders)
    print(CAUSAL_GRAPH.categorical_confounders)

    # Get a feature set (for sensitivity analysis)
    cols = CAUSAL_GRAPH.feature_set("no_infection_markers")

    # Generate DoWhy GML graph
    gml = CAUSAL_GRAPH.to_dowhy_graph("mortality_28days")

    # Generate JSON for frontend DAG
    dag_json = CAUSAL_GRAPH.to_json("mortality_28days")
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

_YAML_PATH = Path(__file__).parent / "causal_graph.yaml"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class TreatmentArm:
    id: int
    label: str
    description: str
    drug_classes: List[str]


@dataclass
class TreatmentDef:
    variable: str
    type: str
    classification_window_hours: int
    arms: List[TreatmentArm]
    drug_lists: Dict[str, List[str]]
    source_derived_table: str
    source_raw_table: str

    @property
    def all_broad_spectrum_drugs(self) -> List[str]:
        broad_classes = ["carbapenems", "glycopeptides", "broad_betalactams", "aminoglycosides"]
        return [d for cls in broad_classes for d in self.drug_lists.get(cls, [])]

    @property
    def all_narrow_spectrum_drugs(self) -> List[str]:
        narrow_classes = ["narrow_betalactams", "nitroimidazoles", "macrolides", "sulfonamides"]
        return [d for cls in narrow_classes for d in self.drug_lists.get(cls, [])]


@dataclass
class OutcomeDef:
    variable: str
    type: str
    label: str
    primary: bool
    computation: str
    source_table: str
    source_column: Optional[str]
    follow_up_days: int


@dataclass
class ConfounderDef:
    variable: str
    group: str
    type: str
    label: str
    identification_type: str
    aggregation: str
    source_table: str
    source_column: Optional[str]
    filter_sql: Optional[str]
    coding: Optional[str]
    clinical_justification: Optional[str]
    note: Optional[str]
    range: Optional[List[float]]
    categories: Optional[List[int]]


@dataclass
class UnmeasuredConfounderDef:
    variable: str
    threat_level: str
    description: str
    sensitivity_approach: str


@dataclass
class SensitivityFeatureSet:
    name: str
    description: str
    exclude_groups: List[str]
    include_groups: Optional[List[str]]  # if set, only include these groups


# ── Main class ────────────────────────────────────────────────────────────────

@dataclass
class CausalGraph:
    """Loaded causal graph — single source of truth for the pipeline."""

    metadata: Dict
    treatment: TreatmentDef
    outcomes: List[OutcomeDef]
    confounders: List[ConfounderDef]
    unmeasured: List[UnmeasuredConfounderDef]
    dag_edges: List[Tuple[str, str]]
    cate_features: List[str]
    sensitivity_feature_sets: Dict[str, SensitivityFeatureSet]

    # ── Confounder accessors ───────────────────────────────────────────────

    @property
    def all_confounder_names(self) -> List[str]:
        return [c.variable for c in self.confounders]

    @property
    def numerical_confounders(self) -> List[str]:
        return [c.variable for c in self.confounders if c.type in ("continuous",)]

    @property
    def binary_confounders(self) -> List[str]:
        return [c.variable for c in self.confounders if c.type == "binary"]

    @property
    def categorical_confounders(self) -> List[str]:
        return [c.variable for c in self.confounders if c.type == "categorical"]

    def get_group(self, group: str) -> List[ConfounderDef]:
        return [c for c in self.confounders if c.group == group]

    def get_groups(self) -> List[str]:
        seen, groups = set(), []
        for c in self.confounders:
            if c.group not in seen:
                groups.append(c.group)
                seen.add(c.group)
        return groups

    def get_by_aggregation(self, aggregation: str) -> List[ConfounderDef]:
        return [c for c in self.confounders if c.aggregation == aggregation]

    def feature_set(self, name: str = "all_confounders") -> List[str]:
        """Return confounder variable names for a named sensitivity feature set."""
        if name not in self.sensitivity_feature_sets:
            raise KeyError(f"Feature set '{name}' not found. "
                           f"Available: {list(self.sensitivity_feature_sets)}")
        fs = self.sensitivity_feature_sets[name]
        if fs.include_groups:
            return [c.variable for c in self.confounders if c.group in fs.include_groups]
        return [c.variable for c in self.confounders if c.group not in fs.exclude_groups]

    # ── Outcome accessors ──────────────────────────────────────────────────

    @property
    def primary_outcome(self) -> OutcomeDef:
        return next(o for o in self.outcomes if o.primary)

    @property
    def outcome_names(self) -> List[str]:
        return [o.variable for o in self.outcomes]

    # ── DAG serialisation ──────────────────────────────────────────────────

    def to_dowhy_graph(self, outcome_name: str) -> str:
        """Serialise to DoWhy GML graph string for a single outcome."""
        nodes = self.all_confounder_names + [self.treatment.variable, outcome_name]
        node_str = "\n".join(f'  node [ id "{n}" label "{n}" ]' for n in nodes)

        edges = []
        for w in self.all_confounder_names:
            edges.append(f'  edge [ source "{w}" target "{self.treatment.variable}" ]')
            edges.append(f'  edge [ source "{w}" target "{outcome_name}" ]')
        edges.append(
            f'  edge [ source "{self.treatment.variable}" target "{outcome_name}" ]'
        )
        for src, tgt in self.dag_edges:
            if src in nodes and tgt in nodes:
                edges.append(f'  edge [ source "{src}" target "{tgt}" ]')

        return f"graph [\n  directed 1\n{node_str}\n{'  '.join(edges)}\n]"

    def to_json(self, outcome_name: str = "mortality_28days") -> dict:
        """Serialise to JSON for the CDSS frontend DAG viewer."""
        _GROUP_COLORS = {
            "illness_severity":  "#BBDEFB",
            "infection_certainty": "#C8E6C9",
            "organ_dysfunction": "#FFE0B2",
            "treatment_history": "#F3E5F5",
            "trajectory":        "#FFF9C4",
            "demographics":      "#E0E0E0",
            "clinical_intent":   "#FFCCBC",
        }
        nodes = []
        for c in self.confounders:
            nodes.append({
                "id": c.variable,
                "label": c.label,
                "type": "confounder",
                "group": c.group,
                "color": _GROUP_COLORS.get(c.group, "#E0E0E0"),
                "variable_type": c.type,
            })
        nodes.append({"id": self.treatment.variable, "label": "Treatment arm",
                       "type": "treatment", "group": "treatment", "color": "#2196F3"})
        outcome = next((o for o in self.outcomes if o.variable == outcome_name), None)
        nodes.append({"id": outcome_name, "label": outcome.label if outcome else outcome_name,
                       "type": "outcome", "group": "outcome", "color": "#F44336"})

        edges = []
        for w in self.all_confounder_names:
            edges.append({"source": w, "target": self.treatment.variable,
                           "type": "confounder_to_treatment"})
            edges.append({"source": w, "target": outcome_name,
                           "type": "confounder_to_outcome"})
        edges.append({"source": self.treatment.variable, "target": outcome_name,
                       "type": "treatment_effect"})
        for src, tgt in self.dag_edges:
            edges.append({"source": src, "target": tgt, "type": "within_confounder"})

        return {
            "nodes": nodes,
            "edges": edges,
            "treatment": self.treatment.variable,
            "outcome": outcome_name,
            "n_confounders": len(self.confounders),
            "confounder_groups": self.get_groups(),
            "unmeasured_confounders": [
                {"variable": u.variable, "threat_level": u.threat_level,
                 "description": u.description}
                for u in self.unmeasured
            ],
            "identification_assumption": self.metadata.get("identification_assumption", ""),
        }

    def to_dot(self, outcome_name: str = "mortality_28days") -> str:
        """Serialise to Graphviz DOT format."""
        _GROUP_COLORS = {
            "illness_severity":  "#BBDEFB",
            "infection_certainty": "#C8E6C9",
            "organ_dysfunction": "#FFE0B2",
            "treatment_history": "#F3E5F5",
            "trajectory":        "#FFF9C4",
            "demographics":      "#E0E0E0",
            "clinical_intent":   "#FFCCBC",
        }
        lines = ["digraph AntibioticDAG {", "  rankdir=LR;",
                 '  node [shape=box, style=filled, fontsize=10];']
        lines.append(f'  "{self.treatment.variable}" [fillcolor="#2196F3", fontcolor=white, label="Treatment arm"];')
        lines.append(f'  "{outcome_name}" [fillcolor="#F44336", fontcolor=white];')
        for c in self.confounders:
            color = _GROUP_COLORS.get(c.group, "#E0E0E0")
            short = c.label[:30]
            lines.append(f'  "{c.variable}" [fillcolor="{color}", label="{short}"];')
        for w in self.all_confounder_names:
            lines.append(f'  "{w}" -> "{self.treatment.variable}" [color=gray, style=dashed];')
            lines.append(f'  "{w}" -> "{outcome_name}" [color=gray, style=dashed];')
        lines.append(f'  "{self.treatment.variable}" -> "{outcome_name}" [color="#2196F3", penwidth=2];')
        for src, tgt in self.dag_edges:
            lines.append(f'  "{src}" -> "{tgt}" [color=orange, style=dotted];')
        lines.append("}")
        return "\n".join(lines)


# ── YAML parser ───────────────────────────────────────────────────────────────

def load_causal_graph(path: Path = _YAML_PATH) -> CausalGraph:
    """Parse causal_graph.yaml into a CausalGraph instance."""
    with open(path) as f:
        raw = yaml.safe_load(f)

    # Treatment
    t = raw["treatment"]
    arms = [TreatmentArm(**a) for a in t["arms"]]
    treatment = TreatmentDef(
        variable=t["variable"],
        type=t["type"],
        classification_window_hours=t["classification_window_hours"],
        arms=arms,
        drug_lists=t.get("drug_lists", {}),
        source_derived_table=t["source"]["derived_table"],
        source_raw_table=t["source"]["raw_table"],
    )

    # Outcomes
    outcomes = []
    for o in raw["outcomes"]:
        outcomes.append(OutcomeDef(
            variable=o["variable"],
            type=o["type"],
            label=o["label"],
            primary=o.get("primary", False),
            computation=o.get("computation", ""),
            source_table=o.get("source_table", ""),
            source_column=o.get("source_column"),
            follow_up_days=o.get("follow_up_days", 28),
        ))

    # Confounders
    confounders = []
    for c in raw["confounders"]:
        confounders.append(ConfounderDef(
            variable=c["variable"],
            group=c["group"],
            type=c["type"],
            label=c.get("label", c["variable"]),
            identification_type=c.get("identification_type", "measured"),
            aggregation=c.get("aggregation", "last_before_decision"),
            source_table=c.get("source_table", ""),
            source_column=c.get("source_column"),
            filter_sql=c.get("filter_sql"),
            coding=c.get("coding"),
            clinical_justification=c.get("clinical_justification"),
            note=c.get("note"),
            range=c.get("range"),
            categories=c.get("categories"),
        ))

    # Unmeasured
    unmeasured = []
    for u in raw.get("unmeasured_confounders", []):
        unmeasured.append(UnmeasuredConfounderDef(
            variable=u["variable"],
            threat_level=u["threat_level"],
            description=u["description"],
            sensitivity_approach=u.get("sensitivity_approach", ""),
        ))

    # DAG edges
    dag_edges = [
        (e[0], e[1])
        for e in raw.get("dag_edges", {}).get("within_confounders", [])
    ]

    # CATE features
    cate_features = raw.get("cate_features", [])

    # Sensitivity feature sets
    sensitivity_feature_sets = {}
    for name, fs in raw.get("sensitivity_feature_sets", {}).items():
        sensitivity_feature_sets[name] = SensitivityFeatureSet(
            name=name,
            description=fs.get("description", ""),
            exclude_groups=fs.get("exclude_groups", []),
            include_groups=fs.get("include_groups"),
        )
    # Always ensure "all_confounders" exists
    if "all_confounders" not in sensitivity_feature_sets:
        sensitivity_feature_sets["all_confounders"] = SensitivityFeatureSet(
            name="all_confounders",
            description="Full adjustment set",
            exclude_groups=[],
            include_groups=None,
        )

    return CausalGraph(
        metadata=raw.get("metadata", {}),
        treatment=treatment,
        outcomes=outcomes,
        confounders=confounders,
        unmeasured=unmeasured,
        dag_edges=dag_edges,
        cate_features=cate_features,
        sensitivity_feature_sets=sensitivity_feature_sets,
    )


# ── Module-level singleton ────────────────────────────────────────────────────

CAUSAL_GRAPH: CausalGraph = load_causal_graph()


if __name__ == "__main__":
    cg = CAUSAL_GRAPH
    print(f"Loaded causal graph: {cg.metadata['title']}")
    print(f"  Confounders : {len(cg.confounders)} ({', '.join(cg.get_groups())})")
    print(f"  Outcomes    : {len(cg.outcomes)} (primary: {cg.primary_outcome.variable})")
    print(f"  DAG edges   : {len(cg.dag_edges)} within-confounder")
    print(f"  Unmeasured  : {len(cg.unmeasured)} threats documented")
    print(f"\nFeature sets:")
    for name in cg.sensitivity_feature_sets:
        cols = cg.feature_set(name)
        print(f"  {name}: {len(cols)} features")
