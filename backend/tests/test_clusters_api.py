"""GET /api/clusters/{id} — the §2D acceptance criterion, end to end."""

import pytest
from sqlalchemy import func, select

from app.models import Cluster, ClusterMember, GoldenRecord


@pytest.fixture(scope="module")
def multi_member_cluster(pipeline_run):
    """A cluster with several members, so fusion has something to resolve."""
    from app.db import SessionLocal

    with SessionLocal() as db:
        cluster_id = db.execute(
            select(ClusterMember.cluster_id)
            .group_by(ClusterMember.cluster_id)
            .having(func.count() >= 3)
            .limit(1)
        ).scalar()
    assert cluster_id, "the fixture produced no multi-member cluster"
    return cluster_id


class TestClusterDetail:
    def test_unknown_cluster_is_404(self, client, pipeline_run):
        assert client.get("/api/clusters/999999").status_code == 404

    def test_the_golden_record_is_returned_with_its_template(self, client, multi_member_cluster):
        body = client.get(f"/api/clusters/{multi_member_cluster}").json()
        assert body["golden"]["std_description"]
        assert body["golden"]["template"], "the grammar it was rendered from"
        assert body["member_count"] >= 3

    def test_the_golden_description_follows_the_template_not_a_member(
        self, client, multi_member_cluster
    ):
        """§2D replaces "pick the best row" with a deterministic rendering."""
        body = client.get(f"/api/clusters/{multi_member_cluster}").json()
        golden = body["golden"]["std_description"]
        assert ", " in golden, "rendered from the comma-separated grammar"
        assert golden == golden.upper()
        assert "{" not in golden, "no unfilled template slot escaped"

    def test_every_fused_field_carries_provenance(self, client, multi_member_cluster):
        """"Where did this description come from?" gets an exact answer."""
        body = client.get(f"/api/clusters/{multi_member_cluster}").json()
        member_ids = {m["item_id"] for m in body["members"]}
        assert body["provenance"]
        for entry in body["provenance"]:
            assert entry["field"] and entry["rule"]
            assert entry["source_member_id"] in member_ids

    def test_provenance_shows_the_competing_candidates(self, client, multi_member_cluster):
        body = client.get(f"/api/clusters/{multi_member_cluster}").json()
        with_candidates = [p for p in body["provenance"] if p["candidates"]]
        assert with_candidates
        for candidate in with_candidates[0]["candidates"]:
            assert {"value", "member_id", "source"} <= set(candidate)

    def test_a_standardization_delta_is_returned_per_member(
        self, client, multi_member_cluster
    ):
        """§2D: the delta is what a CPSE actually reviews."""
        body = client.get(f"/api/clusters/{multi_member_cluster}").json()
        assert len(body["standardization_delta"]) == body["member_count"]
        for delta in body["standardization_delta"]:
            assert delta["legacy"] and delta["golden"]
            assert isinstance(delta["tokens_dropped"], list)

    def test_members_carry_their_originating_cpse_and_legacy_code(
        self, client, multi_member_cluster
    ):
        """The §6.4 mapping block needs every CPSE's own code for the item."""
        body = client.get(f"/api/clusters/{multi_member_cluster}").json()
        for member in body["members"]:
            assert member["cpse"] and member["legacy_code"] and member["description"]


class TestConflictBlocksIssuance:
    """§2D rule 4, enforced through the API."""

    def test_a_conflicted_cluster_cannot_be_coded(self, as_registrar, pipeline_run):
        from app.db import SessionLocal

        with SessionLocal() as db:
            golden_id = db.execute(
                select(GoldenRecord.id)
                .join(Cluster, Cluster.id == GoldenRecord.cluster_id)
                .where(Cluster.status == "conflict")
                .limit(1)
            ).scalar()
        if golden_id is None:
            pytest.skip("this fixture produced no conflicted clusters")
        response = as_registrar.post(f"/api/cnmc/issue/{golden_id}")
        assert response.status_code == 409
        assert "conflict" in response.json()["detail"].lower()

    def test_a_clean_cluster_can_be_coded(self, as_registrar, pipeline_run):
        from app.db import SessionLocal

        with SessionLocal() as db:
            golden_id = db.execute(
                select(GoldenRecord.id).where(GoldenRecord.status == "draft").limit(1)
            ).scalar()
        assert as_registrar.post(f"/api/cnmc/issue/{golden_id}").status_code == 200
