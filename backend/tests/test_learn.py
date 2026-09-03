"""Learning from the Workbench: labels come from decisions, the model trains
on them, never decides, orders the queue by what it does not know, and is
measured against the held-out split beside the pipeline's own score."""

import json

import pytest
from sqlalchemy import delete, select

from app import learn
from app.models import Item, Pair, PairLabel, TruthGroup


class TestFeatures:
    def test_counts_by_role_and_result(self):
        evidence = {
            "route": "tiered",
            "attributes": {
                "agreement": 0.75,
                "per_attr": [
                    {"attr": "bore_mm", "role": "identity_critical", "result": "match"},
                    {"attr": "seal_type", "role": "identity_critical", "result": "unknown"},
                    {"attr": "load_rating_kg", "role": "performance", "result": "in_band"},
                    {"attr": "brand", "role": "cosmetic", "result": "match"},
                ],
            },
        }
        x = learn.features(
            {"tier0_anchor": 0.9, "tier0_key": "mpn", "tier1_fuzzy": 0.8}, evidence, None
        )
        row = dict(zip(learn.FEATURES, x, strict=False))
        assert row["has_anchor"] == 1 and row["tier1_fuzzy"] == 0.8
        assert row["identity_match"] == 1 and row["identity_unknown"] == 1
        assert row["performance_in_band"] == 1 and row["cosmetic_match"] == 1
        assert row["compared"] == 4 and row["route_tiered"] == 1 and row["vetoed"] == 0
        assert row["attribute_agreement"] == 0.75

    def test_a_pair_without_evidence_has_no_row(self, db, pipeline_run):
        pair = db.execute(select(Pair).where(Pair.evidence_json == "{}")).scalars().first()
        if pair is not None:
            assert learn.pair_features(pair) is None


class TestSimulatedLabels:
    def test_labels_come_from_the_tuning_split_only(self, db, pipeline_run):
        result = learn.simulate_labels(db, 120)
        assert result["added"] >= 40 and result["positives"] > 0 and result["negatives"] > 0
        splits = dict(
            db.execute(
                select(Item.id, TruthGroup.split).join(
                    TruthGroup, TruthGroup.raw_item_id == Item.raw_item_id
                )
            ).all()
        )
        for label in db.execute(
            select(PairLabel).where(PairLabel.source == learn.SOURCE_SIMULATED)
        ).scalars():
            pair = db.get(Pair, label.pair_id)
            assert splits[pair.item_a] == "tuning" and splits[pair.item_b] == "tuning"


class TestTraining:
    def test_too_few_labels_is_refused_plainly(self, db, pipeline_run, monkeypatch):
        monkeypatch.setattr(learn, "MIN_LABELS", 10**6)
        with pytest.raises(learn.NotEnoughLabels) as excinfo:
            learn.train(db)
        assert "Workbench" in str(excinfo.value)

    def test_the_model_is_readable_weights_and_beats_chance(self, db, pipeline_run):
        if sum(learn.label_counts(db).values()) < learn.MIN_LABELS:
            learn.simulate_labels(db, 200)
        model = learn.train(db)
        saved = json.loads(learn.model_path().read_text())
        assert saved["features"] == list(learn.FEATURES)
        assert len(saved["coef"]) == len(learn.FEATURES)
        assert model.cv["auc"] is None or model.cv["auc"] > 0.7
        assert model.holdout["pairs"] > 0
        assert model.holdout["model_auc"] > 0.7
        assert 0.0 <= model.probability([0.0] * len(learn.FEATURES)) <= 1.0

    def test_the_opinion_never_decides(self, db, pipeline_run):
        if learn.load_model() is None:
            learn.simulate_labels(db, 200)
            learn.train(db)
        pair = (
            db.execute(select(Pair).where(Pair.evidence_json != "{}", Pair.band == "grey"))
            .scalars()
            .first()
        )
        opinion = learn.score(pair)
        assert opinion and 0.0 <= opinion["probability"] <= 1.0
        assert opinion["leans"] in ("duplicate", "distinct")
        assert learn.status(db)["decides"] is False


class TestEndpoints:
    def test_status_needs_a_session_and_training_needs_a_registrar(
        self, client, as_steward, pipeline_run
    ):
        assert client.get("/api/learn/status").status_code in (200, 401)
        assert as_steward.post("/api/learn/train").status_code == 403

    def test_registrar_trains_and_reads_the_corpus(self, as_registrar, pipeline_run):
        as_registrar.post("/api/learn/simulate", json={"n": 100})
        response = as_registrar.post("/api/learn/train")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["trained"] and body["model"]["n_labels"] >= learn.MIN_LABELS
        assert set(body["model"]["weights"]) == set(learn.FEATURES)

        corpus = as_registrar.get("/api/learn/corpus")
        assert corpus.status_code == 200
        lines = [json.loads(line) for line in corpus.text.splitlines() if line]
        assert lines and {"pair_id", "label", "source", "a", "b"} <= set(lines[0])
        assert lines[0]["label"] in ("duplicate", "distinct")

    def test_the_queue_can_be_ordered_by_uncertainty(self, as_registrar, pipeline_run):
        if learn.load_model() is None:
            as_registrar.post("/api/learn/simulate", json={"n": 100})
            as_registrar.post("/api/learn/train")
        body = as_registrar.get("/api/queues?band=grey&order=uncertainty&limit=10").json()
        assert body["order"] == "uncertainty" and body["model_available"] is True
        opinions = [t["learned"]["uncertainty"] for t in body["tasks"] if t.get("learned")]
        assert opinions == sorted(opinions, reverse=True)
        assert as_registrar.get("/api/queues?band=grey&order=sideways").status_code == 422

    def test_a_decision_is_also_a_label(self, as_registrar, db, pipeline_run):
        # A pair whose items sit in different clusters: rejecting it records the
        # answer without moving anything, so the rest of the suite is unaffected.
        queue = as_registrar.get("/api/queues?band=grey&limit=50").json()
        task = next(
            t
            for t in queue["tasks"]
            if t.get("pair_id") and t["items"][0]["cluster_id"] != t["items"][1]["cluster_id"]
        )
        before = (
            db.execute(select(PairLabel).where(PairLabel.pair_id == task["pair_id"]))
            .scalars()
            .all()
        )
        response = as_registrar.post(
            "/api/decisions", json={"task_id": task["task_id"], "action": "reject"}
        )
        assert response.status_code == 200, response.text
        db.expire_all()
        after = (
            db.execute(select(PairLabel).where(PairLabel.pair_id == task["pair_id"]))
            .scalars()
            .all()
        )
        assert len(after) == len(before) + 1
        assert after[-1].source == learn.SOURCE_REVIEWER and after[-1].label is False
        assert (after[-1].item_a, after[-1].item_b) == tuple(
            sorted((task["items"][0]["item_id"], task["items"][1]["item_id"]))
        )
        # Leave the derived layer as the pipeline built it: later suites count
        # grey pairs against grey tasks. The label and the audit event stay.
        from app.models import Decision, ReviewTask

        pair = db.get(Pair, task["pair_id"])
        pair.verdict = task["verdict"]
        review_task = db.get(ReviewTask, task["task_id"])
        review_task.state = "pending"
        db.execute(delete(Decision).where(Decision.task_id == task["task_id"]))
        db.commit()
