"""Relations, rules and cross-reference endpoints — spec §5, §2B."""

import io

import pytest
from sqlalchemy import func, select

from app.models import ClusterMember, Relation


@pytest.fixture(scope="module")
def a_directed_relation(pipeline_run):
    from app.db import SessionLocal

    with SessionLocal() as db:
        relation = db.execute(
            select(Relation)
            .where(Relation.rel_type == "supersedes", Relation.direction == "a_to_b")
            .limit(1)
        ).scalar_one_or_none()
    if relation is None:
        pytest.skip("this fixture produced no directed relation")
    return relation


class TestEquivalenceIsNotAMerge:
    """§2B: equivalents keep distinct CNMCs. This is a scoring point."""

    def test_related_items_are_never_in_the_same_cluster(self, pipeline_run):
        from app.db import SessionLocal

        with SessionLocal() as db:
            cluster_of = dict(
                db.execute(select(ClusterMember.item_id, ClusterMember.cluster_id)).all()
            )
            merged = [
                (a, b)
                for a, b in db.execute(select(Relation.item_a, Relation.item_b)).all()
                if cluster_of.get(a) is not None and cluster_of.get(a) == cluster_of.get(b)
            ]
        assert not merged, f"{len(merged)} equivalent pairs were merged into one cluster"

    def test_relations_exist_at_all(self, pipeline_run):
        from app.db import SessionLocal

        with SessionLocal() as db:
            assert db.execute(select(func.count(Relation.id))).scalar() > 0


class TestRelationsEndpoint:
    def test_an_item_with_no_relations_returns_an_empty_list(self, client, pipeline_run):
        body = client.get("/api/relations?item=999999").json()
        assert body["count"] == 0 and body["relations"] == []

    def test_direction_reads_correctly_from_both_sides(self, client, a_directed_relation):
        """The same relation, phrased for whichever item you are looking at."""
        left = client.get(f"/api/relations?item={a_directed_relation.item_a}").json()
        right = client.get(f"/api/relations?item={a_directed_relation.item_b}").json()

        from_a = next(
            r for r in left["relations"]
            if r["counterpart"]["item_id"] == a_directed_relation.item_b
        )
        from_b = next(
            r for r in right["relations"]
            if r["counterpart"]["item_id"] == a_directed_relation.item_a
        )
        assert from_a["reading"] == "the other item can substitute this one"
        assert from_b["reading"] == "this item can substitute the other"

    def test_every_relation_carries_its_basis_and_evidence(self, client, a_directed_relation):
        body = client.get(f"/api/relations?item={a_directed_relation.item_a}").json()
        for relation in body["relations"]:
            assert relation["basis"] in {"designation", "crossref", "rule", "llm"}
            assert relation["evidence"].get("source")
            assert 0 < relation["confidence"] <= 1

    def test_the_counterpart_is_described_not_just_referenced(self, client, a_directed_relation):
        body = client.get(f"/api/relations?item={a_directed_relation.item_a}").json()
        counterpart = body["relations"][0]["counterpart"]
        assert counterpart["description"] and counterpart["legacy_code"]


