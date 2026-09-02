"""Review queues, decisions and cluster surgery — spec §5, §6.5, §6.6, §0.9."""

import pytest
from sqlalchemy import func, select

from app.models import AuditEvent, Cluster, ClusterMember, Decision, GoldenRecord, ReviewTask


def _pending_review_task(db):
    """A pending task a steward is allowed to close.

    Conflict tasks share the grey band but are reserved for approvers, so
    selecting purely by band would test the wrong thing.
    """
    from app.models import Pair

    return db.execute(
        select(ReviewTask)
        .join(Pair, Pair.id == ReviewTask.pair_id)
        .where(ReviewTask.state == "pending", Pair.verdict == "review")
        .limit(1)
    ).scalar_one_or_none()


@pytest.fixture
def pending_task(pipeline_run, db):
    task = db.execute(
        select(ReviewTask).where(ReviewTask.state == "pending").limit(1)
    ).scalar_one_or_none()
    if task is None:
        pytest.skip("this fixture produced no pending review task")
    return task


class TestQueues:
    def test_all_three_bands_carry_work(self, client, pipeline_run):
        """§6.5: an automation rate only means something if it can be sampled."""
        counts = client.get("/api/queues").json()["counts"]
        assert set(counts) == {"high", "grey", "low"}
        assert all(counts[band] > 0 for band in ("high", "grey", "low")), counts

    def test_each_band_explains_what_it_is_asking_for(self, client, pipeline_run):
        for band, phrase in (
            ("high", "automatic merge"),
            ("low", "automatic refusal"),
        ):
            task = client.get(f"/api/queues?band={band}&limit=1").json()["tasks"][0]
            assert phrase in task["reason"]

    def test_a_band_can_be_selected(self, client, pipeline_run):
        body = client.get("/api/queues?band=grey&limit=5").json()
        assert body["band"] == "grey"
        assert all(task["band"] == "grey" for task in body["tasks"])

    def test_an_unknown_band_is_refused(self, client, pipeline_run):
        assert client.get("/api/queues?band=purple").status_code == 422

    def test_a_card_shows_two_items_side_by_side(self, client, pipeline_run):
        """§6.5: the card is a comparison, not a single record."""
        tasks = client.get("/api/queues?limit=5").json()["tasks"]
        card = next(t for t in tasks if "items" in t)
        assert len(card["items"]) == 2
        for item in card["items"]:
            assert item["description"] and item["cpse"]

    def test_a_card_carries_the_tier_strip_and_confidence(self, client, pipeline_run):
        card = next(t for t in client.get("/api/queues?limit=5").json()["tasks"] if "items" in t)
        assert {"tier0_anchor", "tier1_fuzzy", "tier2_semantic"} <= set(card["tier_scores"])
        assert 0 <= card["confidence"] <= 1

    def test_the_attribute_diff_marks_agreement_and_conflict(self, client, pipeline_run):
        """§6.5: matching attributes plain, conflicting attributes marked."""
        cards = client.get("/api/queues?limit=25").json()["tasks"]
        with_diff = [c for c in cards if c.get("attribute_diff")]
        assert with_diff
        for entry in with_diff[0]["attribute_diff"]:
            assert isinstance(entry["agrees"], bool)
            assert entry["role"] in {"identity_critical", "performance", "cosmetic"}

    def test_a_refused_pair_explains_itself_in_words(self, client, pipeline_run):
        """"Not a duplicate: bore 25 mm vs 30 mm" is the demo moment."""
        cards = client.get("/api/queues?limit=100").json()["tasks"]
        refused = [c for c in cards if c.get("refused_because")]
        if refused:
            assert all(isinstance(r, str) and r for r in refused[0]["refused_because"])

    def test_pagination_is_stable(self, client, pipeline_run):
        first = client.get("/api/queues?limit=2&offset=0").json()["tasks"]
        second = client.get("/api/queues?limit=2&offset=2").json()["tasks"]
        assert {t["task_id"] for t in first}.isdisjoint({t["task_id"] for t in second})


