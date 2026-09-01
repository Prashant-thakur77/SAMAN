"""Clustering and refinement — spec §7 M3, §2A."""

from app.cluster import UnionFind, build_clusters, draft_golden, refine_clusters

BEARING = "bearing.ball.deep_groove"


class TestUnionFind:
    def test_transitive_merge(self):
        uf = UnionFind()
        uf.union(1, 2)
        uf.union(2, 3)
        assert uf.find(1) == uf.find(3)

    def test_disjoint_stay_disjoint(self):
        uf = UnionFind()
        uf.union(1, 2)
        uf.union(3, 4)
        assert uf.find(1) != uf.find(3)


class TestBuildClusters:
    def test_components_are_found(self):
        groups = build_clusters([(1, 2), (2, 3), (5, 6)], [1, 2, 3, 4, 5, 6, 7])
        assert sorted(sorted(v) for v in groups.values()) == [[1, 2, 3], [4], [5, 6], [7]]

    def test_an_item_with_no_duplicates_is_still_a_cluster(self):
        """A singleton still needs a golden record and a CNMC."""
        groups = build_clusters([], [1, 2])
        assert len(groups) == 2


class TestRefinement:
    """The transitive over-merge §2A forbids."""

    def _attrs(self, bore):
        return {
            "bore_mm": bore, "outer_dia_mm": 52, "width_mm": 15,
            "seal_type": "ZZ", "load_rating_kg": 500, "temp_max_c": 120,
        }

    def test_a_vetoed_pair_is_split_out_of_a_chain(self):
        """A(25) - B(25) - C(30): C must not ride into A's cluster."""
        attrs = {1: self._attrs(25), 2: self._attrs(25), 3: self._attrs(30)}
        classes = dict.fromkeys(attrs, BEARING)
        parts = refine_clusters([1, 2, 3], attrs, classes, {}, {1: 2, 2: 2, 3: 1})
        assert len(parts) == 2
        placement = {i: n for n, part in enumerate(parts) for i in part}
        assert placement[1] == placement[2] != placement[3]

    def test_a_clean_cluster_is_left_alone(self):
        attrs = {i: self._attrs(25) for i in (1, 2, 3)}
        classes = dict.fromkeys(attrs, BEARING)
        assert refine_clusters([1, 2, 3], attrs, classes, {}, {}) == [[1, 2, 3]]

    def test_distinct_manufacturers_are_split_even_when_specs_agree(self):
        """§2B: SKF and FAG records are interchangeable, not identical — and
        they must not be merged transitively through a third item either."""
        attrs = {
            1: {**self._attrs(25), "brand": "SKF"},
            2: {**self._attrs(25), "brand": "SKF"},
            3: {**self._attrs(25), "brand": "FAG"},
        }
        classes = dict.fromkeys(attrs, BEARING)
        mpns = {1: "62052Z", 2: "62052Z", 3: "62052ZR"}
        parts = refine_clusters([1, 2, 3], attrs, classes, mpns, {1: 2, 2: 2, 3: 1})
        placement = {i: n for n, part in enumerate(parts) for i in part}
        assert placement[1] == placement[2] != placement[3]

    def test_pairs_smaller_than_three_are_untouched(self):
        assert refine_clusters([1, 2], {}, {}, {}, {}) == [[1, 2]]

    def test_most_connected_members_form_the_core_first(self):
        """The genuine core should survive intact; the fringe splits off."""
        attrs = {1: self._attrs(25), 2: self._attrs(25), 3: self._attrs(25), 4: self._attrs(30)}
        classes = dict.fromkeys(attrs, BEARING)
        parts = refine_clusters([1, 2, 3, 4], attrs, classes, {}, {1: 5, 2: 5, 3: 5, 4: 1})
        assert sorted(len(p) for p in parts) == [1, 3]


class TestGoldenDraft:
    def test_the_most_complete_member_is_the_representative(self):
        draft = draft_golden(
            [
                {"id": 1, "norm_text": "BEARING 6205", "attrs": {"bore_mm": 25}, "class_code": BEARING},
                {
                    "id": 2,
                    "norm_text": "BEARING BALL 6205 ZZ 25MM BORE SKF",
                    "attrs": {"bore_mm": 25, "seal_type": "ZZ", "brand": "SKF"},
                    "class_code": BEARING,
                },
            ]
        )
        assert draft.std_description == "BEARING BALL 6205 ZZ 25MM BORE SKF"
        assert draft.attrs["seal_type"] == "ZZ"

    def test_attributes_are_merged_by_majority(self):
        members = [
            {"id": i, "norm_text": "X", "attrs": {"seal_type": seal}, "class_code": BEARING}
            for i, seal in [(1, "ZZ"), (2, "ZZ"), (3, "2RS")]
        ]
        assert draft_golden(members).attrs["seal_type"] == "ZZ"

    def test_private_keys_are_not_promoted_into_the_golden_record(self):
        members = [
            {"id": 1, "norm_text": "X", "attrs": {"bore_mm": 25, "_designation": "6205"},
             "class_code": BEARING}
        ]
        assert "_designation" not in draft_golden(members).attrs

    def test_a_conflicted_cluster_is_marked(self):
        members = [{"id": 1, "norm_text": "X", "attrs": {}, "class_code": BEARING}]
        assert draft_golden(members, conflicted=True).status == "conflict"
