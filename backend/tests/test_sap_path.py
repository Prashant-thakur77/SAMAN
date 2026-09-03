"""The SAP door: the RFC adapter speaks the contract over recorded BAPI calls,
the factory falls back to the mock with a reason, and the hook's API key acts
as a named user."""

import re

import pytest

from app import erp
from app.erp import RfcErpAdapter


class FakeConnection:
    """Enough of pyrfc.Connection to check what the adapter says to SAP."""

    def __init__(self, mara: list[dict], ekpo=(), mard=(), mbew=()):
        self.tables = {"MARA": mara, "EKPO": list(ekpo), "MARD": list(mard), "MBEW": list(mbew)}
        self.calls: list[tuple[str, dict]] = []
        self.commits = 0
        self.refuse: str | None = None

    def call(self, name, **params):
        self.calls.append((name, params))
        if name == "RFC_READ_TABLE":
            text = " ".join(o["TEXT"] for o in params["OPTIONS"])
            wanted = set(re.findall(r"MATNR EQ '([^']+)'", text))
            rows = [r for r in self.tables[params["QUERY_TABLE"]] if r["MATNR"] in wanted]
            if "LOEKZ EQ ''" in text:
                rows = [r for r in rows if not r.get("LOEKZ") and not r.get("ELIKZ")]
            fields = [f["FIELDNAME"] for f in params["FIELDS"]]
            return {"DATA": [{"WA": "|".join(str(r.get(f, "")) for f in fields)} for r in rows]}
        if name == "BAPI_MATERIAL_SAVEDATA":
            if self.refuse:
                return {"RETURN": {"TYPE": "E", "MESSAGE": self.refuse}}
            matnr = params["HEADDATA"]["MATERIAL"]
            row = next(r for r in self.tables["MARA"] if r["MATNR"] == matnr)
            if "CLIENTDATA" in params:
                row["LVORM"] = params["CLIENTDATA"]["DEL_FLAG"]
            if "EXTENSIONIN" in params:
                value = params["EXTENSIONIN"][0]["VALUEPART1"]
                flags = params["EXTENSIONINX"][0]["VALUEPART1"]
                assert value[:18].strip() == matnr
                if flags[18] == "X":
                    row["ZZ_CNMC"] = value[18:38].strip()
                if flags[19] == "X":
                    row["ZZ_SUPERSEDES"] = value[38:56].strip()
            return {"RETURN": {"TYPE": "S", "MESSAGE": "saved"}}
        if name == "BAPI_TRANSACTION_COMMIT":
            self.commits += 1
            return {"RETURN": {"TYPE": ""}}
        raise AssertionError(f"unexpected RFC {name}")


@pytest.fixture
def sap():
    mara = [
        {
            "MATNR": "CPCL-A1",
            "MTART": "HIBE",
            "MEINS": "EA",
            "LVORM": "",
            "ZZ_CNMC": "",
            "ZZ_SUPERSEDES": "",
        },
        {
            "MATNR": "CPCL-A2",
            "MTART": "HIBE",
            "MEINS": "EA",
            "LVORM": "",
            "ZZ_CNMC": "",
            "ZZ_SUPERSEDES": "",
        },
        {
            "MATNR": "IOCL-B7",
            "MTART": "HIBE",
            "MEINS": "NO",
            "LVORM": "",
            "ZZ_CNMC": "",
            "ZZ_SUPERSEDES": "",
        },
    ]
    ekpo = [
        {"MATNR": "CPCL-A2", "MENGE": "12.000", "LOEKZ": "", "ELIKZ": ""},
        {"MATNR": "CPCL-A2", "MENGE": "5.000", "LOEKZ": "", "ELIKZ": "X"},  # delivered
        {"MATNR": "IOCL-B7", "MENGE": "3.000", "LOEKZ": "L", "ELIKZ": ""},  # deleted line
    ]
    mard = [{"MATNR": "CPCL-A1", "LABST": "40.000"}, {"MATNR": "CPCL-A1", "LABST": "2.000"}]
    mbew = [{"MATNR": "CPCL-A1", "SALK3": "1,250.50"}]
    return FakeConnection(mara, ekpo, mard, mbew)


class TestReads:
    def test_masters_come_back_in_the_contracts_names(self, sap):
        adapter = RfcErpAdapter(sap)
        masters = adapter.read_masters(["CPCL-A1", "IOCL-B7"])
        assert masters["IOCL-B7"]["meins"] == "NO"
        assert set(masters["CPCL-A1"]) == {
            "matnr",
            "mtart",
            "meins",
            "lvorm",
            "zz_cnmc",
            "zz_supersedes",
        }

    def test_open_lines_exclude_deleted_and_delivered(self, sap):
        tx = RfcErpAdapter(sap).read_open_transactions(["CPCL-A1", "CPCL-A2", "IOCL-B7"])
        assert tx["CPCL-A2"].open_po_lines == 1 and tx["CPCL-A2"].open_qty == 12.0
        assert tx["IOCL-B7"].open_po_lines == 0 and not tx["IOCL-B7"].blocks_change
        assert tx["CPCL-A1"].stock_qty == 42.0 and tx["CPCL-A1"].total_value == 1250.5

    def test_where_clauses_fit_rfc_read_tables_lines(self, sap):
        adapter = RfcErpAdapter(sap, batch=2)
        adapter.read_masters([f"CPCL-{n:06d}" for n in range(5)])
        reads = [p for name, p in sap.calls if name == "RFC_READ_TABLE"]
        assert len(reads) == 3  # 5 materials in batches of 2
        for params in reads:
            assert all(len(o["TEXT"]) <= 72 for o in params["OPTIONS"])