class TestDecisions:
    def test_a_steward_can_reject_a_grey_pair(self, as_steward, db, pipeline_run):
        # A conflict also lands in the grey band but needs an approver, so pick
        # a task whose pair is an ordinary uncertain match.
        task = _pending_review_task(db)
        if task is None:
            pytest.skip("no pending grey task")
        response = as_steward.post(
            "/api/decisions", json={"task_id": task.id, "action": "reject", "note": "different bore"}
        )
        assert response.status_code == 200
        db.expire_all()
        assert db.get(ReviewTask, task.id).state == "done"

    def test_a_decision_is_persisted_with_its_author(self, as_steward, db, pipeline_run):
        task = _pending_review_task(db)
        if task is None:
            pytest.skip("no pending task")
        as_steward.post("/api/decisions", json={"task_id": task.id, "action": "reject"})
        decision = db.execute(
            select(Decision).where(Decision.task_id == task.id)
        ).scalar_one_or_none()
        assert decision is not None and decision.user_id

    def test_deciding_twice_is_refused(self, as_steward, db, pipeline_run):
        task = _pending_review_task(db)
        if task is None:
            pytest.skip("no pending task")
        as_steward.post("/api/decisions", json={"task_id": task.id, "action": "reject"})
        again = as_steward.post("/api/decisions", json={"task_id": task.id, "action": "reject"})
        assert again.status_code == 409

    def test_an_unknown_action_is_refused(self, as_steward, pending_task):
        response = as_steward.post(
            "/api/decisions", json={"task_id": pending_task.id, "action": "obliterate"}
        )
        assert response.status_code == 422

    def test_an_unknown_task_is_404(self, as_steward, pipeline_run):
        assert as_steward.post(
            "/api/decisions", json={"task_id": 999999, "action": "reject"}
        ).status_code == 404

    def test_a_viewer_cannot_decide(self, client, pending_task):
        client.post("/api/auth/login", json={"email": "viewer@min.gov.in", "password": "demo"})
        response = client.post(
            "/api/decisions", json={"task_id": pending_task.id, "action": "reject"}
        )
        assert response.status_code == 403

    def test_a_conflict_task_needs_an_approver(self, as_steward, db, pipeline_run):
        """A specification conflict is a data-quality call, not a similarity one."""
        from app.models import Pair

        task = db.execute(
            select(ReviewTask)
            .join(Pair, Pair.id == ReviewTask.pair_id)
            .where(ReviewTask.state == "pending", Pair.verdict == "conflict")
            .limit(1)
        ).scalar_one_or_none()
        if task is None:
            pytest.skip("no pending conflict task")
        response = as_steward.post(
            "/api/decisions", json={"task_id": task.id, "action": "reject"}
        )
        assert response.status_code == 403
        assert "approver" in response.json()["detail"]

    def test_every_decision_writes_an_audit_event(self, as_steward, db, pipeline_run):
        task = _pending_review_task(db)
        if task is None:
            pytest.skip("no pending task")
        before = db.execute(select(func.count(AuditEvent.id))).scalar()
        as_steward.post("/api/decisions", json={"task_id": task.id, "action": "reject"})
        db.expire_all()
        after = db.execute(select(func.count(AuditEvent.id))).scalar()
        assert after == before + 1


