"""Executive and Opportunity dashboards — spec §6.7, §6.8, §2E, §9A, §0.9b."""

import pytest
from sqlalchemy import func, select

from app import inventory, opportunity
from app.models import Cnmc, GoldenRecord, Item, PurchaseHistory
from app.visibility import Scope, price_band, redact_prices

REGISTRAR = Scope("registrar", None)
CPCL_STEWARD = Scope("steward", "CPCL")


class TestVisibilityPolicy:
    """§0.9b — the same rule for the dashboards and the Copilot."""

    def test_a_registrar_sees_attributed_prices(self):
        assert REGISTRAR.sees_all_prices

    def test_a_steward_does_not(self):
        assert not CPCL_STEWARD.sees_all_prices

    def test_a_steward_still_sees_their_own_cpse(self):
        rows = [{"cpse": "CPCL", "unit_price": 100.0}, {"cpse": "IOCL", "unit_price": 200.0}]
        redacted = redact_prices(rows, CPCL_STEWARD)
        assert redacted[0]["unit_price"] == 100.0
        assert redacted[1]["unit_price"] is None and redacted[1]["price_withheld"]

    def test_the_row_survives_redaction(self):
        """Knowing four CPSEs buy the item is the point; the price is what is held back."""
        rows = [{"cpse": "IOCL", "unit_price": 200.0, "qty": 12}]
        redacted = redact_prices(rows, CPCL_STEWARD)
        assert redacted[0]["qty"] == 12 and redacted[0]["cpse"] == "IOCL"

    def test_the_band_is_what_a_steward_sees_instead(self):
        band = price_band([100.0, 250.0, 180.0])
        assert band["n"] == 3 and band["min"] == 100.0 and band["max"] == 250.0
        assert "market range" in band["label"]

    def test_an_empty_price_set_has_no_band(self):
        assert price_band([]) is None and price_band([0.0, None]) is None


class TestJointTenders:
    """§9A: purchase history must be used, not merely stored."""

    def test_candidates_need_two_or_more_cpses(self, pipeline_run, db):
        result = opportunity.joint_tender_candidates(db, REGISTRAR)
        assert result["candidates"]
        assert all(c["cpse_count"] >= 2 for c in result["candidates"])

    def test_every_figure_states_its_assumption(self, pipeline_run, db):
        result = opportunity.joint_tender_candidates(db, REGISTRAR)
        assert "capturable" in result["assumption_note"]
        assert result["capture_assumption"] == opportunity.DEFAULT_CAPTURE

    def test_the_assumption_scales_the_estimate(self, pipeline_run, db):
        low = opportunity.joint_tender_candidates(db, REGISTRAR, capture=0.4)
        high = opportunity.joint_tender_candidates(db, REGISTRAR, capture=0.8)
        assert high["total_estimated_saving"] == pytest.approx(
            low["total_estimated_saving"] * 2, rel=0.01
        )

    def test_the_estimate_never_exceeds_the_observed_opportunity(self, pipeline_run, db):
        for candidate in opportunity.joint_tender_candidates(db, REGISTRAR)["candidates"]:
            assert candidate["estimated_saving"] <= candidate["max_opportunity"] + 0.01

    def test_a_steward_sees_a_band_not_other_cpses_prices(self, pipeline_run, db):
        result = opportunity.joint_tender_candidates(db, CPCL_STEWARD)
        candidate = result["candidates"][0]
        for row in candidate["per_cpse"]:
            if row["cpse"] != "CPCL":
                assert row["unit_price"] is None
        assert candidate["market_band"] is not None

    def test_the_programme_total_is_not_reduced_by_redaction(self, pipeline_run, db):
        """The consolidated figure is the point; only attribution is restricted."""
        registrar = opportunity.joint_tender_candidates(db, REGISTRAR)
        steward = opportunity.joint_tender_candidates(db, CPCL_STEWARD)
        assert registrar["total_estimated_saving"] == steward["total_estimated_saving"]


class TestPriceVariance:
    def test_prices_are_normalized_per_base_unit(self, pipeline_run, db):
        """§2A.1: a box of 100 must not be compared with a single piece."""
        result = opportunity.price_variance(db, REGISTRAR)
        assert "base unit" in result["note"]
        # Without normalization a packed row shows a ~100x spread; a real
        # catalogue's variance for one material is far smaller than that.
        assert result["rows"][0]["variance_pct"] < 80

    def test_rows_are_ordered_by_variance(self, pipeline_run, db):
        rows = opportunity.price_variance(db, REGISTRAR)["rows"]
        assert rows == sorted(rows, key=lambda r: r["variance_pct"], reverse=True)

    def test_a_steward_cannot_read_another_cpses_price(self, pipeline_run, db):
        for row in opportunity.price_variance(db, CPCL_STEWARD)["rows"]:
            for entry in row["prices"]:
                if entry["cpse"] != "CPCL":
                    assert entry["unit_price"] is None


class TestPurchaseTrend:
    def test_the_last_purchase_and_direction_are_reported(self, pipeline_run, db):
        item_id = db.execute(
            select(PurchaseHistory.item_id)
            .group_by(PurchaseHistory.item_id)
            .having(func.count() >= 2)
            .limit(1)
        ).scalar()
        result = opportunity.last_purchase_and_trend(db, item_id, REGISTRAR)
        assert result["orders"] >= 2
        assert result["last"]["unit_price"] > 0
        assert result["trend"]["direction"] in {"up", "down", "flat"}

    def test_an_item_never_purchased_reports_nothing_rather_than_zero(self, pipeline_run, db):
        assert opportunity.last_purchase_and_trend(db, 999999, REGISTRAR)["orders"] == 0


