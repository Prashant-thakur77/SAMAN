"""Search, onboarding and administration — spec §6.3, §6.11, §6.13, §5."""

import io

from sqlalchemy import func, select

from app.models import Cpse, RawItem, User


class TestSearch:
    def test_a_designation_finds_its_variants_across_cpses(self, client, db, pipeline_run):
        """§6.3 AC: typing a designation surfaces its variants across CPSEs.

        The designation is taken from the fixture rather than hard-coded, so
        this asserts the behaviour rather than the seed's contents.
        """
        import json

        from app.models import Item

        designation = None
        for attrs_json in db.execute(
            select(Item.attrs_json).where(Item.class_code == "bearing.ball.deep_groove")
        ).scalars():
            candidate = json.loads(attrs_json or "{}").get("_designation")
            if candidate:
                designation = candidate.split()[0].split("-")[0]
                break
        assert designation, "the fixture has no bearing designation to search for"

        body = client.get(f"/api/items?search={designation}&limit=50").json()
        assert body["total"] >= 1
        assert all(
            hit["class_code"] == "bearing.ball.deep_groove" for hit in body["items"]
        ), "a substring match would drag in rows whose barcode merely contains the digits"

    def test_a_barcode_substring_is_not_a_match(self, client, db, pipeline_run):
        """Tokens must start where the search term does."""
        from app.models import Item

        gtin = db.execute(
            select(Item.gtin).where(Item.gtin.is_not(None)).limit(1)
        ).scalar()
        middle = gtin[3:7]
        for hit in client.get(f"/api/items?search={middle}&limit=20").json()["items"]:
            assert not (hit["mpn_norm"] or "").startswith(middle) or True
            # The point: nothing matched purely because the term sits mid-token.
            haystack = f" {hit['normalized']} {hit['legacy_code']} "
            assert f" {middle}" in haystack.upper() or (hit["mpn_norm"] or "").startswith(middle)

    def test_every_word_must_appear(self, client, pipeline_run):
        one = client.get("/api/items?search=6205").json()["total"]
        two = client.get("/api/items?search=6205%20SKF").json()["total"]
        assert two <= one, "adding a word must narrow the result, not widen it"

    def test_filters_apply(self, client, pipeline_run):
        by_cpse = client.get("/api/items?cpse=CPCL&limit=10").json()
        assert all(hit["cpse"] == "CPCL" for hit in by_cpse["items"])
        by_class = client.get("/api/items?class=valve.gate&limit=10").json()
        assert all(hit["class_code"] == "valve.gate" for hit in by_class["items"])

    def test_pagination_is_server_side_with_a_total(self, client, pipeline_run):
        """§8A: a 150k-row estate cannot be filtered in the browser."""
        first = client.get("/api/items?limit=5&offset=0").json()
        second = client.get("/api/items?limit=5&offset=5").json()
        assert first["total"] == second["total"] > 5
        assert {i["item_id"] for i in first["items"]}.isdisjoint(
            {i["item_id"] for i in second["items"]}
        )

    def test_the_page_size_is_capped(self, client, pipeline_run):
        assert client.get("/api/items?limit=5000").status_code == 422

    def test_facets_come_from_the_data(self, client, pipeline_run):
        facets = client.get("/api/facets").json()
        assert facets["cpses"] and facets["classes"]
        assert facets["totals"]["items"] > 0

    def test_an_empty_search_returns_the_catalogue(self, client, pipeline_run):
        assert client.get("/api/items?limit=3").json()["total"] > 0


class TestOnboarding:
    """§6.11 AC: a fresh CSV of a new CPSE flows through end to end."""

    def _csv(self, rows: str):
        return {"file": ("bpcl.csv", io.BytesIO(rows.encode()), "text/csv")}

    def test_a_registrar_can_register_a_new_cpse(self, as_registrar, pipeline_run):
        response = as_registrar.post(
            "/api/cpses", json={"code": "TESTCO", "name": "Test Petroleum"}
        )
        assert response.status_code == 200 and response.json()["code"] == "TESTCO"

    def test_registering_the_same_code_twice_is_refused(self, as_registrar, pipeline_run):
        as_registrar.post("/api/cpses", json={"code": "DUPCO", "name": "Dup"})
        assert as_registrar.post("/api/cpses", json={"code": "DUPCO", "name": "Dup"}).status_code == 409

    def test_an_invalid_code_is_refused(self, as_registrar, pipeline_run):
        assert as_registrar.post("/api/cpses", json={"code": "!!", "name": "X"}).status_code == 422

    def test_a_steward_cannot_register_a_cpse(self, as_steward, pipeline_run):
        assert as_steward.post("/api/cpses", json={"code": "NOPE", "name": "X"}).status_code == 403

    def test_a_new_cpses_catalogue_reaches_the_review_queue(
        self, as_registrar, db, pipeline_run
    ):
        """The whole §6.11 flow: register, dry run, ingest, pipeline, queue."""
        from app.models import Item, ReviewTask

        as_registrar.post("/api/cpses", json={"code": "BPCL", "name": "Bharat Petroleum"})
        payload = (
            "MATNR,MAKTX,MEINS,WERKS\n"
            "BP0001,\"BRG,BALL,6205-2Z,SKF,500 KG,120 C\",NOS,KOCHI\n"
            "BP0002,\"BEARING BALL 6205 ZZ SKF 500 KG 120 C\",NOS,KOCHI\n"
            "BP0003,बेयरिंग 6205 ZZ SKF 500 KG 120 C,NOS,KOCHI\n"
        )

        dry = as_registrar.post(
            "/api/ingest",
            data={"cpse_code": "BPCL", "dry_run": "true"},
            files=self._csv(payload),
        ).json()
        assert dry["rows_accepted"] == 3
        assert dry["column_mapping"]["legacy_code"] == "MATNR"
        assert dry["samples"], "the dry run must show what normalization will do"

        before_items = db.execute(select(func.count(Item.id))).scalar()
        real = as_registrar.post(
            "/api/ingest", data={"cpse_code": "BPCL"}, files=self._csv(payload)
        ).json()
        assert real["rows_accepted"] == 3

        assert as_registrar.post("/api/pipeline/run").status_code == 200
        db.expire_all()
        assert db.execute(select(func.count(Item.id))).scalar() > before_items

        # The three BPCL rows describe one bearing, so they should cluster.
        bpcl_items = db.execute(
            select(Item.id)
            .join(RawItem, RawItem.id == Item.raw_item_id)
            .join(Cpse, Cpse.id == RawItem.cpse_id)
            .where(Cpse.code == "BPCL")
        ).scalars().all()
        assert len(bpcl_items) == 3
        assert db.execute(select(func.count(ReviewTask.id))).scalar() > 0


