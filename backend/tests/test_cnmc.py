"""CNMC format and the Damm check digit — spec §5."""

import pytest

from app.cnmc import (
    CODE_PATTERN,
    damm_check_digit,
    family_for,
    format_code,
    is_valid,
    next_code,
    serial_of,
)


class TestFormat:
    def test_shape_is_cccc_sss_nnnnnn_k(self):
        code = format_code("BRNG", "010", 1)
        assert CODE_PATTERN.match(code)
        assert code == "BRNG-010-000001-3"

    def test_serial_is_zero_padded(self):
        assert format_code("VALV", "020", 42).startswith("VALV-020-000042-")

    @pytest.mark.parametrize(
        ("family", "segment", "serial"),
        [("BR", "010", 1), ("BRNG", "10", 1), ("BRNG", "010", -1), ("BRNG", "010", 1_000_000)],
    )
    def test_malformed_input_is_rejected(self, family, segment, serial):
        with pytest.raises(ValueError):
            format_code(family, segment, serial)

    def test_every_class_maps_to_a_family(self):
        from app.taxonomy import load_schemas

        for class_code in load_schemas():
            family, segment = family_for(class_code)
            assert len(family) == 4 and len(segment) == 3


class TestDammCheckDigit:
    """Damm over Luhn: it also catches the 0/9 adjacent transposition."""

    def test_issued_codes_verify(self):
        for serial in (1, 2, 99, 12345, 999_999):
            assert is_valid(format_code("BRNG", "010", serial))

    def test_all_single_digit_errors_are_detected(self):
        code = format_code("BRNG", "010", 4321)
        for i, ch in enumerate(code):
            if not ch.isdigit():
                continue
            for replacement in "0123456789":
                if replacement == ch:
                    continue
                assert not is_valid(code[:i] + replacement + code[i + 1 :])

    def test_all_adjacent_transpositions_are_detected(self):
        body = "BRNG010004321"
        expected = damm_check_digit(body)
        for i in range(len(body) - 1):
            if body[i] == body[i + 1]:
                continue
            swapped = body[:i] + body[i + 1] + body[i] + body[i + 2 :]
            assert damm_check_digit(swapped) != expected

    def test_zero_nine_transposition_is_detected(self):
        """The case Luhn misses."""
        assert damm_check_digit("BRNG010000090") != damm_check_digit("BRNG010000009")

    @pytest.mark.parametrize("bad", ["", "nope", "BRNG-010-000001-9", "BRNG-10-000001-3"])
    def test_invalid_codes_are_rejected(self, bad):
        assert not is_valid(bad)


class TestAllocation:
    def test_next_code_skips_used_serials(self):
        assert serial_of(next_code("valve.gate", {1, 2, 3})) == 4

    def test_first_code_of_a_family_is_serial_one(self):
        assert serial_of(next_code("valve.gate", set())) == 1

    def test_different_classes_get_different_families(self):
        assert next_code("valve.gate", set())[:4] != next_code("pipe.seamless", set())[:4]

    def test_serial_of_rejects_junk(self):
        assert serial_of("not-a-code") is None


class TestIssuanceEndpoint:
    def _first_golden(self, db):
        from sqlalchemy import select

        from app.models import GoldenRecord

        return db.execute(
            select(GoldenRecord.id).where(GoldenRecord.status != "conflict").limit(1)
        ).scalar_one()

    def test_registrar_can_issue_and_the_code_verifies(self, as_registrar, db, pipeline_run):
        r = as_registrar.post(f"/api/cnmc/issue/{self._first_golden(db)}")
        assert r.status_code == 200
        assert is_valid(r.json()["code"])

    def test_issuing_twice_returns_the_same_code(self, as_registrar, db, pipeline_run):
        golden_id = self._first_golden(db)
        first = as_registrar.post(f"/api/cnmc/issue/{golden_id}").json()
        second = as_registrar.post(f"/api/cnmc/issue/{golden_id}").json()
        assert first["code"] == second["code"]
        assert second["already_issued"] is True

    def test_issuing_approves_the_golden_record(self, as_registrar, db, pipeline_run):
        from app.models import GoldenRecord

        golden_id = self._first_golden(db)
        as_registrar.post(f"/api/cnmc/issue/{golden_id}")
        db.expire_all()
        assert db.get(GoldenRecord, golden_id).status == "approved"

    def test_a_conflicted_cluster_cannot_be_coded(self, as_registrar, db, pipeline_run):
        """§2D: an unresolved identity-critical conflict blocks approval."""
        from sqlalchemy import select

        from app.models import GoldenRecord

        conflicted = db.execute(
            select(GoldenRecord.id).where(GoldenRecord.status == "conflict").limit(1)
        ).scalar_one_or_none()
        if conflicted is None:
            pytest.skip("this fixture produced no conflicted clusters")
        r = as_registrar.post(f"/api/cnmc/issue/{conflicted}")
        assert r.status_code == 409
        assert "conflict" in r.json()["detail"].lower()

    def test_the_code_can_be_looked_up(self, as_registrar, db, pipeline_run):
        code = as_registrar.post(f"/api/cnmc/issue/{self._first_golden(db)}").json()["code"]
        r = as_registrar.get(f"/api/cnmc/{code}")
        assert r.status_code == 200 and r.json()["code"] == code

    def test_steward_cannot_issue(self, as_steward, pipeline_run):
        r = as_steward.post("/api/cnmc/issue/1")
        assert r.status_code == 403

    def test_unknown_golden_record_is_404(self, as_registrar, pipeline_run):
        assert as_registrar.post("/api/cnmc/issue/999999").status_code == 404

    def test_validate_endpoint_is_public(self, client):
        code = format_code("BRNG", "010", 7)
        assert client.get(f"/api/cnmc/validate/{code}").json()["valid"] is True
        assert client.get("/api/cnmc/validate/BRNG-010-000007-0").json()["valid"] is False