class TestInventorySharing:
    """§2E."""

    def test_a_transfer_suggestion_traces_to_real_stock(self, pipeline_run, db):
        result = inventory.transfer_suggestions(db, REGISTRAR)
        assert result["suggestions_found"] > 0, "the demo flow needs at least one"
        suggestion = result["suggestions"][0]
        assert suggestion["from"]["cpse"] != suggestion["to"]["cpse"]
        assert suggestion["qty"] > 0 and suggestion["avoided_purchase_value"] > 0
        assert suggestion["idle_since"]

    def test_the_out_of_scope_limitation_is_stated(self, pipeline_run, db):
        assert "Distance is out of scope" in inventory.transfer_suggestions(db, REGISTRAR)["note"]

    def test_dead_stock_is_valued_and_ordered(self, pipeline_run, db):
        result = inventory.dead_stock(db, REGISTRAR)
        assert result["materials_found"] > 0
        values = [row["value"] for row in result["rows"]]
        assert values == sorted(values, reverse=True)

    def test_consolidated_stock_sums_every_cpse(self, pipeline_run, db):
        from app.models import ClusterMember

        cluster_id = db.execute(
            select(ClusterMember.cluster_id)
            .group_by(ClusterMember.cluster_id)
            .having(func.count() >= 2)
            .limit(1)
        ).scalar()
        result = inventory.consolidated_stock(db, cluster_id, REGISTRAR)
        assert result["total_qty"] == pytest.approx(
            sum(p["qty_on_hand"] for p in result["positions"])
        )

    def test_a_steward_cannot_read_another_cpses_valuation(self, pipeline_run, db):
        from app.models import ClusterMember

        cluster_id = db.execute(
            select(ClusterMember.cluster_id)
            .group_by(ClusterMember.cluster_id)
            .having(func.count() >= 2)
            .limit(1)
        ).scalar()
        for position in inventory.consolidated_stock(db, cluster_id, CPCL_STEWARD)["positions"]:
            if position["cpse"] != "CPCL":
                assert position["value"] is None and position["value_withheld"]


class TestExecutiveEndpoint:
    def test_the_kpis_spec_6_7_names_are_present(self, client, pipeline_run):
        keys = {k["key"] for k in client.get("/api/dashboard/executive").json()["kpis"]}
        assert {
            "items",
            "clusters",
            "duplicates",
            "cnmcs",
            "automation",
            "savings",
        } <= keys

    def test_prevented_duplicates_are_counted_beside_the_cleanup(
        self, client, pipeline_run
    ):
        """The rest of this dashboard measures cleaning up; this one measures
        the mess not being made."""
        kpis = {
            k["key"]: k for k in client.get("/api/dashboard/executive").json()["kpis"]
        }
        assert "prevented" in kpis
        assert kpis["prevented"]["value"] >= 0
        assert kpis["prevented"]["note"]

    def test_kpis_reconcile_with_the_database(self, client, db, pipeline_run):
        """§6.7 AC: the numbers must reconcile, not merely look plausible."""
        body = client.get("/api/dashboard/executive").json()
        kpis = {k["key"]: k["value"] for k in body["kpis"]}
        assert kpis["items"] == db.execute(select(func.count(Item.id))).scalar()
        assert kpis["cnmcs"] == db.execute(select(func.count(Cnmc.id))).scalar()

    def test_a_modelled_figure_carries_its_assumption(self, client, pipeline_run):
        savings = next(
            k for k in client.get("/api/dashboard/executive").json()["kpis"] if k["key"] == "savings"
        )
        assert "capturable" in savings["note"]

    def test_the_heatmap_is_scaled_to_its_busiest_cell(self, client, pipeline_run):
        heatmap = client.get("/api/dashboard/executive").json()["heatmap"]
        assert heatmap["peak"] > 0
        assert max(c["intensity"] for c in heatmap["cells"]) == pytest.approx(1.0)
        assert len(heatmap["cells"]) == len(heatmap["classes"]) * len(heatmap["cpses"])

    def test_progress_is_a_fraction(self, client, pipeline_run):
        for row in client.get("/api/dashboard/executive").json()["per_cpse"]:
            assert 0.0 <= row["progress"] <= 1.0
            assert row["coded"] <= row["items"]

    def test_the_trend_reflects_what_actually_happened(self, client, as_registrar, db, pipeline_run):
        """No modelled curve: empty until a code is issued."""
        golden_id = db.execute(
            select(GoldenRecord.id).where(GoldenRecord.status == "draft").limit(1)
        ).scalar()
        as_registrar.post(f"/api/cnmc/issue/{golden_id}")
        trend = client.get("/api/dashboard/executive").json()["trend"]
        assert trend and trend[-1]["cnmcs_total"] >= 1


class TestOpportunityEndpoint:
    def test_the_three_blocks_are_present(self, client, pipeline_run):
        body = client.get("/api/dashboard/opportunity").json()
        assert {"joint_tenders", "price_variance", "inventory"} <= set(body)
        assert {"transfers", "dead_stock"} <= set(body["inventory"])

    def test_the_capture_assumption_is_a_parameter(self, client, pipeline_run):
        low = client.get("/api/dashboard/opportunity?capture=0.4").json()
        high = client.get("/api/dashboard/opportunity?capture=0.8").json()
        assert (
            high["joint_tenders"]["total_estimated_saving"]
            > low["joint_tenders"]["total_estimated_saving"]
        )

    def test_the_slider_range_is_enforced(self, client, pipeline_run):
        assert client.get("/api/dashboard/opportunity?capture=0.95").status_code == 422
        assert client.get("/api/dashboard/opportunity?capture=0.1").status_code == 422

    def test_the_viewers_scope_is_stated(self, client, pipeline_run):
        assert client.get("/api/dashboard/opportunity").json()["visibility"]["note"]
