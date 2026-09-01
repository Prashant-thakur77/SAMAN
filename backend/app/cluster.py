"""Pair graph -> clusters -> golden-record drafts (spec §7 M3).

Only pairs the matcher accepted outright become edges. Grey pairs and
`conflict` pairs deliberately do NOT merge anything: they become review tasks,
because merging on an uncertain signal is exactly the failure a materials
registry cannot recover from.

The draft description written here is a placeholder chosen from the members;
M3.4 replaces it with the deterministic per-class template renderer (§2D).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass


class UnionFind:
    """Disjoint sets with path compression and union by size."""

    def __init__(self) -> None:
        self.parent: dict[int, int] = {}
        self.size: dict[int, int] = {}

    def add(self, item: int) -> None:
        if item not in self.parent:
            self.parent[item] = item
            self.size[item] = 1

    def find(self, item: int) -> int:
        self.add(item)
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:  # path compression
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.size[ra] < self.size[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.size[ra] += self.size[rb]

    def groups(self) -> dict[int, list[int]]:
        out: dict[int, list[int]] = defaultdict(list)
        for item in self.parent:
            out[self.find(item)].append(item)
        return out


@dataclass
class ClusterDraft:
    members: list[int]
    std_description: str
    attrs: dict
    status: str  # draft | conflict
    class_code: str


def build_clusters(
    accepted_pairs: list[tuple[int, int]],
    all_item_ids: list[int],
) -> dict[int, list[int]]:
    """Connected components over accepted duplicate edges.

    Every item is added, so a singleton becomes its own cluster: an item with
    no duplicates still needs a golden record and a CNMC.
    """
    uf = UnionFind()
    for item_id in all_item_ids:
        uf.add(item_id)
    for a, b in accepted_pairs:
        uf.union(a, b)
    return uf.groups()


def _completeness(attrs: dict) -> int:
    return sum(1 for k, v in attrs.items() if not k.startswith("_") and v is not None)


def draft_golden(members: list[dict], conflicted: bool = False) -> ClusterDraft:
    """Pick a representative member and merge attributes across the cluster.

    The representative is the most completely-described member, tie-broken by
    the longest normalized text — the row a human would also pick as the
    clearest statement of the item. §2D replaces this with a rendered template.
    """
    best = max(
        members,
        key=lambda m: (_completeness(m["attrs"]), len(m["norm_text"]), -m["id"]),
    )

    # Union of attributes, preferring values seen most often across members.
    tally: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for member in members:
        for key, value in member["attrs"].items():
            if key.startswith("_") or value is None:
                continue
            tally[key][json.dumps(value, sort_keys=True, default=str)] += 1

    merged: dict = {}
    for key, counts in tally.items():
        winner = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
        merged[key] = json.loads(winner)

    return ClusterDraft(
        members=[m["id"] for m in members],
        std_description=best["norm_text"],
        attrs=merged,
        status="conflict" if conflicted else "draft",
        class_code=best["class_code"],
    )


def refine_clusters(
    members: list[int],
    attrs_by_id: dict[int, dict],
    class_by_id: dict[int, str],
    mpn_by_id: dict[int, str | None],
    degree: dict[int, int],
) -> list[list[int]]:
    """Split a cluster until no two members inside it would be refused.

    Connected components merge transitively: A matches B and B matches C puts
    all three together even when A and C are a hard-constraint mismatch. That
    is precisely what §2A forbids — "similarity never overrides a veto" has to
    hold across the closure, not just pair by pair, or one chain of near-misses
    collapses a whole class into a single cluster.

    The same argument applies to every reason the matcher refuses a pair, not
    only to §2A vetoes. Two manufacturers' catalogue records are refused
    pairwise (§2B), and without this they would still end up merged through a
    third item that resembles both.

    Members are placed most-connected first, so the genuine core of a cluster
    forms before its fringe, and a member joins a sub-cluster only if it is
    conflict-free against *every* member already there (complete linkage on the
    refusal relation).
    """
    from .compare import compare_attrs
    from .match import MatchCandidate, distinct_manufacturers
    from .taxonomy import get_schema

    if len(members) < 3:
        return [members]

    cache: dict[tuple[int, int], bool] = {}

    def _candidate(item: int) -> MatchCandidate:
        return MatchCandidate(
            id=item,
            class_code=class_by_id.get(item, ""),
            class_confidence=1.0,
            norm_text="",
            norm_hash="",
            mpn_norm=mpn_by_id.get(item),
            gtin=None,
            attrs=attrs_by_id.get(item, {}),
        )

    def conflicts(a: int, b: int) -> bool:
        key = (a, b) if a < b else (b, a)
        if key in cache:
            return cache[key]

        if distinct_manufacturers(_candidate(a), _candidate(b)):
            cache[key] = True
        elif class_by_id.get(a) != class_by_id.get(b):
            # Cross-class pairs never had a shared schema to veto with; they
            # can only have been joined by an exact anchor key.
            cache[key] = False
        else:
            schema = get_schema(class_by_id.get(a, ""))
            cache[key] = compare_attrs(
                attrs_by_id.get(a, {}), attrs_by_id.get(b, {}), schema
            ).is_veto
        return cache[key]

    ordered = sorted(members, key=lambda i: (-degree.get(i, 0), i))
    subclusters: list[list[int]] = []
    for item in ordered:
        for sub in subclusters:
            if not any(conflicts(item, other) for other in sub):
                sub.append(item)
                break
        else:
            subclusters.append([item])
    return subclusters
