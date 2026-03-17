"""TaskGraph: DAG-based workflow engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from typing import Any


@dataclass
class TaskNode:
    """A single node in the task execution graph."""

    name: str
    agent_type: str
    dependencies: list[str] = field(default_factory=list)
    input_context: dict[str, Any] = field(default_factory=dict)
    output_context: dict[str, Any] = field(default_factory=dict)


class TaskGraph:
    """Directed acyclic graph of tasks.

    Nodes represent pipeline stages; edges encode execution order.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, TaskNode] = {}
        self._edges: dict[str, list[str]] = {}  # node -> list of successors

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def add_node(self, node: TaskNode) -> None:
        """Register a task node."""
        self._nodes[node.name] = node
        if node.name not in self._edges:
            self._edges[node.name] = []

    def add_edge(self, from_node: str, to_node: str) -> None:
        """Add a directed edge from_node → to_node."""
        if from_node not in self._nodes:
            raise ValueError(f"Unknown node: {from_node!r}")
        if to_node not in self._nodes:
            raise ValueError(f"Unknown node: {to_node!r}")
        if to_node not in self._edges[from_node]:
            self._edges[from_node].append(to_node)

    # ------------------------------------------------------------------
    # Execution ordering (topological sort — Kahn's algorithm)
    # ------------------------------------------------------------------

    def get_execution_order(self) -> list[str]:
        """Return node names in topological order.

        Raises ValueError if a cycle is detected.
        """
        in_degree: dict[str, int] = {n: 0 for n in self._nodes}
        for src, successors in self._edges.items():
            for dst in successors:
                in_degree[dst] += 1

        queue: deque[str] = deque(n for n, d in in_degree.items() if d == 0)
        order: list[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for successor in self._edges.get(node, []):
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    queue.append(successor)

        if len(order) != len(self._nodes):
            raise ValueError("Cycle detected in task graph")

        return order

    # ------------------------------------------------------------------
    # Convenience factory
    # ------------------------------------------------------------------

    @classmethod
    def default_pipeline(cls) -> "TaskGraph":
        """Return the standard plan → implement → validate → review pipeline."""
        graph = cls()
        for name, agent in [
            ("plan", "planner"),
            ("implement", "implementer"),
            ("validate", "validator"),
            ("review", "reviewer"),
        ]:
            graph.add_node(TaskNode(name=name, agent_type=agent))

        graph.add_edge("plan", "implement")
        graph.add_edge("implement", "validate")
        graph.add_edge("validate", "review")
        return graph

    @property
    def nodes(self) -> dict[str, TaskNode]:
        return dict(self._nodes)
