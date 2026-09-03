"""The data-quality scorecard and ABC classes: computed from the tables the
pipeline keeps, stated with their weights, and served where a buyer looks."""

from app import quality
from app.opportunity import ABC_A_SHARE, abc_classes, load_purchases


class TestScorecard:
    def test_every_cpse_gets_rates_in_range_and_a_score(self, db, pipeline_run):
        card = quality.scorecard(db)
        assert abs(sum(card["weights"].values()) - 1.0) < 1e-9
        assert card["cpses"] and card["national"]
        for row in card["cpses"] + [card["national"]]:
            assert set(row["rates"]) == set(card["weights"])
            assert all(0.0 <= v <= 1.0 for v in row["rates"].values())
            assert 0.0 <= row["score"] <= 1.0
            assert row["items"] > 0

    def test_the_national_row_counts_every_row_once(self, db, pipeline_run):
        card = quality.scorecard(db)
        assert card["national"]["items"] == sum(r["items"] for r in card["cpses"])

    def test_internal_duplicates_are_within_a_cpse_only(self, db, pipeline_run):
        """Two CPSEs sharing a cluster is the platform working, not a defect."""
        card = quality.scorecard(db)
        for row in card["cpses"]:
            assert row["internal_duplicates"] <= row["items"]

    def test_it_rides_with_the_executive_dashboard(self, client, pipeline_run):
        body = client.get("/api/dashboard/executive").json()
        assert body["quality"]["cpses"] and "weights" in body["quality"]


class TestAbc:
    def test_a_class_carries_the_top_of_each_cpses_spend(self, db, pipeline_run):
        purchases = load_purchases(db)
        classes = abc_classes(purchases)
        assert classes, "no purchases in the window"
        spend: dict[str, dict[str, float]] = {}
        for purchase in purchases:
            entry = classes.get((purchase.cluster_id, purchase.cpse))
            if entry is None:
                continue
            by_class = spend.setdefault(purchase.cpse, {"A": 0.0, "B": 0.0, "C": 0.0})
            by_class[entry["abc"]] += purchase.qty * purchase.unit_price
        for cpse, by_class in spend.items():
            total = sum(by_class.values())
            # A carries up to 70% by construction; the material that crosses
            # the line is the first B, so A sits just under the cut-off.
            assert by_class["A"] / total <= ABC_A_SHARE + 1e-9, cpse
            assert by_class["A"] >= by_class["C"], cpse

    def test_the_item_page_and_dead_stock_carry_the_class(self, client, pipeline_run):
        item = client.get("/api/items/1").json()
        assert "abc" in item["purchase_history"]
        assert item["purchase_history"]["abc"] in (None, "A", "B", "C")
        client.post("/api/auth/login", json={"email": "registrar@min.gov.in", "password": "demo"})
        dashboard = client.get("/api/dashboard/opportunity").json()
        positions = [
            p for row in dashboard["inventory"]["dead_stock"]["rows"] for p in row["positions"]
        ]
        assert positions and all(p["abc"] in ("A", "B", "C") for p in positions)
