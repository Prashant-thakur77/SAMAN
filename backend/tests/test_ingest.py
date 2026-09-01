"""CSV ingest and its validation report — spec §5, §6.11."""

import io

from sqlalchemy import func, select

from app.models import RawItem
from app.routers.ingest import guess_mapping


def csv_bytes(rows: str) -> dict:
    return {"file": ("catalogue.csv", io.BytesIO(rows.encode()), "text/csv")}


class TestColumnMapping:
    def test_canonical_headers_map(self):
        mapping, unmapped = guess_mapping(
            ["legacy_code", "description", "uom", "plant", "price", "qty_on_hand"]
        )
        assert set(mapping) == {"legacy_code", "description", "uom", "plant", "price", "qty_on_hand"}
        assert unmapped == []

    def test_sap_style_headers_map(self):
        """Real extracts arrive with SAP field names, not ours."""
        mapping, _ = guess_mapping(["MATNR", "MAKTX", "MEINS", "WERKS"])
        assert mapping["legacy_code"] == "MATNR"
        assert mapping["description"] == "MAKTX"
        assert mapping["uom"] == "MEINS"

    def test_spacing_and_case_are_tolerated(self):
        mapping, _ = guess_mapping(["Material Number", "Material Description"])
        assert mapping["legacy_code"] == "Material Number"
        assert mapping["description"] == "Material Description"

    def test_unrecognised_headers_are_reported_not_dropped_silently(self):
        _, unmapped = guess_mapping(["legacy_code", "description", "cost_centre"])
        assert unmapped == ["cost_centre"]


