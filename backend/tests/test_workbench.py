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
    def test_all_three_bands_carry_work(self, as_viewer, pipeline_run):
        """§6.5: an automation rate only means something if it can be sampled."""
        counts = as_viewer.get("/api/queues").json()["counts"]
        assert set(counts) == {"high", "grey", "low"}
        assert all(counts[band] > 0 for band in ("high", "grey", "low")), counts

    def test_each_band_explains_what_it_is_asking_for(self, as_viewer, pipeline_run):
        for band, phrase in (
            ("high", "automatic merge"),
            ("low", "automatic refusal"),
        ):
            task = as_viewer.get(f"/api/queues?band={band}&limit=1").json()["tasks"][0]
            assert phrase in task["reason"]

    def test_a_band_can_be_selected(self, as_viewer, pipeline_run):
        body = as_viewer.get("/api/queues?band=grey&limit=5").json()
        assert body["band"] == "grey"
        assert all(task["band"] == "grey" for task in body["tasks"])

    def test_an_unknown_band_is_refused(self, as_viewer, pipeline_run):
        assert as_viewer.get("/api/queues?band=purple").status_code == 422

    def test_a_card_shows_two_items_side_by_side(self, as_viewer, pipeline_run):
        """§6.5: the card is a comparison, not a single record."""
        tasks = as_viewer.get("/api/queues?limit=5").json()["tasks"]
        card = next(t for t in tasks if "items" in t)
        assert len(card["items"]) == 2
        for item in card["items"]:
            assert item["description"] and item["cpse"]

    def test_a_card_carries_the_tier_strip_and_confidence(self, as_viewer, pipeline_run):
        card = next(t for t in as_viewer.get("/api/queues?limit=5").json()["tasks"] if "items" in t)
        assert {"tier0_anchor", "tier1_fuzzy", "tier2_semantic"} <= set(card["tier_scores"])
        assert 0 <= card["confidence"] <= 1

    def test_the_attribute_diff_marks_agreement_and_conflict(self, as_viewer, pipeline_run):
        """§6.5: matching attributes plain, conflicting attributes marked."""
        cards = as_viewer.get("/api/queues?limit=25").json()["tasks"]
        with_diff = [c for c in cards if c.get("attribute_diff")]
        assert with_diff
        for entry in with_diff[0]["attribute_diff"]:
            assert isinstance(entry["agrees"], bool)
            assert entry["role"] in {"identity_critical", "performance", "cosmetic"}

    def test_a_refused_pair_explains_itself_in_words(self, as_viewer, pipeline_run):
        """ "Not a duplicate: bore 25 mm vs 30 mm" is the demo moment."""
        cards = as_viewer.get("/api/queues?limit=100").json()["tasks"]
        refused = [c for c in cards if c.get("refused_because")]
        if refused:
            assert all(isinstance(r, str) and r for r in refused[0]["refused_because"])

    def test_pagination_is_stable(self, as_viewer, pipeline_run):
        first = as_viewer.get("/api/queues?limit=2&offset=0").json()["tasks"]
        second = as_viewer.get("/api/queues?limit=2&offset=2").json()["tasks"]
        assert {t["task_id"] for t in first}.isdisjoint({t["task_id"] for t in second})


