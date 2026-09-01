"""Hash-chained audit log — spec §0.8 and §0.9a.

§0.9a asks specifically for a test that mutates a payload directly in the
database and asserts verification fails at the right sequence number.
"""

import json
from itertools import pairwise

import pytest
from sqlalchemy import select, text

from app import audit
from app.models import AuditEvent


@pytest.fixture
def ledger(db):
    """A short, valid chain to attack."""
    db.execute(text("DELETE FROM audit_event"))
    db.commit()
    audit.ensure_genesis(db)
    for n in range(1, 6):
        audit.record(db, "decision.approve", f"pair:{n}", {"n": n}, user="steward@cpcl.in")
    return db


class TestChainConstruction:
    def test_a_fresh_ledger_opens_with_a_genesis_event(self, db):
        db.execute(text("DELETE FROM audit_event"))
        db.commit()
        genesis = audit.ensure_genesis(db)
        assert genesis.seq == 0
        assert genesis.prev_hash == audit.GENESIS_PREV_HASH
        assert audit.verify(db)["valid"]

    def test_genesis_is_not_created_twice(self, db):
        db.execute(text("DELETE FROM audit_event"))
        db.commit()
        first = audit.ensure_genesis(db)
        assert audit.ensure_genesis(db).id == first.id

    def test_each_event_links_to_the_previous(self, ledger):
        events = ledger.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars().all()
        for previous, current in pairwise(events):
            assert current.prev_hash == previous.hash
            assert current.seq == previous.seq + 1

    def test_the_hash_covers_sequence_previous_and_payload(self):
        """Binding `seq` is what makes reordering detectable, not just tampering."""
        base = audit.compute_hash(5, "abc", '{"a":1}')
        assert audit.compute_hash(6, "abc", '{"a":1}') != base
        assert audit.compute_hash(5, "abd", '{"a":1}') != base
        assert audit.compute_hash(5, "abc", '{"a":2}') != base

    def test_canonical_json_is_order_independent(self):
        assert audit.canonical_json({"b": 1, "a": 2}) == audit.canonical_json({"a": 2, "b": 1})

    def test_a_clean_chain_verifies(self, ledger):
        result = audit.verify(ledger)
        assert result["valid"] and result["first_break"] is None
        assert result["events"] == 6


class TestTamperDetection:
    def test_editing_a_payload_breaks_the_chain_at_that_event(self, ledger):
        """The §0.9a test: mutate the DB directly, expect the exact seq."""
        ledger.execute(
            text("UPDATE audit_event SET payload_json = :p WHERE seq = 3"),
            {"p": '{"n":999}'},
        )
        ledger.commit()
        result = audit.verify(ledger)
        assert not result["valid"]
        assert result["first_break"]["seq"] == 3
        assert "altered" in result["first_break"]["reason"]

    def test_deleting_an_event_is_detected(self, ledger):
        ledger.execute(text("DELETE FROM audit_event WHERE seq = 3"))
        ledger.commit()
        result = audit.verify(ledger)
        assert not result["valid"]
        assert result["first_break"]["seq"] == 4
        assert "removed or reordered" in result["first_break"]["reason"]

    def test_reordering_two_events_is_detected(self, ledger):
        """A chain bound only by prev_hash could hide this; binding seq cannot."""
        rows = ledger.execute(
            text("SELECT seq, payload_json, hash, prev_hash FROM audit_event WHERE seq IN (2,3)")
        ).all()
        first, second = sorted(rows, key=lambda r: r[0])
        for target, source in ((2, second), (3, first)):
            ledger.execute(
                text(
                    "UPDATE audit_event SET payload_json=:p, hash=:h, prev_hash=:pv WHERE seq=:s"
                ),
                {"p": source[1], "h": source[2], "pv": source[3], "s": target},
            )
        ledger.commit()
        assert not audit.verify(ledger)["valid"]

    def test_rewriting_a_hash_to_match_a_forged_payload_still_breaks_the_link(self, ledger):
        """Recomputing one event's hash orphans every event after it."""
        forged = '{"n":42}'
        ledger.execute(
            text("UPDATE audit_event SET payload_json=:p, hash=:h WHERE seq=2"),
            {"p": forged, "h": audit.compute_hash(2, ledger.execute(
                text("SELECT prev_hash FROM audit_event WHERE seq=2")).scalar(), forged)},
        )
        ledger.commit()
        result = audit.verify(ledger)
        assert not result["valid"]
        assert result["first_break"]["seq"] == 3