class TestOverturningAutomaticDecisions:
    """A reviewer's "no" has to change the world, not just a flag."""

    def test_rejecting_an_automatic_merge_separates_the_items(
        self, as_steward, client, db, pipeline_run
    ):
        from app.models import Pair

        client.post("/api/auth/login", json={"email": "approver@min.gov.in", "password": "demo"})
        row = db.execute(
            select(ReviewTask, Pair)
            .join(Pair, Pair.id == ReviewTask.pair_id)
            .where(ReviewTask.state == "pending", ReviewTask.band == "high")
            .limit(1)
        ).first()
        if row is None:
            pytest.skip("no pending high-band task")
        task, pair = row

        before = db.execute(
            select(ClusterMember.cluster_id).where(ClusterMember.item_id == pair.item_a)
        ).scalar()
        assert before == db.execute(
            select(ClusterMember.cluster_id).where(ClusterMember.item_id == pair.item_b)
        ).scalar(), "an auto-accepted pair should start out merged"

        response = client.post(
            "/api/decisions", json={"task_id": task.id, "action": "reject", "note": "not the same"}
        )
        assert response.status_code == 200
        db.expire_all()
        after_a = db.execute(
            select(ClusterMember.cluster_id).where(ClusterMember.item_id == pair.item_a)
        ).scalar()
        after_b = db.execute(
            select(ClusterMember.cluster_id).where(ClusterMember.item_id == pair.item_b)
        ).scalar()
        assert after_a != after_b, "rejecting a merge must actually undo it"

    def test_approving_a_low_band_refusal_merges_the_items(self, client, db, pipeline_run):
        from app.models import Pair

        client.post("/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"})
        row = db.execute(
            select(ReviewTask, Pair)
            .join(Pair, Pair.id == ReviewTask.pair_id)
            .where(ReviewTask.state == "pending", ReviewTask.band == "low")
            .limit(1)
        ).first()
        if row is None:
            pytest.skip("no pending low-band task")
        task, pair = row
        response = client.post(
            "/api/decisions", json={"task_id": task.id, "action": "approve"}
        )
        # Either it merges, or it is refused because a code has been issued.
        assert response.status_code in (200, 409)
        if response.status_code == 200:
            db.expire_all()
            assert db.execute(
                select(ClusterMember.cluster_id).where(ClusterMember.item_id == pair.item_a)
            ).scalar() == db.execute(
                select(ClusterMember.cluster_id).where(ClusterMember.item_id == pair.item_b)
            ).scalar()