class TestDecisions:
    def test_a_steward_can_reject_a_grey_pair(self, as_steward, db, pipeline_run):
        # A conflict also lands in the grey band but needs an approver, so pick
        # a task whose pair is an ordinary uncertain match.
        task = _pending_review_task(db)
        if task is None:
            pytest.skip("no pending grey task")
        response = as_steward.post(
            "/api/decisions",
            json={"task_id": task.id, "action": "reject", "note": "different bore"},
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
        assert (
            as_steward.post(
                "/api/decisions", json={"task_id": 999999, "action": "reject"}
            ).status_code
            == 404
        )

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
        response = as_steward.post("/api/decisions", json={"task_id": task.id, "action": "reject"})
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
        assert (
            before
            == db.execute(
                select(ClusterMember.cluster_id).where(ClusterMember.item_id == pair.item_b)
            ).scalar()
        ), "an auto-accepted pair should start out merged"

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
        response = client.post("/api/decisions", json={"task_id": task.id, "action": "approve"})
        # Either it merges, or it is refused because a code has been issued.
        assert response.status_code in (200, 409)
        if response.status_code == 200:
            db.expire_all()
            assert (
                db.execute(
                    select(ClusterMember.cluster_id).where(ClusterMember.item_id == pair.item_a)
                ).scalar()
                == db.execute(
                    select(ClusterMember.cluster_id).where(ClusterMember.item_id == pair.item_b)
                ).scalar()
            )


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
            pairs = (
                db.execute(
                    select(ClusterMember.cluster_id)
                    .group_by(ClusterMember.cluster_id)
                    .having(func.count() >= 2)
                    .limit(2)
                )
                .scalars()
                .all()
            )
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
        item_id = (
            db.execute(
                select(ClusterMember.item_id).where(
                    ClusterMember.cluster_id == multi_member_cluster
                )
            )
            .scalars()
            .first()
        )
        response = as_steward.post(
            f"/api/clusters/{multi_member_cluster}/split", json={"item_id": item_id}
        )
        assert response.status_code == 200
        new_cluster = response.json()["new_cluster_id"]
        db.expire_all()
        assert (
            db.execute(
                select(ClusterMember.cluster_id).where(ClusterMember.item_id == item_id)
            ).scalar()
            == new_cluster
        )

    def test_a_split_writes_an_audit_event(self, as_steward, db, multi_member_cluster):
        item_id = (
            db.execute(
                select(ClusterMember.item_id).where(
                    ClusterMember.cluster_id == multi_member_cluster
                )
            )
            .scalars()
            .first()
        )
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
        response = as_steward.post(f"/api/clusters/{singleton}/split", json={"item_id": item_id})
        assert response.status_code == 422

    def test_merging_moves_every_member_and_drops_the_source(self, as_steward, db, pipeline_run):
        clusters = (
            db.execute(
                select(ClusterMember.cluster_id)
                .group_by(ClusterMember.cluster_id)
                .having(func.count() == 1)
                .limit(2)
            )
            .scalars()
            .all()
        )
        source, target = clusters[0], clusters[1]
        moved = (
            db.execute(select(ClusterMember.item_id).where(ClusterMember.cluster_id == source))
            .scalars()
            .all()
        )

        response = as_steward.post(
            f"/api/clusters/{target}/merge", json={"source_cluster_id": source}
        )
        assert response.status_code == 200
        db.expire_all()
        assert db.get(Cluster, source) is None
        for item_id in moved:
            assert (
                db.execute(
                    select(ClusterMember.cluster_id).where(ClusterMember.item_id == item_id)
                ).scalar()
                == target
            )

    def test_a_merge_writes_an_audit_event(self, as_steward, db, pipeline_run):
        clusters = (
            db.execute(
                select(ClusterMember.cluster_id)
                .group_by(ClusterMember.cluster_id)
                .having(func.count() == 1)
                .limit(2)
            )
            .scalars()
            .all()
        )
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
        clusters = (
            db.execute(
                select(ClusterMember.cluster_id)
                .group_by(ClusterMember.cluster_id)
                .having(func.count() == 1)
                .limit(2)
            )
            .scalars()
            .all()
        )
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

        item_id = (
            db.execute(select(ClusterMember.item_id).where(ClusterMember.cluster_id == cluster_id))
            .scalars()
            .first()
        )
        client.post("/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"})
        response = client.post(f"/api/clusters/{cluster_id}/split", json={"item_id": item_id})
        assert response.status_code == 409
        assert "immutable" in response.json()["detail"].lower()


