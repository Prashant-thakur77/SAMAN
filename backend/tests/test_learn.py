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
        row = learn.features(
            {"tier0_anchor": 0.9, "tier0_key": "mpn", "tier1_fuzzy": 0.8}, evidence, None
        )
        assert set(row) == set(learn.FEATURES) and len(learn.FEATURES) <= 24
        assert row["has_anchor"] == 1 and row["tier1_fuzzy"] == 0.8
        assert row["identity_match"] == 1 and row["identity_unknown"] == 1
        assert row["performance_in_band"] == 1 and row["cosmetic_match"] == 1
        assert row["compared"] == 4 and row["route_tiered"] == 1 and row["vetoed"] == 0
        assert row["attribute_agreement"] == 0.75
        # Two identity attributes seen, one compared.
        assert row["identity_coverage"] == 0.5
        assert row["brand_equal"] == 1 and row["brand_differs"] == 0
        # Without the items' facts the item-derived features are unknown, not zero.
        assert row["same_cpse"] is None and row["token_jaccard"] is None

    def test_item_facts_feed_the_pair_features(self):
        a = learn.ItemFacts(
            1, "bearing", "6205ZZ", None, frozenset("BEARING 6205 ZZ SKF".split()), 19
        )
        b = learn.ItemFacts(
            2, "bearing", "6206ZZ", None, frozenset("BEARING 6206 ZZ SKF".split()), 19
        )
        row = learn.features({}, {"route": "tiered"}, None, a, b)
        assert row["same_cpse"] == 0 and row["mpn_differs"] == 1
        assert row["token_jaccard"] == pytest.approx(3 / 5) and row["length_ratio"] == 1.0
        same = learn.features({}, {"route": "tiered"}, None, a, a)
        assert same["same_cpse"] == 1 and same["mpn_differs"] == 0 and same["token_jaccard"] == 1

    def test_facts_load_in_one_batch(self, db, pipeline_run):
        pair = db.execute(select(Pair).where(Pair.evidence_json != "{}")).scalars().first()
        facts = learn.item_facts(db, (pair.item_a, pair.item_b))
        assert set(facts) == {pair.item_a, pair.item_b}
        row = learn.pair_features(pair, facts)
        assert row is not None and row["same_cpse"] in (0.0, 1.0)

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
        # Per class, the same three numbers the README quotes overall.
        per_class = model.holdout["per_class"]
        assert per_class and {"class_code", "model_auc", "precision", "recall"} <= set(per_class[0])
        assert sum(row["pairs"] for row in per_class) == model.holdout["pairs"]
        # Manual training is an attempt like any other, and is written down.
        last = learn.history(1)[0]
        assert last["trigger"] == "manual" and last["promoted"] is True
        assert last["weights"] == model.weights()

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
        # The uncertain part of the page is in order; a random fifth follows it,
        # marked as such, so the model's blind spots are sampled too.
        uncertain = [t for t in body["tasks"] if t["picked_for"] == "uncertain"]
        random_picks = [t for t in body["tasks"] if t["picked_for"] == "random"]
        opinions = [t["learned"]["uncertainty"] for t in uncertain if t.get("learned")]
        assert opinions == sorted(opinions, reverse=True)
        assert body["mix"] == {
            "uncertain": len(uncertain),
            "random": len(random_picks),
            "share": 0.2,
        }
        assert len(random_picks) == 2 and len(uncertain) == 8
        # Reloading the same page shows the same cards.
        again = as_registrar.get("/api/queues?band=grey&order=uncertainty&limit=10").json()
        assert [t["task_id"] for t in again["tasks"]] == [t["task_id"] for t in body["tasks"]]
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


# --------------------------------------------------------------------------
# Old models, the champion/challenger loop, and threshold suggestions
# --------------------------------------------------------------------------


OLD_FEATURES = list(learn.FEATURES[:15])