class TestVoiding:
    """§0.9a: deletions are never physical."""

    def test_voiding_appends_rather_than_removes(self, ledger):
        before = ledger.execute(select(AuditEvent).where(AuditEvent.seq == 2)).scalar_one()
        audit.void(ledger, 2, "raised in error", user="approver@min.gov.in")
        still_there = ledger.execute(select(AuditEvent).where(AuditEvent.seq == 2)).scalar_one()
        assert still_there.hash == before.hash

    def test_the_chain_stays_valid_after_a_void(self, ledger):
        audit.void(ledger, 2, "raised in error")
        result = audit.verify(ledger)
        assert result["valid"] and 2 in result["voided_events"]

    def test_the_void_names_what_it_retracts(self, ledger):
        event = audit.void(ledger, 2, "duplicate entry")
        payload = json.loads(event.payload_json)
        assert payload["voids_seq"] == 2 and payload["reason"] == "duplicate entry"

    def test_voiding_an_unknown_event_is_refused(self, ledger):
        with pytest.raises(ValueError):
            audit.void(ledger, 9999, "nope")


class TestAuditApi:
    def test_verify_endpoint_reports_a_valid_chain(self, client, pipeline_run):
        body = client.get("/api/audit/verify").json()
        assert body["valid"] is True and body["first_break"] is None

    def test_the_stream_returns_newest_first(self, client, pipeline_run):
        events = client.get("/api/audit?limit=5").json()["events"]
        if len(events) > 1:
            assert events[0]["seq"] > events[-1]["seq"]

    def test_events_can_be_filtered_by_entity(self, client, as_registrar, pipeline_run, db):
        from app.models import GoldenRecord

        golden_id = db.execute(
            select(GoldenRecord.id).where(GoldenRecord.status == "draft").limit(1)
        ).scalar()
        as_registrar.post(f"/api/cnmc/issue/{golden_id}")
        body = client.get("/api/audit?entity=cnmc").json()
        assert body["total"] >= 1
        assert all(e["entity"].startswith("cnmc") for e in body["events"])

    def test_every_event_exposes_its_links(self, client, pipeline_run):
        for event in client.get("/api/audit?limit=3").json()["events"]:
            assert len(event["hash"]) == 64 and len(event["prev_hash"]) == 64


class TestConcurrentAppends:
    """The pipeline runs in a background task while a reviewer is deciding."""

    def test_two_writers_do_not_fork_or_fail_the_chain(self, db):
        import threading

        from sqlalchemy import text

        from app.db import SessionLocal

        db.execute(text("DELETE FROM audit_event"))
        db.commit()
        audit.ensure_genesis(db)

        failures: list[str] = []

        def append(worker: int) -> None:
            try:
                with SessionLocal() as session:
                    for n in range(10):
                        audit.record(session, "decision", f"p:{worker}-{n}", {"w": worker, "n": n})
            except Exception as exc:
                failures.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=append, args=(w,)) for w in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert failures == []
        db.expire_all()
        result = audit.verify(db)
        assert result["valid"], result["first_break"]
        assert result["events"] == 41  # genesis + 4 workers x 10


class TestAuditFiltering:
    """The stream is only useful if a specific event can be found in it."""

    def test_the_action_filter_narrows_the_stream(self, as_registrar, pipeline_run):
        everything = as_registrar.get("/api/audit").json()
        assert everything["actions"], "the stream must report what actions exist"
        action = max(everything["actions"], key=lambda name: everything["actions"][name])

        filtered = as_registrar.get(f"/api/audit?action={action}").json()
        assert filtered["total"] == everything["actions"][action]
        assert all(event["action"].startswith(action) for event in filtered["events"])

    def test_the_action_counts_add_up_to_the_whole_stream(
        self, as_registrar, pipeline_run
    ):
        body = as_registrar.get("/api/audit").json()
        assert sum(body["actions"].values()) == body["total"]

    def test_filters_combine(self, as_registrar, pipeline_run):
        body = as_registrar.get("/api/audit").json()
        event = body["events"][0]
        narrowed = as_registrar.get(
            f"/api/audit?action={event['action']}&user={event['user']}"
        ).json()
        assert narrowed["total"] >= 1
        assert all(e["user"] == event["user"] for e in narrowed["events"])

    def test_an_action_nobody_performed_returns_an_empty_stream(
        self, as_registrar, pipeline_run
    ):
        body = as_registrar.get("/api/audit?action=nobody.did.this").json()
        assert body["total"] == 0 and body["events"] == []
