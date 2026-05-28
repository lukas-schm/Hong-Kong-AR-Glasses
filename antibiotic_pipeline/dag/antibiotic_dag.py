"""
Causal DAG for the antibiotic continuation decision in suspected sepsis.

All structure is now sourced from antibiotic_pipeline/definitions/causal_graph.yaml
via the CausalGraph loader. This module provides a thin wrapper and backward-compatible
constants for code that imports from here.
"""

import json
from typing import Dict, List, Tuple

from antibiotic_pipeline.definitions.loader import CAUSAL_GRAPH

# ── Constants (derived from CAUSAL_GRAPH) ─────────────────────────────────────

TREATMENT_NODE: str = CAUSAL_GRAPH.treatment.variable

OUTCOME_NODES: List[str] = CAUSAL_GRAPH.outcome_names

CONFOUNDERS: Dict[str, List[str]] = {
    group: [c.variable for c in CAUSAL_GRAPH.get_group(group)]
    for group in CAUSAL_GRAPH.get_groups()
}

ALL_CONFOUNDERS: List[str] = CAUSAL_GRAPH.all_confounder_names

CONFOUNDER_EDGES: List[Tuple[str, str]] = CAUSAL_GRAPH.dag_edges

UNMEASURED_CONFOUNDERS: List[str] = [u.variable for u in CAUSAL_GRAPH.unmeasured]


# ── DAG class ─────────────────────────────────────────────────────────────────

class AntibioticDAG:
    """Causal DAG for the antibiotic continuation decision.

    Delegates all serialisation to CAUSAL_GRAPH; exposes the same interface
    as before for backward compatibility.
    """

    def __init__(self):
        self.treatment_node = TREATMENT_NODE
        self.outcome_nodes = OUTCOME_NODES
        self.confounders = CONFOUNDERS
        self.confounder_edges = CONFOUNDER_EDGES
        self.unmeasured_confounders = UNMEASURED_CONFOUNDERS

    @property
    def all_confounders(self) -> List[str]:
        return ALL_CONFOUNDERS

    def to_dowhy_graph(self, outcome_node: str = "mortality_28days") -> str:
        return CAUSAL_GRAPH.to_dowhy_graph(outcome_node)

    def to_json(self, outcome_node: str = "mortality_28days") -> dict:
        return CAUSAL_GRAPH.to_json(outcome_node)

    def to_dot(self, outcome_node: str = "mortality_28days") -> str:
        return CAUSAL_GRAPH.to_dot(outcome_node)

    def get_minimal_adjustment_set(self) -> List[str]:
        return ALL_CONFOUNDERS

    def sensitivity_adjustment_sets(self) -> Dict[str, List[str]]:
        return {
            name: CAUSAL_GRAPH.feature_set(name)
            for name in CAUSAL_GRAPH.sensitivity_feature_sets
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

ANTIBIOTIC_DAG = AntibioticDAG()


def save_dag_json(path: str, outcome_node: str = "mortality_28days"):
    with open(path, "w") as f:
        json.dump(ANTIBIOTIC_DAG.to_json(outcome_node), f, indent=2)


if __name__ == "__main__":
    dag = AntibioticDAG()
    print(f"Confounders: {len(dag.all_confounders)}")
    print(f"Confounder edges: {len(dag.confounder_edges)}")
    print("\nDoWhy GML (mortality):")
    print(dag.to_dowhy_graph("mortality_28days")[:500], "...")
    print("\nDOT preview:")
    print(dag.to_dot("mortality_28days")[:500], "...")
