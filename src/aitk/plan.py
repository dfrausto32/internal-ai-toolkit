"""Phase 5 node-spec schema — the contract the planner writes and the scheduler reads.

A *node* is one unit of work in a plan's DAG. It maps to a multi-file output scope, declares
its dependencies, and carries the acceptance criteria a reviewer checks against. This module
models a node spec, parses it from a frontmatter Markdown file, and validates a whole plan
(unique ids, resolvable dependencies, acyclic) plus write-scope overlap detection used later by
the broker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from aitk.spec import parse_spec

VALIDATION_KINDS = ("automated", "gated")


@dataclass(frozen=True)
class Criterion:
    """A single acceptance criterion with a stable id (e.g. AC-1)."""
    id: str
    text: str


@dataclass
class NodeSpec:
    """One node in a plan's DAG — its id, dependencies, output scope, and acceptance criteria."""
    id: str
    body: str = ""
    language: str = "python"
    frameworks: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    output_scope: list[str] = field(default_factory=list)
    acceptance_criteria: list[Criterion] = field(default_factory=list)
    validation_kind: str = "automated"
    test_command: str | None = None
    estimated_lines: int | None = None

    @classmethod
    def from_meta(cls, meta: dict, body: str = "") -> "NodeSpec":
        """Build a NodeSpec from parsed frontmatter, normalizing acceptance criteria."""
        node_id = meta.get("id")
        if not node_id:
            raise ValueError("node spec is missing required field 'id'")
        return cls(
            id=str(node_id),
            body=body,
            language=meta.get("language", "python"),
            frameworks=list(meta.get("frameworks") or []),
            depends_on=[str(d) for d in (meta.get("depends_on") or [])],
            output_scope=[str(p) for p in (meta.get("output_scope") or [])],
            acceptance_criteria=_normalize_criteria(meta.get("acceptance_criteria") or []),
            validation_kind=meta.get("validation_kind", "automated"),
            test_command=meta.get("test_command"),
            estimated_lines=meta.get("estimated_lines"),
        )


def _normalize_criteria(raw: list) -> list[Criterion]:
    """Accept criteria as plain strings or {id, text} dicts; assign positional ids to strings."""
    out: list[Criterion] = []
    for i, item in enumerate(raw, start=1):
        if isinstance(item, str):
            out.append(Criterion(id=f"AC-{i}", text=item))
        elif isinstance(item, dict):
            cid = str(item.get("id") or f"AC-{i}")
            text = str(item.get("text", "")).strip()
            out.append(Criterion(id=cid, text=text))
        else:
            raise ValueError(f"acceptance_criteria[{i - 1}] must be a string or a mapping")
    return out


def parse_node_spec(path: str) -> NodeSpec:
    """Parse a node-spec Markdown file (frontmatter + body) into a NodeSpec."""
    meta, body = parse_spec(path)
    return NodeSpec.from_meta(meta, body)


def validate_plan(nodes: list[NodeSpec]) -> list[str]:
    """Return a list of human-readable errors for a plan; empty list means the plan is valid."""
    errors: list[str] = []

    ids = [n.id for n in nodes]
    seen: set[str] = set()
    for nid in ids:
        if nid in seen:
            errors.append(f"duplicate node id: {nid!r}")
        seen.add(nid)
    id_set = set(ids)

    for node in nodes:
        if node.validation_kind not in VALIDATION_KINDS:
            errors.append(
                f"node {node.id!r}: invalid validation_kind {node.validation_kind!r} "
                f"(expected one of {VALIDATION_KINDS})"
            )
        for dep in node.depends_on:
            if dep not in id_set:
                errors.append(f"node {node.id!r}: depends_on unknown node {dep!r}")
            if dep == node.id:
                errors.append(f"node {node.id!r}: depends on itself")
        crit_ids: set[str] = set()
        for crit in node.acceptance_criteria:
            if crit.id in crit_ids:
                errors.append(f"node {node.id!r}: duplicate acceptance-criterion id {crit.id!r}")
            crit_ids.add(crit.id)

    cycle = _find_cycle(nodes)
    if cycle:
        errors.append("dependency cycle: " + " -> ".join(cycle))

    return errors


def topological_levels(nodes: list[NodeSpec]) -> list[list[str]]:
    """Group node ids into dependency levels; nodes in the same level have no edge between them.

    Level 0 has no dependencies; each later level depends only on earlier ones. Raises
    ValueError if the plan contains a cycle (validate_plan reports it more gently).
    """
    by_id = {n.id: n for n in nodes}
    remaining = {n.id: {d for d in n.depends_on if d in by_id} for n in nodes}
    levels: list[list[str]] = []
    while remaining:
        ready = sorted(nid for nid, deps in remaining.items() if not deps)
        if not ready:
            raise ValueError("cannot compute levels: dependency cycle present")
        levels.append(ready)
        for nid in ready:
            del remaining[nid]
        for deps in remaining.values():
            deps.difference_update(ready)
    return levels


def _find_cycle(nodes: list[NodeSpec]) -> list[str]:
    """Return one cycle as a list of node ids (with the start repeated at the end), or []."""
    by_id = {n.id: n for n in nodes}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in by_id}
    stack: list[str] = []

    def visit(nid: str) -> list[str]:
        color[nid] = GRAY
        stack.append(nid)
        for dep in by_id[nid].depends_on:
            if dep not in by_id:
                continue
            if color[dep] == GRAY:
                return stack[stack.index(dep):] + [dep]
            if color[dep] == WHITE:
                found = visit(dep)
                if found:
                    return found
        color[nid] = BLACK
        stack.pop()
        return []

    for nid in by_id:
        if color[nid] == WHITE:
            found = visit(nid)
            if found:
                return found
    return []


# --- write-scope overlap (used later by the broker's write-lease registry) ---

def _norm(path: str) -> PurePosixPath:
    """Normalize a scope entry to a comparable POSIX path (no trailing slash)."""
    return PurePosixPath(path.strip().rstrip("/"))


def _is_prefix(a: PurePosixPath, b: PurePosixPath) -> bool:
    """True if path a equals b or is an ancestor directory of b."""
    return a == b or b.is_relative_to(a)


def paths_conflict(a: str, b: str) -> bool:
    """True if two scope entries collide: equal, or one is a directory prefix of the other."""
    na, nb = _norm(a), _norm(b)
    return _is_prefix(na, nb) or _is_prefix(nb, na)


def scopes_overlap(scope_a: list[str], scope_b: list[str]) -> bool:
    """True if any path in scope_a conflicts with any path in scope_b."""
    return any(paths_conflict(x, y) for x in scope_a for y in scope_b)


def find_scope_conflicts(nodes: list[NodeSpec]) -> list[tuple[str, str]]:
    """Return sorted (id_a, id_b) pairs whose output scopes overlap.

    This is the raw overlap set. The scheduler later excludes pairs already serialized by a
    dependency edge; here we report all overlaps so the planner can be warned about collisions.
    """
    conflicts: list[tuple[str, str]] = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = nodes[i], nodes[j]
            if a.output_scope and b.output_scope and scopes_overlap(a.output_scope, b.output_scope):
                conflicts.append(tuple(sorted((a.id, b.id))))
    return sorted(conflicts)