class TestIngest:
    def test_dry_run_writes_nothing(self, as_steward, db):
        before = db.execute(select(func.count(RawItem.id))).scalar()
        r = as_steward.post(
            "/api/ingest",
            data={"cpse_code": "CPCL", "dry_run": "true"},
            files=csv_bytes("legacy_code,description,uom\nDRY1,BALL BEARING SKF 6205-2Z,NOS\n"),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["dry_run"] is True and body["rows_accepted"] == 1
        assert db.execute(select(func.count(RawItem.id))).scalar() == before

    def test_report_shows_what_normalization_will_do(self, as_steward):
        r = as_steward.post(
            "/api/ingest",
            data={"cpse_code": "CPCL", "dry_run": "true"},
            files=csv_bytes("legacy_code,description,uom\nS1,\"BRG,BALL,6205ZZ,SKF\",NOS\n"),
        )
        sample = r.json()["samples"][0]
        assert sample["normalized"] == "BEARING BALL 6205ZZ SKF"
        assert sample["class_code"] == "bearing.ball.deep_groove"
        assert sample["attrs"]["bore_mm"] == 25

    def test_rows_are_written_when_not_a_dry_run(self, as_steward, db):
        before = db.execute(select(func.count(RawItem.id))).scalar()
        r = as_steward.post(
            "/api/ingest",
            data={"cpse_code": "CPCL"},
            files=csv_bytes("legacy_code,description\nNEW1,VALVE GATE 50NB CLASS 300 SS316\n"),
        )
        assert r.json()["rows_accepted"] == 1
        assert db.execute(select(func.count(RawItem.id))).scalar() == before + 1

    def test_missing_fields_are_rejected_with_a_reason(self, as_steward):
        r = as_steward.post(
            "/api/ingest",
            data={"cpse_code": "CPCL", "dry_run": "true"},
            files=csv_bytes("legacy_code,description\n,NO CODE\nX1,\n"),
        )
        body = r.json()
        assert body["rows_rejected"] == 2
        reasons = " ".join(row["reason"] for row in body["rejected"])
        assert "code" in reasons.lower() and "description" in reasons.lower()

    def test_duplicate_codes_within_the_file_are_caught(self, as_steward):
        r = as_steward.post(
            "/api/ingest",
            data={"cpse_code": "CPCL", "dry_run": "true"},
            files=csv_bytes("legacy_code,description\nD1,BEARING 6205\nD1,BEARING 6205\n"),
        )
        assert r.json()["duplicates_in_file"] == 1

    def test_re_ingesting_the_same_file_is_idempotent(self, as_steward):
        payload = "legacy_code,description\nIDEM1,GASKET SPIRAL WOUND 80NB CLASS 150\n"
        first = as_steward.post(
            "/api/ingest", data={"cpse_code": "CPCL"}, files=csv_bytes(payload)
        ).json()
        second = as_steward.post(
            "/api/ingest", data={"cpse_code": "CPCL"}, files=csv_bytes(payload)
        ).json()
        assert first["rows_accepted"] == 1
        assert second["rows_accepted"] == 0 and second["already_present"] == 1

    def test_unknown_cpse_is_404(self, as_steward):
        r = as_steward.post(
            "/api/ingest",
            data={"cpse_code": "NOPE"},
            files=csv_bytes("legacy_code,description\nA,B\n"),
        )
        assert r.status_code == 404

    def test_file_without_identifiable_columns_explains_itself(self, as_steward):
        r = as_steward.post(
            "/api/ingest",
            data={"cpse_code": "CPCL"},
            files=csv_bytes("foo,bar\n1,2\n"),
        )
        assert r.status_code == 422
        assert "foo" in r.json()["detail"]

    def test_explicit_mapping_overrides_the_guess(self, as_steward):
        r = as_steward.post(
            "/api/ingest",
            data={
                "cpse_code": "CPCL",
                "dry_run": "true",
                "mapping": '{"legacy_code": "our_ref", "description": "text"}',
            },
            files=csv_bytes("our_ref,text\nM1,BALL BEARING SKF 6205-2Z\n"),
        )
        assert r.status_code == 200 and r.json()["rows_accepted"] == 1

    def test_non_utf8_file_is_read_rather_than_refused(self, as_steward):
        """CPSE extracts are routinely cp1252."""
        payload = "legacy_code,description\nCP1,VALVE 50NB CLASS 300 SS316 CAFé\n".encode("cp1252")
        r = as_steward.post(
            "/api/ingest",
            data={"cpse_code": "CPCL", "dry_run": "true"},
            files={"file": ("x.csv", io.BytesIO(payload), "text/csv")},
        )
        assert r.status_code == 200 and r.json()["rows_accepted"] == 1


class TestPipelineEndpoint:
    def test_status_is_available_without_running_anything(self, client):
        r = client.get("/api/pipeline/status")
        assert r.status_code == 200
        assert r.json()["state"] in {"idle", "running", "done", "error"}

    def test_run_creates_items_for_newly_ingested_rows(self, as_steward, db):
        from app.models import Item

        as_steward.post(
            "/api/ingest",
            data={"cpse_code": "CPCL"},
            files=csv_bytes("legacy_code,description\nPIPE1,PIPE SEAMLESS 100NB SCH40 CS-A106B\n"),
        )
        before = db.execute(select(func.count(Item.id))).scalar()
        r = as_steward.post("/api/pipeline/run")
        assert r.status_code == 200
        db.expire_all()
        after = db.execute(select(func.count(Item.id))).scalar()
        assert after > before


class TestUploadLimits:
    def test_an_oversized_file_is_refused_without_being_buffered(
        self, as_registrar, seeded, monkeypatch
    ):
        """The cap has to fire during the read, not after it.

        The limit is lowered rather than a 64 MB body constructed: the point
        under test is the ordering, not the constant.
        """
        from app.routers import ingest as ingest_router

        monkeypatch.setattr(ingest_router, "MAX_UPLOAD_BYTES", 1024)
        monkeypatch.setattr(ingest_router, "UPLOAD_CHUNK", 256)

        body = b"legacy_code,description\n" + b"X,LONG DESCRIPTION HERE\n" * 500
        response = as_registrar.post(
            "/api/ingest",
            data={"cpse_code": "CPCL", "dry_run": "true"},
            files={"file": ("big.csv", body, "text/csv")},
        )
        assert response.status_code == 413
        assert "MB" in response.json()["detail"]

    def test_a_file_inside_the_limit_still_ingests(self, as_registrar, seeded):
        body = b"legacy_code,description,uom\nUP-1,BEARING BALL 6205 ZZ SKF,NOS\n"
        response = as_registrar.post(
            "/api/ingest",
            data={"cpse_code": "CPCL", "dry_run": "true"},
            files={"file": ("small.csv", body, "text/csv")},
        )
        assert response.status_code == 200