class TestClusterSurgery:
    """§6.6 — split and merge, each writing an audit event."""

    @pytest.fixture
    def multi_member_cluster(self, pipeline_run, db):
        cluster_id = db.execute(
            select(ClusterMember.cluster_id)
            .group_by(ClusterMember.cluster_id)
            .having(func.count() >= 3)
            .limit(1)
        ).scalar()
        if cluster_id is None:
            # The small test profile does not always produce a three-member
            # cluster on its own; earlier this fixture relied on another
            # file's merge test having made one, which is an order dependency.
            # Build the precondition here instead: move one member across.
            pairs = db.execute(
                select(ClusterMember.cluster_id)
                .group_by(ClusterMember.cluster_id)
                .having(func.count() >= 2)
                .limit(2)
            ).scalars().all()
            assert len(pairs) == 2, "need two clusters to build a three-member one"
            target, donor = pairs
            member = db.execute(
                select(ClusterMember).where(ClusterMember.cluster_id == donor).limit(1)
            ).scalar_one()
            member.cluster_id = target
            db.commit()
            cluster_id = target
        return cluster_id

    def test_splitting_moves_the_member_into_its_own_cluster(
        self, as_steward, db, multi_member_cluster
    ):
        item_id = db.execute(
            select(ClusterMember.item_id).where(ClusterMember.cluster_id == multi_member_cluster)
        ).scalars().first()
        response = as_steward.post(
            f"/api/clusters/{multi_member_cluster}/split", json={"item_id": item_id}
        )
        assert response.status_code == 200
        new_cluster = response.json()["new_cluster_id"]
        db.expire_all()
        assert db.execute(
            select(ClusterMember.cluster_id).where(ClusterMember.item_id == item_id)
        ).scalar() == new_cluster

    def test_a_split_writes_an_audit_event(self, as_steward, db, multi_member_cluster):
        item_id = db.execute(
            select(ClusterMember.item_id).where(ClusterMember.cluster_id == multi_member_cluster)
        ).scalars().first()
        as_steward.post(f"/api/clusters/{multi_member_cluster}/split", json={"item_id": item_id})
        db.expire_all()
        latest = db.execute(
            select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)
        ).scalar_one()
        assert latest.action == "cluster.split"

    def test_splitting_the_last_member_is_refused(self, as_steward, db, pipeline_run):
        singleton = db.execute(
            select(ClusterMember.cluster_id)
            .group_by(ClusterMember.cluster_id)
            .having(func.count() == 1)
            .limit(1)
        ).scalar()
        item_id = db.execute(
            select(ClusterMember.item_id).where(ClusterMember.cluster_id == singleton)
        ).scalar()
        response = as_steward.post(
            f"/api/clusters/{singleton}/split", json={"item_id": item_id}
        )
        assert response.status_code == 422

    def test_merging_moves_every_member_and_drops_the_source(
        self, as_steward, db, pipeline_run
    ):
        clusters = db.execute(
            select(ClusterMember.cluster_id)
            .group_by(ClusterMember.cluster_id)
            .having(func.count() == 1)
            .limit(2)
        ).scalars().all()
        source, target = clusters[0], clusters[1]
        moved = db.execute(
            select(ClusterMember.item_id).where(ClusterMember.cluster_id == source)
        ).scalars().all()

        response = as_steward.post(
            f"/api/clusters/{target}/merge", json={"source_cluster_id": source}
        )
        assert response.status_code == 200
        db.expire_all()
        assert db.get(Cluster, source) is None
        for item_id in moved:
            assert db.execute(
                select(ClusterMember.cluster_id).where(ClusterMember.item_id == item_id)
            ).scalar() == target

    def test_a_merge_writes_an_audit_event(self, as_steward, db, pipeline_run):
        clusters = db.execute(
            select(ClusterMember.cluster_id)
            .group_by(ClusterMember.cluster_id)
            .having(func.count() == 1)
            .limit(2)
        ).scalars().all()
        as_steward.post(
            f"/api/clusters/{clusters[1]}/merge", json={"source_cluster_id": clusters[0]}
        )
        db.expire_all()
        latest = db.execute(
            select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)
        ).scalar_one()
        assert latest.action == "cluster.merge"

    def test_the_golden_record_is_rebuilt_after_a_merge(self, as_steward, db, pipeline_run):
        """The description must never drift out of step with its cluster."""
        clusters = db.execute(
            select(ClusterMember.cluster_id)
            .group_by(ClusterMember.cluster_id)
            .having(func.count() == 1)
            .limit(2)
        ).scalars().all()
        as_steward.post(
            f"/api/clusters/{clusters[1]}/merge", json={"source_cluster_id": clusters[0]}
        )
        db.expire_all()
        golden = db.execute(
            select(GoldenRecord).where(GoldenRecord.cluster_id == clusters[1])
        ).scalar_one()
        assert golden.std_description

    def test_a_cluster_cannot_merge_into_itself(self, as_steward, db, multi_member_cluster):
        response = as_steward.post(
            f"/api/clusters/{multi_member_cluster}/merge",
            json={"source_cluster_id": multi_member_cluster},
        )
        assert response.status_code == 422


class TestImmutabilityOfIssuedCodes:
    def test_a_coded_cluster_cannot_be_split(self, client, db, pipeline_run):
        # One TestClient holds one session, so identity is switched explicitly
        # rather than by combining the as_registrar and as_steward fixtures.
        cluster_id = db.execute(
            select(ClusterMember.cluster_id)
            .group_by(ClusterMember.cluster_id)
            .having(func.count() >= 2)
            .limit(1)
        ).scalar()
        golden = db.execute(
            select(GoldenRecord).where(GoldenRecord.cluster_id == cluster_id)
        ).scalar_one()
        if golden.status == "conflict":
            pytest.skip("that cluster is conflicted and cannot be coded")

        client.post("/api/auth/login", json={"email": "registrar@min.gov.in", "password": "demo"})
        assert client.post(f"/api/cnmc/issue/{golden.id}").status_code == 200

        item_id = db.execute(
            select(ClusterMember.item_id).where(ClusterMember.cluster_id == cluster_id)
        ).scalars().first()
        client.post("/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"})
        response = client.post(f"/api/clusters/{cluster_id}/split", json={"item_id": item_id})
        assert response.status_code == 409
        assert "immutable" in response.json()["detail"].lower()