class TestSeparationOfDuties:
    """§0.9 — the proposer of a golden record may not approve it."""

    def test_editing_then_issuing_as_the_same_user_is_refused(self, client, db, pipeline_run):
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

    def test_an_item_returns_its_golden_record_and_siblings(self, as_viewer, db, pipeline_run):
        item_id = db.execute(
            select(ClusterMember.item_id)
            .group_by(ClusterMember.cluster_id)
            .having(func.count() >= 2)
            .limit(1)
        ).scalar()
        body = as_viewer.get(f"/api/items/{item_id}").json()
        assert body["golden"]["std_description"]
        assert body["duplicates"], "a clustered item should list its duplicates"

    def test_duplicates_and_equivalents_are_separate_blocks(self, as_viewer, db, pipeline_run):
        from app.models import Relation

        relation = db.execute(select(Relation).limit(1)).scalar_one_or_none()
        if relation is None:
            pytest.skip("no relations")
        body = as_viewer.get(f"/api/items/{relation.item_a}").json()
        assert "duplicates" in body and "equivalents" in body
        duplicate_ids = {d["item_id"] for d in body["duplicates"]}
        equivalent_ids = {e["counterpart"]["item_id"] for e in body["equivalents"]}
        assert duplicate_ids.isdisjoint(equivalent_ids)

    def test_an_equivalent_states_which_way_substitution_runs(self, as_viewer, db, pipeline_run):
        from app.models import Relation

        relation = db.execute(
            select(Relation).where(Relation.rel_type == "supersedes").limit(1)
        ).scalar_one_or_none()
        if relation is None:
            pytest.skip("no directed relations")
        body = as_viewer.get(f"/api/items/{relation.item_a}").json()
        entry = next(
            e for e in body["equivalents"] if e["counterpart"]["item_id"] == relation.item_b
        )
        assert isinstance(entry["substitutes_this"], bool)

    def test_an_unknown_item_is_404(self, as_viewer, pipeline_run):
        assert as_viewer.get("/api/items/999999").status_code == 404


class TestQueueFilters:
    """Queues are worked by family; the filters say what exists and keep it."""

    def test_facets_list_classes_and_cpses_present_in_the_band(self, as_viewer, pipeline_run):
        body = as_viewer.get("/api/queues?band=grey").json()
        assert body["facets"]["classes"] and body["facets"]["cpses"]
        assert sum(f["count"] for f in body["facets"]["classes"]) == body["total"]

    def test_a_class_filter_keeps_only_that_class(self, as_viewer, pipeline_run):
        facets = as_viewer.get("/api/queues?band=grey").json()["facets"]
        code = facets["classes"][0]["code"]
        body = as_viewer.get(f"/api/queues?band=grey&class={code}&limit=50").json()
        assert body["total"] == facets["classes"][0]["count"]
        assert body["filters"]["class"] == code
        for card in body["tasks"]:
            assert code in {item["class_code"] for item in card["items"]}

    def test_a_cpse_filter_keeps_pairs_touching_that_cpse(self, as_viewer, pipeline_run):
        facets = as_viewer.get("/api/queues?band=grey").json()["facets"]
        cpse = facets["cpses"][-1]
        body = as_viewer.get(f"/api/queues?band=grey&cpse={cpse['id']}&limit=50").json()
        assert body["total"] == cpse["count"]
        for card in body["tasks"]:
            assert cpse["code"] in {item["cpse"] for item in card["items"]}

    def test_mine_keeps_the_callers_role(self, as_steward, pipeline_run):
        body = as_steward.get("/api/queues?band=grey&mine=true").json()
        assert body["filters"]["mine"] is True
        assert body["total"] <= as_steward.get("/api/queues?band=grey").json()["total"]

    def test_every_card_says_why_it_is_here(self, as_viewer, pipeline_run):
        for band in ("high", "grey", "low"):
            body = as_viewer.get(f"/api/queues?band={band}&limit=3").json()
            for card in body["tasks"]:
                assert card["why"] and card["why"].endswith((".", ")"))