def _write_model(features: list[str], **overrides) -> None:
    n = len(features)
    raw = {
        "features": features,
        "mean": [0.0] * n,
        "scale": [1.0] * n,
        "coef": [0.1] * n,
        "intercept": 0.0,
        "trained_at": "2026-09-03T00:00:00+00:00",
        "n_labels": 400,
        "labels": {"simulated": 400},
        "cv": {"folds": 5, "auc": 0.99, "precision": 0.95, "recall": 0.95},
        "holdout": {"pairs": 1, "model_auc": 0.9},
        "last_label_id": 0,
    }
    raw.update(overrides)
    learn.model_path().parent.mkdir(parents=True, exist_ok=True)
    learn.model_path().write_text(json.dumps(raw))
    learn._cache = None


class TestOldModels:
    def test_a_fifteen_feature_model_still_loads_and_scores(self, db, pipeline_run):
        _write_model(OLD_FEATURES)
        try:
            model = learn.load_model()
            assert model is not None and model.features == OLD_FEATURES
            pair = db.execute(select(Pair).where(Pair.evidence_json != "{}")).scalars().first()
            opinion = learn.score(pair, model, db=db)
            assert opinion and 0.0 <= opinion["probability"] <= 1.0
            # The richer row is matched by name; the extra features are ignored.
            row = learn.pair_features(pair, learn.item_facts(db, (pair.item_a, pair.item_b)))
            assert model.probability(row) == pytest.approx(
                model.probability([row[name] for name in OLD_FEATURES])
            )
            assert learn.status(db)["trained"] is True
        finally:
            learn.forget_model()

    def test_an_unknown_or_broken_model_is_refused_with_a_retrain_note(self, db, pipeline_run):
        try:
            _write_model(["tier0_anchor", "something_this_version_never_computes"])
            assert learn.load_model() is None
            status = learn.status(db)
            assert status["trained"] is False and "retrain" in status["note"].lower()
            _write_model(OLD_FEATURES, coef=[0.1] * 3)
            assert learn.load_model() is None and "retrain" in learn.status(db)["note"].lower()
            learn.model_path().write_text("not json")
            learn._cache = None
            assert learn.load_model() is None and "retrain" in learn.status(db)["note"].lower()
        finally:
            learn.forget_model()


def _ensure_champion(db) -> learn.Model:
    if sum(learn.label_counts(db).values()) < learn.MIN_LABELS:
        learn.simulate_labels(db, 200)
    model = learn.load_model()
    return model if model is not None else learn.train(db)


def _reject_a_grey_pair(as_registrar, db) -> dict:
    """One reviewer decision, then the derived layer put back so later suites
    see what the pipeline built. The label and the audit event stay."""
    from app.models import Decision, ReviewTask

    queue = as_registrar.get("/api/queues?band=grey&limit=50").json()
    task = next(
        t
        for t in queue["tasks"]
        if t.get("pair_id") and t["items"][0]["cluster_id"] != t["items"][1]["cluster_id"]
    )
    response = as_registrar.post(
        "/api/decisions", json={"task_id": task["task_id"], "action": "reject"}
    )
    assert response.status_code == 200, response.text
    db.expire_all()
    pair = db.get(Pair, task["pair_id"])
    pair.verdict = task["verdict"]
    review_task = db.get(ReviewTask, task["task_id"])
    review_task.state = "pending"
    db.execute(delete(Decision).where(Decision.task_id == task["task_id"]))
    db.commit()
    return task


