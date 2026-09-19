"""The house dictionary: a steward's word wins over ours, is audited, and
reaches the normaliser for that CPSE's rows."""

import json

from sqlalchemy import select

from app import abbreviations
from app.models import AuditEvent
from app.normalize import expand_abbreviations, normalize_row


class TestExpansion:
    def test_a_house_word_wins_over_the_built_in_table(self):
        assert expand_abbreviations("BRG SPWD 6205") == "BEARING SPWD 6205"
        assert (
            expand_abbreviations("BRG SPWD 6205", {"SPWD": "SPIRAL WOUND", "BRG": "BRIDGE"})
            == "BRIDGE SPIRAL WOUND 6205"
        )

    def test_normalize_row_takes_the_dictionary(self):
        plain = normalize_row("GSKT SPWD 2IN").norm_text
        house = normalize_row("GSKT SPWD 2IN", None, {"SPWD": "SPIRAL WOUND"}).norm_text
        assert "SPWD" in plain and "SPIRAL WOUND" in house


class TestTheDictionary:
    def test_a_steward_teaches_their_cpse_and_the_chain_records_it(self, client, db, pipeline_run):
        client.post("/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"})
        # Not for another CPSE, and not for everyone.
        assert (
            client.post(
                "/api/abbreviations",
                json={"token": "SPWD", "expansion": "spiral wound", "cpse_code": "IOCL"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/abbreviations", json={"token": "SPWD", "expansion": "spiral wound"}
            ).status_code
            == 403
        )
        added = client.post(
            "/api/abbreviations",
            json={
                "token": "spwd",
                "expansion": "spiral wound",
                "cpse_code": "CPCL",
                "note": "Manali stores",
            },
        )
        assert added.status_code == 200, added.text
        rows = added.json()["house"]
        assert any(
            r["token"] == "SPWD" and r["expansion"] == "SPIRAL WOUND" and r["cpse"] == "CPCL"
            for r in rows
        )
        event = (
            db.execute(
                select(AuditEvent)
                .where(AuditEvent.action == "abbreviation.upsert")
                .order_by(AuditEvent.seq.desc())
            )
            .scalars()
            .first()
        )
        assert event is not None and json.loads(event.payload_json)["after"] == "SPIRAL WOUND"

        # The preview shows what the word changes, for that CPSE only.
        pv = client.post(
            "/api/abbreviations/preview", json={"description": "GSKT SPWD 2IN", "cpse_code": "CPCL"}
        ).json()
        assert pv["changed"] is True and "SPIRAL WOUND" in pv["with_house_words"]
        other = client.post(
            "/api/abbreviations/preview", json={"description": "GSKT SPWD 2IN", "cpse_code": "IOCL"}
        ).json()
        assert other["changed"] is False

        # Teaching the same token again replaces, keeping one active row.
        client.post(
            "/api/abbreviations",
            json={"token": "SPWD", "expansion": "spiral wound gasket", "cpse_code": "CPCL"},
        )
        active = [
            r
            for r in client.get("/api/abbreviations?cpse=CPCL").json()["house"]
            if r["token"] == "SPWD"
        ]
        assert len(active) == 1 and active[0]["expansion"] == "SPIRAL WOUND GASKET"

        # Retiring it takes it out of force; the built-in count is stated.
        listing = client.get("/api/abbreviations").json()
        assert listing["built_in"] > 100
        rid = active[0]["id"]
        assert client.delete(f"/api/abbreviations/{rid}").status_code == 200
        assert all(r["id"] != rid for r in client.get("/api/abbreviations").json()["house"])

    def test_a_registrar_may_teach_every_catalogue_and_it_reaches_new_rows(
        self, as_registrar, db, pipeline_run
    ):
        from app.models import Cpse, Item, RawItem
        from app.pipeline import build_items

        added = as_registrar.post(
            "/api/abbreviations", json={"token": "HLMT", "expansion": "helmet"}
        )
        assert added.status_code == 200, added.text
        assert abbreviations.for_cpse(db, None)["HLMT"] == "HELMET"
        cpse_id = db.execute(select(Cpse.id).where(Cpse.code == "CPCL")).scalar_one()
        raw = RawItem(
            cpse_id=cpse_id, legacy_code="ABBR-TEST-1", description="HLMT SAFETY CL A", uom="NOS"
        )
        db.add(raw)
        db.commit()
        build_items(db, [raw.id])
        item = db.execute(select(Item).where(Item.raw_item_id == raw.id)).scalar_one()
        try:
            assert item.norm_text.startswith("HELMET SAFETY")
        finally:
            # Leave the estate as it was for the suites that follow.
            db.delete(item)
            db.delete(raw)
            db.commit()
            rid = next(r["id"] for r in added.json()["house"] if r["token"] == "HLMT")
            as_registrar.delete(f"/api/abbreviations/{rid}")