class TestBulkDecisions:
    def test_a_page_of_the_high_band_closes_with_one_reason(self, as_steward, db, pipeline_run):
        page = as_steward.get("/api/queues?band=high&limit=5").json()["tasks"]
        ids = [card["task_id"] for card in page]
        if not ids:
            pytest.skip("no pending high-band task")
        response = as_steward.post(
            "/api/decisions/bulk",
            json={"task_ids": ids, "action": "approve", "note": "policy confirmation"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["count"] == len(ids) and body["skipped"] == []
        db.expire_all()
        assert all(db.get(ReviewTask, i).state == "done" for i in ids)
        # One audit event per row, each with the shared reason.
        events = (
            db.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "decision.approve",
                    AuditEvent.entity.in_([f"review_task:{i}" for i in ids]),
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == len(ids)
        assert all('"policy confirmation"' in e.payload_json for e in events)

    def test_a_task_that_cannot_close_is_reported_not_fatal(self, as_steward, db, pipeline_run):
        task = _pending_review_task(db)
        if task is None:
            pytest.skip("no pending task")
        as_steward.post("/api/decisions", json={"task_id": task.id, "action": "reject"})
        response = as_steward.post(
            "/api/decisions/bulk", json={"task_ids": [task.id, 10**9], "action": "reject"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 0
        assert {row["task_id"] for row in body["skipped"]} == {task.id, 10**9}

    def test_only_approve_and_reject_in_bulk(self, as_steward, pipeline_run):
        response = as_steward.post("/api/decisions/bulk", json={"task_ids": [1], "action": "split"})
        assert response.status_code == 422

    def test_a_viewer_cannot_bulk_decide(self, as_viewer, pipeline_run):
        response = as_viewer.post(
            "/api/decisions/bulk", json={"task_ids": [1], "action": "approve"}
        )
        assert response.status_code == 403


class TestUndo:
    """Everyone mis-clicks. Within the window the world goes back as it was."""

    def _high_task(self, db):
        from app.models import Pair

        return db.execute(
            select(ReviewTask, Pair)
            .join(Pair, Pair.id == ReviewTask.pair_id)
            .where(ReviewTask.state == "pending", ReviewTask.band == "high")
            .limit(1)
        ).first()

    def test_a_reject_is_taken_back_and_the_pair_rejoined(self, as_steward, db, pipeline_run):
        from app.models import PairLabel

        row = self._high_task(db)
        if row is None:
            pytest.skip("no pending high-band task")
        task, pair = row
        verdict_before = pair.verdict
        cluster_before = db.execute(
            select(ClusterMember.cluster_id).where(ClusterMember.item_id == pair.item_a)
        ).scalar()
        decided = as_steward.post(
            "/api/decisions", json={"task_id": task.id, "action": "reject", "seconds": 12.5}
        ).json()
        assert decided["undo_until"]
        db.expire_all()
        assert (
            db.execute(
                select(ClusterMember.cluster_id).where(ClusterMember.item_id == pair.item_b)
            ).scalar()
            != cluster_before
        ), "the reject should have split the pair"

        response = as_steward.post(f"/api/decisions/{decided['decision_id']}/undo")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["restored"]["label_withdrawn"] is True
        db.expire_all()
        assert db.get(ReviewTask, task.id).state == "pending"
        assert db.get(Decision, decided["decision_id"]) is None
        assert db.get(pair.__class__, pair.id).verdict == verdict_before
        # Both items are back in one cluster.
        a, b = (
            db.execute(
                select(ClusterMember.cluster_id).where(ClusterMember.item_id == item)
            ).scalar()
            for item in (pair.item_a, pair.item_b)
        )
        assert a == b
        # No label remains for the model to learn from.
        lo, hi = sorted((pair.item_a, pair.item_b))
        assert (
            db.execute(
                select(func.count(PairLabel.id)).where(
                    PairLabel.item_a == lo, PairLabel.item_b == hi, PairLabel.source == "reviewer"
                )
            ).scalar()
            == 0
        )
        # The chain remembers both.
        undo = (
            db.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "decision.undo",
                    AuditEvent.entity == f"review_task:{task.id}",
                )
            )
            .scalars()
            .first()
        )
        assert undo is not None and '"after_seconds"' in undo.payload_json

    def test_an_approve_that_merged_is_unmerged(self, client, db, pipeline_run):
        from app.models import Pair

        client.post("/api/auth/login", json={"email": "approver@min.gov.in", "password": "demo"})
        row = db.execute(
            select(ReviewTask, Pair)
            .join(Pair, Pair.id == ReviewTask.pair_id)
            .where(ReviewTask.state == "pending", ReviewTask.band == "low")
            .limit(1)
        ).first()
        if row is None:
            pytest.skip("no pending low-band task")
        task, pair = row
        decided = client.post("/api/decisions", json={"task_id": task.id, "action": "approve"})
        assert decided.status_code == 200, decided.text
        db.expire_all()
        merged = [
            db.execute(
                select(ClusterMember.cluster_id).where(ClusterMember.item_id == item)
            ).scalar()
            for item in (pair.item_a, pair.item_b)
        ]
        assert merged[0] == merged[1]

        response = client.post(f"/api/decisions/{decided.json()['decision_id']}/undo")
        assert response.status_code == 200, response.text
        assert "unmerged_into" in response.json()["restored"]
        db.expire_all()
        apart = [
            db.execute(
                select(ClusterMember.cluster_id).where(ClusterMember.item_id == item)
            ).scalar()
            for item in (pair.item_a, pair.item_b)
        ]
        assert apart[0] != apart[1]
        assert db.get(ReviewTask, task.id).state == "pending"

    def test_only_the_author_or_an_admin_may_undo(self, client, db, pipeline_run):
        task = _pending_review_task(db)
        if task is None:
            pytest.skip("no pending task")
        client.post("/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"})
        decided = client.post(
            "/api/decisions", json={"task_id": task.id, "action": "reject"}
        ).json()
        client.post("/api/auth/login", json={"email": "approver@min.gov.in", "password": "demo"})
        assert client.post(f"/api/decisions/{decided['decision_id']}/undo").status_code == 403

    def test_the_window_closes(self, as_steward, db, pipeline_run, monkeypatch):
        from datetime import UTC, datetime, timedelta

        task = _pending_review_task(db)
        if task is None:
            pytest.skip("no pending task")
        decided = as_steward.post("/api/decisions", json={"task_id": task.id, "action": "reject"})
        decision = db.get(Decision, decided.json()["decision_id"])
        decision.ts = datetime.now(UTC) - timedelta(minutes=6)
        db.commit()
        response = as_steward.post(f"/api/decisions/{decision.id}/undo")
        assert response.status_code == 409
        assert "window closed" in response.json()["detail"]

    def test_undoing_twice_is_a_404(self, as_steward, db, pipeline_run):
        task = _pending_review_task(db)
        if task is None:
            pytest.skip("no pending task")
        decided = as_steward.post("/api/decisions", json={"task_id": task.id, "action": "reject"})
        did = decided.json()["decision_id"]
        assert as_steward.post(f"/api/decisions/{did}/undo").status_code == 200
        assert as_steward.post(f"/api/decisions/{did}/undo").status_code == 404


class TestCompareAnyTwoRows:
    def test_two_rows_are_scored_like_the_pipeline_scores_them(self, as_viewer, db, pipeline_run):
        from app.models import Pair

        pair = db.execute(select(Pair).where(Pair.verdict == "distinct").limit(1)).scalar_one()
        body = as_viewer.get(f"/api/compare?a={pair.item_a}&b={pair.item_b}").json()
        assert body["verdict"] == pair.verdict
        assert body["pipeline"] == {
            "paired": True,
            "verdict": pair.verdict,
            "pair_id": pair.id,
            "same_cluster": False,
        }
        assert body["why"] and body["attribute_diff"] and body["tier_scores"]
        assert [i["item_id"] for i in body["items"]] == [pair.item_a, pair.item_b]

    def test_rows_the_pipeline_never_paired_still_compare(self, as_viewer, db, pipeline_run):
        from app.models import Item

        ids = db.execute(select(Item.id).order_by(Item.id).limit(2)).scalars().all()
        body = as_viewer.get(f"/api/compare?a={ids[0]}&b={ids[1]}").json()
        assert body["verdict"] in ("duplicate", "distinct", "conflict", "review")
        assert "Nothing was stored" in body["note"]

    def test_the_same_row_twice_is_refused(self, as_viewer, pipeline_run):
        assert as_viewer.get("/api/compare?a=1&b=1").status_code == 422
        assert as_viewer.get("/api/compare?a=1&b=999999999").status_code == 404


class TestAttachments:
    """The datasheet an approver asks for first: stored by hash, served checked, voided not deleted."""

    def _cluster(self, db):
        return db.execute(select(GoldenRecord.cluster_id).limit(1)).scalar_one()

    def test_attach_list_download_and_void(self, client, db, pipeline_run):
        from app.models import AuditEvent

        client.post("/api/auth/login", json={"email": "approver@min.gov.in", "password": "demo"})
        cid = self._cluster(db)
        pdf = b"%PDF-1.4\n%synthetic datasheet\n"
        up = client.post(
            f"/api/clusters/{cid}/attachments",
            data={"kind": "datasheet", "note": "from the OEM site"},
            files={"file": ("6205-datasheet.pdf", pdf, "application/pdf")},
        )
        assert up.status_code == 200, up.text
        listed = up.json()["attachments"]
        assert listed and listed[-1]["filename"] == "6205-datasheet.pdf"
        assert listed[-1]["uploaded_by"] and listed[-1]["kind"] == "datasheet"
        att = listed[-1]

        again = client.get(f"/api/clusters/{cid}/attachments").json()
        assert any(a["id"] == att["id"] for a in again["attachments"])

        got = client.get(f"/api/clusters/attachments/{att['id']}/file")
        assert got.status_code == 200 and got.content == pdf
        assert got.headers["content-type"].startswith("application/pdf")

        # The same bytes attached twice are one file on disk, two rows.
        twice = client.post(
            f"/api/clusters/{cid}/attachments",
            files={"file": ("copy.pdf", pdf, "application/pdf")},
        ).json()
        assert sum(1 for a in twice["attachments"] if a["sha256"] == att["sha256"]) == 2

        gone = client.delete(f"/api/clusters/attachments/{att['id']}?reason=wrong%20revision")
        assert gone.status_code == 200
        assert all(
            a["id"] != att["id"]
            for a in client.get(f"/api/clusters/{cid}/attachments").json()["attachments"]
        )
        assert client.get(f"/api/clusters/attachments/{att['id']}/file").status_code == 404
        actions = {
            e.action
            for e in db.execute(
                select(AuditEvent).where(
                    AuditEvent.entity == f"golden:{att and again['golden_id']}"
                )
            ).scalars()
        }
        assert {"attachment.add", "attachment.void"} <= actions

    def test_only_documents_and_pictures_and_only_from_those_who_may(
        self, client, as_viewer, db, pipeline_run
    ):
        cid = self._cluster(db)
        assert (
            as_viewer.post(
                f"/api/clusters/{cid}/attachments",
                files={"file": ("x.pdf", b"%PDF", "application/pdf")},
            ).status_code
            == 403
        )
        client.post("/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"})
        refused = client.post(
            f"/api/clusters/{cid}/attachments",
            files={"file": ("run.exe", b"MZ", "application/octet-stream")},
        )
        assert refused.status_code == 422