class TestSeparationOfDuties:
    """§0.9 — the proposer of a golden record may not approve it."""

    def test_editing_then_issuing_as_the_same_user_is_refused(
        self, client, db, pipeline_run
    ):
        golden = db.execute(
            select(GoldenRecord).where(GoldenRecord.status == "draft").limit(1)
        ).scalar_one()
        client.post("/api/auth/login", json={"email": "registrar@min.gov.in", "password": "demo"})
        edit = client.post(
            f"/api/clusters/{golden.cluster_id}/golden",
            json={"std_description": "EDITED BY THE REGISTRAR"},
        )
        assert edit.status_code == 200

        response = client.post(f"/api/cnmc/issue/{golden.id}")
        assert response.status_code == 409
        assert "cannot" in response.json()["detail"].lower()

    def test_a_different_approver_may_issue_it(self, client, db, pipeline_run):
        golden = db.execute(
            select(GoldenRecord).where(GoldenRecord.status == "draft").offset(1).limit(1)
        ).scalar_one()
        client.post("/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"})
        client.post(
            f"/api/clusters/{golden.cluster_id}/golden",
            json={"std_description": "EDITED BY A STEWARD"},
        )
        client.post("/api/auth/login", json={"email": "registrar@min.gov.in", "password": "demo"})
        assert client.post(f"/api/cnmc/issue/{golden.id}").status_code == 200

    def test_an_approved_record_can_no_longer_be_edited(self, client, db, pipeline_run):
        golden = db.execute(
            select(GoldenRecord).where(GoldenRecord.status == "draft").offset(2).limit(1)
        ).scalar_one()
        client.post("/api/auth/login", json={"email": "registrar@min.gov.in", "password": "demo"})
        client.post(f"/api/cnmc/issue/{golden.id}")
        response = client.post(
            f"/api/clusters/{golden.cluster_id}/golden", json={"std_description": "TOO LATE"}
        )
        assert response.status_code == 409


class TestItemDetail:
    """§6.4 / §2B — duplicates and equivalents as two separate blocks."""

    def test_an_item_returns_its_golden_record_and_siblings(self, client, db, pipeline_run):
        item_id = db.execute(
            select(ClusterMember.item_id)
            .group_by(ClusterMember.cluster_id)
            .having(func.count() >= 2)
            .limit(1)
        ).scalar()
        body = client.get(f"/api/items/{item_id}").json()
        assert body["golden"]["std_description"]
        assert body["duplicates"], "a clustered item should list its duplicates"

    def test_duplicates_and_equivalents_are_separate_blocks(self, client, db, pipeline_run):
        from app.models import Relation

        relation = db.execute(select(Relation).limit(1)).scalar_one_or_none()
        if relation is None:
            pytest.skip("no relations")
        body = client.get(f"/api/items/{relation.item_a}").json()
        assert "duplicates" in body and "equivalents" in body
        duplicate_ids = {d["item_id"] for d in body["duplicates"]}
        equivalent_ids = {e["counterpart"]["item_id"] for e in body["equivalents"]}
        assert duplicate_ids.isdisjoint(equivalent_ids)

    def test_an_equivalent_states_which_way_substitution_runs(self, client, db, pipeline_run):
        from app.models import Relation

        relation = db.execute(
            select(Relation).where(Relation.rel_type == "supersedes").limit(1)
        ).scalar_one_or_none()
        if relation is None:
            pytest.skip("no directed relations")
        body = client.get(f"/api/items/{relation.item_a}").json()
        entry = next(
            e for e in body["equivalents"] if e["counterpart"]["item_id"] == relation.item_b
        )
        assert isinstance(entry["substitutes_this"], bool)

    def test_an_unknown_item_is_404(self, client, pipeline_run):
        assert client.get("/api/items/999999").status_code == 404