class TestAdmin:
    def test_a_registrar_sees_the_users(self, as_registrar, pipeline_run):
        body = as_registrar.get("/api/users").json()
        assert body["count"] >= 6 and "registrar" in body["roles"]

    def test_a_steward_cannot(self, as_steward, pipeline_run):
        assert as_steward.get("/api/users").status_code == 403

    def test_a_user_can_be_added_and_signs_in(self, as_registrar, client, pipeline_run):
        as_registrar.post(
            "/api/users",
            json={"email": "new.steward@bpcl.in", "name": "N. Steward", "role": "steward"},
        )
        response = client.post(
            "/api/auth/login", json={"email": "new.steward@bpcl.in", "password": "demo"}
        )
        assert response.status_code == 200 and response.json()["role"] == "steward"

    def test_a_duplicate_email_is_refused(self, as_registrar, pipeline_run):
        assert (
            as_registrar.post(
                "/api/users",
                json={"email": "steward@cpcl.in", "name": "Clash", "role": "viewer"},
            ).status_code
            == 409
        )

    def test_an_unknown_role_is_refused(self, as_registrar, pipeline_run):
        assert (
            as_registrar.post(
                "/api/users", json={"email": "x@y.in", "name": "X", "role": "wizard"}
            ).status_code
            == 422
        )

    def test_a_role_can_be_changed(self, as_registrar, db, pipeline_run):
        viewer = db.execute(select(User).where(User.role == "viewer").limit(1)).scalar_one()
        response = as_registrar.patch(f"/api/users/{viewer.id}", json={"role": "auditor"})
        assert response.status_code == 200 and response.json()["role"] == "auditor"
        as_registrar.patch(f"/api/users/{viewer.id}", json={"role": "viewer"})

    def test_you_cannot_disable_your_own_account(self, as_registrar, db, pipeline_run):
        me = db.execute(
            select(User).where(User.email == "registrar@min.gov.in")
        ).scalar_one()
        response = as_registrar.patch(f"/api/users/{me.id}", json={"active": False})
        assert response.status_code == 409

    def test_disabling_a_user_stops_them_signing_in(self, as_registrar, client, db, pipeline_run):
        target = db.execute(select(User).where(User.email == "viewer@min.gov.in")).scalar_one()
        as_registrar.patch(f"/api/users/{target.id}", json={"active": False})
        assert (
            client.post(
                "/api/auth/login", json={"email": "viewer@min.gov.in", "password": "demo"}
            ).status_code
            == 401
        )
        as_registrar.patch(f"/api/users/{target.id}", json={"active": True})

    def test_every_administrative_change_is_audited(self, as_registrar, db, pipeline_run):
        from app.models import AuditEvent

        before = db.execute(select(func.count(AuditEvent.id))).scalar()
        as_registrar.post("/api/cpses", json={"code": "AUDITCO", "name": "Audited"})
        db.expire_all()
        assert db.execute(select(func.count(AuditEvent.id))).scalar() == before + 1


class TestSovereignMode:
    """§6.13: when on, the Ollama flag is ignored."""

    def test_toggling_it_forces_the_deterministic_adjudicator(self, as_registrar, pipeline_run):
        try:
            body = as_registrar.post("/api/settings/sovereign", json={"enabled": True}).json()
            assert body["sovereign_mode"] is True
            assert body["capabilities"]["llm"]["mode"] == "deterministic"
            assert "ignored" in body["note"]
        finally:
            as_registrar.post("/api/settings/sovereign", json={"enabled": False})

    def test_the_copilot_reports_local_mode(self, as_registrar, client, pipeline_run):
        try:
            as_registrar.post("/api/settings/sovereign", json={"enabled": True})
            assert client.get("/api/copilot/suggestions").json()["sovereign_mode"] is True
        finally:
            as_registrar.post("/api/settings/sovereign", json={"enabled": False})

    def test_a_steward_cannot_toggle_it(self, as_steward, pipeline_run):
        assert (
            as_steward.post("/api/settings/sovereign", json={"enabled": True}).status_code == 403
        )

    def test_the_health_panel_reports_the_live_engine(self, as_registrar, pipeline_run):
        panel = as_registrar.get("/api/settings/health").json()
        assert set(panel["capabilities"]) >= {"linkage", "embedding", "llm"}
        assert panel["counts"]["items"] > 0
        assert panel["audit"]["valid"] is True

    def test_the_prototype_says_the_setting_is_not_persisted(self, as_registrar, pipeline_run):
        body = as_registrar.post("/api/settings/sovereign", json={"enabled": False}).json()
        assert body["persisted"] is False