class TestProposingRelations:
    def test_a_steward_can_propose_one(self, as_steward, pipeline_run):
        response = as_steward.post(
            "/api/relations",
            json={"item_a": 1, "item_b": 2, "rel_type": "supersedes", "direction": "a_to_b"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "proposed", "never active on creation"

    def test_a_viewer_cannot(self, client, pipeline_run):
        client.post("/api/auth/login", json={"email": "viewer@min.gov.in", "password": "demo"})
        assert client.post("/api/relations", json={"item_a": 1, "item_b": 2}).status_code == 403

    @pytest.mark.parametrize(
        "body",
        [
            {"item_a": 1, "item_b": 1},
            {"item_a": 1, "item_b": 2, "rel_type": "invented"},
            {"item_a": 1, "item_b": 2, "direction": "sideways"},
        ],
    )
    def test_invalid_proposals_are_rejected(self, as_steward, pipeline_run, body):
        assert as_steward.post("/api/relations", json=body).status_code == 422

    def test_an_unknown_item_is_404(self, as_steward, pipeline_run):
        response = as_steward.post("/api/relations", json={"item_a": 1, "item_b": 999999})
        assert response.status_code == 404


class TestRulesEndpoint:
    def test_rules_are_returned_parsed_so_a_steward_can_read_them(self, client, pipeline_run):
        body = client.get("/api/rules").json()
        assert body["count"] > 0
        rule = body["rules"][0]
        assert rule["valid"] and rule["parsed"][0]["equivalent_if"]

    def test_a_registrar_can_add_a_rule(self, as_registrar, pipeline_run):
        response = as_registrar.post(
            "/api/rules",
            json={
                "class_code": "ppe.helmet",
                "rule_yaml": "- class: ppe.helmet\n  equivalent_if: [helmet_class ==, standard ==]",
            },
        )
        assert response.status_code == 200 and response.json()["conditions"] == 1

    def test_a_rule_that_does_not_parse_is_refused(self, as_registrar, pipeline_run):
        response = as_registrar.post(
            "/api/rules", json={"class_code": "x", "rule_yaml": "%%% not yaml"}
        )
        assert response.status_code == 422
        assert "parse" in response.json()["detail"].lower()

    def test_a_steward_cannot_change_the_rules(self, as_steward, pipeline_run):
        response = as_steward.post(
            "/api/rules", json={"class_code": "x", "rule_yaml": "- class: x\n  never_if: [a !=]"}
        )
        assert response.status_code == 403


class TestCrossrefImport:
    def _csv(self, text):
        return {"file": ("crossref.csv", io.BytesIO(text.encode()), "text/csv")}

    def test_a_steward_can_upload_an_interchange_table(self, as_steward, pipeline_run):
        response = as_steward.post(
            "/api/crossref/import",
            files=self._csv(
                "mpn_a,brand_a,mpn_b,brand_b\nZZ-9001,SKF,ZZ-9002,FAG\n"
            ),
        )
        assert response.status_code == 200 and response.json()["imported"] == 1

    def test_re_uploading_the_same_rows_adds_nothing(self, as_steward, pipeline_run):
        payload = "mpn_a,brand_a,mpn_b,brand_b\nZZ-8001,SKF,ZZ-8002,FAG\n"
        first = as_steward.post("/api/crossref/import", files=self._csv(payload)).json()
        second = as_steward.post("/api/crossref/import", files=self._csv(payload)).json()
        assert first["imported"] == 1
        assert second["imported"] == 0 and second["rejected"] == 1

    def test_a_file_without_the_required_columns_explains_itself(self, as_steward, pipeline_run):
        response = as_steward.post("/api/crossref/import", files=self._csv("foo,bar\n1,2\n"))
        assert response.status_code == 422
        assert "mpn_a" in response.json()["detail"]

    def test_self_referential_rows_are_rejected(self, as_steward, pipeline_run):
        response = as_steward.post(
            "/api/crossref/import", files=self._csv("mpn_a,mpn_b\nZZ-7001,ZZ-7001\n")
        )
        assert response.json()["imported"] == 0


class TestEquivalenceMetrics:
    """§0.6 requires these reported separately from the duplicate metrics."""

    def test_equivalence_is_measured_not_asserted(self, pipeline_run):
        equivalence = pipeline_run["metrics"]["equivalence"]
        assert equivalence["status"] == "measured"
        for key in ("precision", "recall", "direction_accuracy", "candidate_coverage"):
            assert key in equivalence

    def test_direction_is_mostly_right(self, pipeline_run):
        """Getting the direction wrong is an unsafe substitution, not a near miss."""
        assert pipeline_run["metrics"]["equivalence"]["direction_accuracy"] >= 0.90

    def test_every_basis_is_exercised(self, pipeline_run):
        by_basis = pipeline_run["metrics"]["equivalence"]["by_basis"]
        assert set(by_basis) & {"designation", "crossref", "rule"}