class TestWrites:
    def test_a_crossref_is_a_bapi_save_and_one_commit(self, sap):
        adapter = RfcErpAdapter(sap)
        after = adapter.write_crossref("CPCL-A1", "BRNG-010-000003-7")
        assert after["zz_cnmc"] == "BRNG-010-000003-7"
        save = next(p for name, p in sap.calls if name == "BAPI_MATERIAL_SAVEDATA")
        assert save["EXTENSIONIN"][0]["STRUCTURE"] == "BAPI_TE_MARA"
        assert "CLIENTDATA" not in save  # a cross-reference never touches the flag
        assert sap.commits == 1

    def test_a_block_sets_the_deletion_flag_never_deletes(self, sap):
        adapter = RfcErpAdapter(sap)
        after = adapter.block_material("CPCL-A2", "CPCL-A1")
        assert after["lvorm"] == "X" and after["zz_supersedes"] == "CPCL-A1"
        assert len(sap.tables["MARA"]) == 3

    def test_restore_puts_the_before_image_back(self, sap):
        adapter = RfcErpAdapter(sap)
        before = adapter.read_masters(["CPCL-A2"])["CPCL-A2"]
        adapter.block_material("CPCL-A2", "CPCL-A1")
        adapter.restore("CPCL-A2", before)
        assert adapter.read_masters(["CPCL-A2"])["CPCL-A2"] == before

    def test_bulk_writes_commit_once(self, sap):
        adapter = RfcErpAdapter(sap)
        assert adapter.block_material_many([("CPCL-A2", "CPCL-A1"), ("IOCL-B7", "CPCL-A1")]) == 2
        assert sap.commits == 1

    def test_a_refusal_from_sap_is_raised_not_swallowed(self, sap):
        sap.refuse = "Material locked by user MMCLERK"
        with pytest.raises(RuntimeError, match="MMCLERK"):
            RfcErpAdapter(sap).write_crossref("CPCL-A1", "BRNG-010-000003-7")


class TestFactory:
    def test_the_default_is_the_mock(self):
        assert erp.adapter_status()["mode"] == "mock"
        assert erp.adapter_status()["degraded"] is False

    def test_rfc_without_the_connector_falls_back_and_says_so(self, monkeypatch, client):
        from app.config import get_settings

        monkeypatch.setenv("SAMAN_ERP_ADAPTER", "rfc")
        monkeypatch.setenv("SAP_ASHOST", "sap.example.invalid")
        get_settings.cache_clear()
        erp.reset_adapter()
        try:
            status = erp.adapter_status()
            assert status["requested"] == "rfc" and status["mode"] == "mock"
            assert status["degraded"] and "unavailable" in status["note"]
            assert isinstance(erp.get_adapter(), erp.MockErpAdapter)
            from app import capabilities

            capabilities.detect.cache_clear()
            health = client.get("/api/health").json()["capabilities"]
            assert health["erp"]["mode"] == "mock" and health["erp"]["degraded"] is True
        finally:
            monkeypatch.delenv("SAMAN_ERP_ADAPTER")
            monkeypatch.delenv("SAP_ASHOST")
            get_settings.cache_clear()
            erp.reset_adapter()
            from app import capabilities

            capabilities.detect.cache_clear()


class TestApiKeys:
    def test_a_configured_key_acts_as_its_user(self, client, seeded, monkeypatch):
        from app.config import get_settings

        monkeypatch.setenv("SAMAN_API_KEYS", "steward@cpcl.in=hook-secret-1")
        get_settings.cache_clear()
        try:
            session = client.get("/api/auth/session", headers={"X-SAMAN-Key": "hook-secret-1"})
            assert session.status_code == 200 and session.json()["email"] == "steward@cpcl.in"
            assert client.get("/api/auth/session", headers={"X-SAMAN-Key": "wrong"}).json() is None
            # The hook's actual call: Smart-Create's check, as that steward.
            check = client.post(
                "/api/smart-create/check",
                json={"description": "BALL BEARING 6205 ZZ SKF"},
                headers={"X-SAMAN-Key": "hook-secret-1"},
            )
            assert check.status_code == 200, check.text
        finally:
            monkeypatch.delenv("SAMAN_API_KEYS")
            get_settings.cache_clear()

    def test_without_configuration_a_key_is_ignored(self, client, seeded):
        assert client.get("/api/auth/session", headers={"X-SAMAN-Key": "anything"}).json() is None