class TestAutoRetrain:
    @pytest.fixture(autouse=True)
    def _loop_on(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "saman_auto_retrain", True)
        monkeypatch.setattr(get_settings(), "saman_retrain_every", 2)
        learn.forget_history()
        yield
        learn.wait_for_retrain()
        learn.forget_history()

    def test_reviewer_decisions_trigger_a_retrain_that_is_recorded(
        self, as_registrar, db, pipeline_run
    ):
        from app.models import AuditEvent

        champion = _ensure_champion(db)
        before = learn.auto_retrain_status(db)
        assert before["enabled"] and before["every"] == 2 and before["due"] is False

        _reject_a_grey_pair(as_registrar, db)
        assert learn.auto_retrain_status(db)["labels_since"] == 1
        _reject_a_grey_pair(as_registrar, db)
        learn.wait_for_retrain()

        attempts = learn.history()
        assert attempts and attempts[0]["trigger"] == "auto"
        last = attempts[0]
        assert last["n_labels"] >= champion.n_labels
        # Labels are counted per pair (the latest answer wins), so one is enough.
        assert last["labels"].get(learn.SOURCE_REVIEWER, 0) >= 1
        assert isinstance(last["promoted"], bool) and last["reason"]
        assert last["holdout_auc"] is not None and last["champion_auc"] is not None
        assert learn.history_path().exists()
        # The attempt moved the watermark: the loop is not due again at once.
        assert learn.auto_retrain_status(db)["due"] is False
        event = (
            db.execute(
                select(AuditEvent)
                .where(AuditEvent.entity == "model:pairwise")
                .where(AuditEvent.action.in_(("model.retrained", "model.kept")))
                .order_by(AuditEvent.seq.desc())
            )
            .scalars()
            .first()
        )
        assert event is not None and event.user == "system"
        assert json.loads(event.payload_json)["promoted"] == last["promoted"]
        status = learn.status(db)
        assert status["history"][0]["ts"] == last["ts"]
        assert set(status["auto_retrain"]) >= {"enabled", "every", "labels_since", "due"}

    def test_simulated_labels_do_not_count(self, db, pipeline_run):
        _ensure_champion(db)
        before = learn.auto_retrain_status(db)["labels_since"]
        added = learn.simulate_labels(db, 20)["added"]
        assert added > 0
        after = learn.auto_retrain_status(db)
        assert after["labels_since"] == before
        assert learn.schedule_retrain(db) is None

    def test_a_worse_challenger_is_kept_not_promoted(self, db, pipeline_run, monkeypatch):
        from app.models import AuditEvent

        champion = _ensure_champion(db)
        saved_before = learn.model_path().read_text()

        def poor(_db, _model):
            # Same held-out set as the champion's, so its stored AUC stands.
            return {
                "pairs": champion.holdout["pairs"],
                "positives": 1,
                "model_auc": 0.51,
                "pipeline_auc": 0.5,
                "grey_pairs": 0,
                "grey_model_auc": None,
                "grey_pipeline_auc": None,
                "per_class": [],
            }

        monkeypatch.setattr(learn, "evaluate_holdout", poor)
        attempt = learn.maybe_retrain(db)
        assert attempt["promoted"] is False and "champion kept" in attempt["reason"]
        assert attempt["weights"] is None and attempt["champion_auc"] == champion.holdout_auc()
        assert learn.model_path().read_text() == saved_before
        assert learn.load_model().trained_at == champion.trained_at
        event = (
            db.execute(
                select(AuditEvent)
                .where(AuditEvent.entity == "model:pairwise")
                .order_by(AuditEvent.seq.desc())
            )
            .scalars()
            .first()
        )
        assert event.action == "model.kept"
        assert learn.history(1)[0]["promoted"] is False

    def test_a_challenger_that_is_not_worse_is_promoted(self, db, pipeline_run):
        champion = _ensure_champion(db)
        attempt = learn.maybe_retrain(db)
        assert attempt["promoted"] is True
        assert attempt["holdout_auc"] >= champion.holdout_auc() - learn.PROMOTION_TOLERANCE
        assert attempt["weights"] == learn.load_model().weights()

    def test_only_one_round_runs_at_a_time(self, db, pipeline_run):
        _ensure_champion(db)
        with learn._retrain_lock:
            assert learn.maybe_retrain(db) == {"skipped": "a retrain is already running"}
            assert learn.schedule_retrain(db) is None

    def test_a_failing_retrain_never_raises_into_the_decision(self, db, pipeline_run, monkeypatch):
        _ensure_champion(db)
        monkeypatch.setattr(learn, "fit", lambda _db: 1 / 0)
        assert learn.maybe_retrain(db) is None
        monkeypatch.setattr(learn, "auto_retrain_status", lambda _db: 1 / 0)
        assert learn.schedule_retrain(db) is None


class TestSuggestions:
    def test_suggestions_are_explicit_about_not_being_applied(self, db, pipeline_run):
        from app import match

        t_high_before = match.T_HIGH
        _ensure_champion(db)
        suggestions = learn.suggest_thresholds(db)
        assert suggestions["applied"] is False
        assert suggestions["current_t_high"] == t_high_before
        assert "not applied" in suggestions["note"]
        for row in suggestions["classes"]:
            assert row["applied"] is False
            assert row["labelled_pairs"] >= learn.SUGGESTION_MIN_LABELS
            assert 0 < row["positives"] < row["labelled_pairs"]
            assert 0.0 <= row["suggested_t_high"] <= 1.0
            assert 0.0 <= row["suggested_precision"] <= 1.0 and 0.0 <= row["suggested_f1"] <= 1.0
            assert row["current_t_high"] == t_high_before
        assert t_high_before == match.T_HIGH
        status = learn.status(db)
        assert status["suggestions"]["applied"] is False

    def test_a_class_with_one_answer_only_gets_no_suggestion(self, db, pipeline_run):
        # Thirty labels that all say "yes" cannot place a cut.
        suggestions = learn.suggest_thresholds(db, min_labels=10**6)
        assert suggestions["classes"] == [] and suggestions["applied"] is False


class TestRealLabelsFirst:
    """Once people's decisions outnumber the simulated ones, the model is
    taught by people alone, and is judged on them out of sample."""

    def _reviewer_labels_from_truth(self, db, n: int) -> list[int]:
        """Reviewer labels written straight from the tuning split's truth, as
        many stewards' afternoons would have; returns the label ids."""
        truth = learn._truth(db, "tuning")
        labelled = {(a, b) for a, b in db.execute(select(PairLabel.item_a, PairLabel.item_b)).all()}
        ids: list[int] = []
        yes = no = 0
        for pair in db.execute(select(Pair).where(Pair.evidence_json != "{}")).scalars():
            if pair.item_a not in truth or pair.item_b not in truth:
                continue
            key = tuple(sorted((pair.item_a, pair.item_b)))
            if key in labelled:
                continue
            same = truth[pair.item_a] == truth[pair.item_b]
            # Keep the two answers roughly balanced, as a real queue is not.
            if (same and yes > no + 5) or (not same and no > yes + 5):
                continue
            yes += int(same)
            no += int(not same)
            row = learn.record_label(db, pair, same, 1, learn.SOURCE_REVIEWER)
            db.flush()
            ids.append(row.id)
            labelled.add(key)
            if len(ids) >= n:
                break
        db.commit()
        return ids

    def test_simulated_labels_alone_train_on_everything_and_show_no_matrix(self, db, pipeline_run):
        if learn.label_counts(db).get(learn.SOURCE_SIMULATED, 0) < learn.MIN_LABELS:
            learn.simulate_labels(db, 200)
        rows, which = learn.training_rows(db)
        assert which == "all"
        # The handful of reviewer labels other tests wrote do not make a matrix.
        if learn.label_counts(db).get(learn.SOURCE_REVIEWER, 0) < learn.CONFUSION_MIN_LABELS:
            assert learn.reviewer_confusion(db) is None

    def test_reviewer_labels_take_over_once_they_outnumber_the_simulated(self, db, pipeline_run):
        counts = learn.label_counts(db)
        simulated = counts.get(learn.SOURCE_SIMULATED, 0)
        need = max(simulated + 1, learn.MIN_LABELS, learn.CONFUSION_MIN_LABELS) - counts.get(
            learn.SOURCE_REVIEWER, 0
        )
        ids = self._reviewer_labels_from_truth(db, need + 5)
        try:
            rows, which = learn.training_rows(db)
            assert which == learn.SOURCE_REVIEWER
            assert all(source == learn.SOURCE_REVIEWER for _, _, _, source in rows)
            model = learn.fit(db)
            assert model.trained_on == learn.SOURCE_REVIEWER
            assert set(model.labels) == {learn.SOURCE_REVIEWER}

            matrix = learn.reviewer_confusion(db)
            assert matrix is not None
            assert matrix["tp"] + matrix["tn"] + matrix["fp"] + matrix["fn"] == matrix["labels"]
            assert 0.0 <= matrix["agreement"] <= 1.0
            assert "never saw it" in matrix["note"]
            status = learn.status(db)
            assert status["next_training_uses"] == learn.SOURCE_REVIEWER
            assert status["reviewer_confusion"]["labels"] == matrix["labels"]
        finally:
            db.execute(delete(PairLabel).where(PairLabel.id.in_(ids)))
            db.commit()
            learn.forget_model()
