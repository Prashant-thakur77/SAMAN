"""The per-CPSE catalogue report: reconciles with the dashboards, redacted as
the CPSE's steward would see it whoever asks, delivered by SMTP or into the
outbox, and audited."""

import email
import json
from email import policy

import pytest
from sqlalchemy import func, select

from app import analytics, inventory, opportunity, reports
from app.models import Cpse
from app.routers.dashboard import executive_for
from app.visibility import Scope

REGISTRAR = Scope("registrar", None)
PRICE_KEYS = ("unit_price", "unit_value", "price", "value", "total_value", "avoided_purchase_value")


@pytest.fixture(scope="module")
def cpcl(db_module):
    return reports.cpse_report(db_module, "CPCL", REGISTRAR)


@pytest.fixture(scope="module")
def db_module(pipeline_run):
    from app.db import SessionLocal

    with SessionLocal() as session:
        yield session


@pytest.fixture
def outbox(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMAN_OUTBOX_DIR", str(tmp_path / "outbox"))
    return tmp_path / "outbox"


def _walk(node, path=()):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _walk(value, (*path, key))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, (*path, i))


class TestReconciliation:
    """Every figure is the dashboard's figure for the same CPSE."""

    def test_coded_rows_are_the_executive_dashboards_per_cpse_coded(self, cpcl, db_module):
        per_cpse = next(
            row for row in executive_for(db_module, REGISTRAR)["per_cpse"] if row["cpse"] == "CPCL"
        )
        assert cpcl["catalogue"]["rows"] == per_cpse["items"]
        assert cpcl["catalogue"]["coded"] == per_cpse["coded"]
        assert cpcl["catalogue"]["coded_share"] == per_cpse["progress"]

    def test_cross_cpse_rows_over_every_cpse_sum_to_the_multi_cpse_rows(self, db_module):
        """Each row in a cluster two CPSEs share is counted once, under its
        own CPSE, so the sum over CPSEs is the dashboard's multi-CPSE rows."""
        codes = db_module.execute(select(Cpse.code)).scalars().all()
        total = sum(
            reports.cpse_report(db_module, code, REGISTRAR)["duplicates"]["cross_cpse"]["rows"]
            for code in codes
        )
        assert total == analytics.by_cpse_count(db_module)["multi_rows"]

    def test_the_per_cpse_breakdown_is_bounded_by_the_total(self, cpcl):
        cross = cpcl["duplicates"]["cross_cpse"]
        assert cross["by_cpse"], "the seeded estate shares materials between CPSEs"
        for row in cross["by_cpse"]:
            assert row["cpse"] != "CPCL"
            assert 0 < row["materials"] <= cross["clusters"]
            assert 0 < row["rows"] <= cross["rows"]
        assert sum(r["materials"] for r in cross["by_cpse"]) >= cross["clusters"]

    def test_internal_duplicates_are_the_scorecards(self, cpcl):
        assert (
            cpcl["duplicates"]["internal"]["surplus_rows"]
            == cpcl["quality"]["row"]["internal_duplicates"]
        )
        for example in cpcl["duplicates"]["internal"]["examples"]:
            assert example["a"]["legacy_code"] != example["b"]["legacy_code"]

    def test_dead_stock_over_every_cpse_is_the_dashboards_tile(self, db_module):
        codes = db_module.execute(select(Cpse.code)).scalars().all()
        total = sum(
            reports.cpse_report(db_module, code, REGISTRAR)["inventory"]["dead_stock"]["value_inr"]
            for code in codes
        )
        assert total == pytest.approx(
            inventory.dead_stock(db_module, REGISTRAR, limit=1)["total_value"], abs=1.0
        )

    def test_stock_value_is_the_cpses_own_positions(self, cpcl, db_module):
        from app.models import Stock

        cpse_id = db_module.execute(select(Cpse.id).where(Cpse.code == "CPCL")).scalar()
        value = db_module.execute(
            select(func.sum(Stock.qty_on_hand * Stock.unit_value)).where(Stock.cpse_id == cpse_id)
        ).scalar()
        assert cpcl["inventory"]["value_inr"] == pytest.approx(value, abs=0.01)

    def test_spend_in_the_window_is_the_cpses_share_of_the_ladder(self, cpcl, db_module):
        purchases = opportunity.load_purchases(db_module)
        mine = sum(p.qty * p.unit_price for p in purchases if p.cpse == "CPCL")
        assert cpcl["procurement"]["your_spend_inr"] == pytest.approx(mine, abs=0.01)
        assert cpcl["procurement"]["your_orders"] == sum(1 for p in purchases if p.cpse == "CPCL")

    def test_attributed_savings_never_exceed_the_estates_estimate(self, cpcl, db_module):
        tenders = opportunity.joint_tender_candidates(db_module, REGISTRAR, limit=0)
        assert (
            0
            < cpcl["procurement"]["joint_tenders"]["estimated_saving_yours_inr"]
            <= tenders["total_estimated_saving"]
        )
        for row in cpcl["procurement"]["joint_tenders"]["rows"]:
            assert row["estimated_saving_yours_inr"] <= row["estimated_saving_all_inr"]
            assert 0 < row["your_share_of_volume"] <= 1

    def test_pending_tasks_never_exceed_the_queue(self, cpcl, db_module):
        pending = executive_for(db_module, REGISTRAR)["review"]["pending"]
        for band, n in cpcl["review"]["pending"].items():
            assert n <= pending.get(band, 0)
        assert cpcl["review"]["conflicts"] <= cpcl["review"]["pending_total"]

    def test_every_modelled_figure_carries_its_assumption(self, cpcl):
        assert "capturable" in cpcl["procurement"]["joint_tenders"]["assumption"]
        assert "Not a forecast" in cpcl["procurement"]["joint_tenders"]["assumption"]
        assert "your own last price" in cpcl["inventory"]["transfers"]["as_receiver"]["assumption"]
        assert cpcl["synthetic_note"].startswith("The demo estate is synthetic")
        assert cpcl["period"]["months"] == opportunity.WINDOW_MONTHS

    def test_actions_carry_the_count_that_produced_them(self, cpcl):
        assert cpcl["actions"], "a mid-flight estate has work waiting"
        for action in cpcl["actions"]:
            assert action["count"] > 0 and action["key"] and action["text"]
        assert {a["key"] for a in cpcl["actions"]} & {"confirm_high", "grey", "conflicts"}

    def test_the_quality_section_names_the_weakest_rate_and_a_remedy(self, cpcl):
        weakest = cpcl["quality"]["weakest"]
        rates = cpcl["quality"]["row"]["rates"]
        assert rates[weakest["rate"]] == min(rates.values())
        assert weakest["what_lifts_it"]


class TestRedaction:
    """§0.9b: whoever asks, the document carries no other CPSE's price."""

    def test_the_report_is_computed_in_the_stewards_scope_even_for_the_registrar(self, cpcl):
        assert cpcl["requested_by"] == "registrar"
        assert cpcl["visibility"]["role"] == "steward"
        assert cpcl["visibility"]["sees_attributed_prices"] is False

    def test_no_dict_attributed_to_another_cpse_carries_a_price(self, cpcl):
        for path, node in _walk(cpcl):
            owner = node.get("cpse") or node.get("from_cpse") or node.get("to_cpse")
            if owner in (None, "CPCL", "withheld"):
                continue
            for key in PRICE_KEYS:
                assert (
                    node.get(key) is None
                ), f"{'/'.join(map(str, path))} carries {key} for {owner}"

    def test_price_variance_sides_are_withheld_unless_they_are_ours(self, cpcl):
        for row in cpcl["procurement"]["price_variance"]["rows"]:
            assert row["your_unit_price"] > row["market_band"]["mean"]
            assert row["market_band"]["n"] >= 2

    def test_price_flags_count_only_our_own_and_state_the_rule(self, cpcl, db_module):
        """The flag is the Opportunity page's stated rule applied to CPCL's
        own average; another buyer's flag is a price and stays out."""
        pv = cpcl["procurement"]["price_variance"]
        assert "not a finding" in pv["anomaly_rule"]
        ours = sum(
            1
            for row in opportunity.price_variance(db_module, REGISTRAR, limit=10**6)["rows"]
            for p in row["prices"]
            if p["cpse"] == "CPCL" and "anomaly" in p
        )
        assert pv["materials_far_above_the_others"] == ours
        for row in pv["rows"]:
            assert row["far_above_the_others"] is None or row["far_above_the_others"] > 1.5

    def test_transfers_in_never_carry_the_holders_price(self, cpcl):
        for row in cpcl["inventory"]["transfers"]["as_receiver"]["rows"]:
            assert row["from_cpse"] != "CPCL"
            assert "unit_value" not in row
            assert row["value"] is None or row["valued_at"]

    def test_the_other_cpses_exact_prices_are_absent_from_json_and_html(self, cpcl, db_module):
        """The registrar's own view of the same materials names each buyer's
        average price; none that the band does not already give away (its
        edges and mean) may appear in the document."""
        html = reports.render_html(cpcl)
        blob = json.dumps(cpcl)
        registrar_prices: dict[int, list[tuple[str, float]]] = {}
        for row in opportunity.price_variance(db_module, REGISTRAR, limit=10**6)["rows"]:
            registrar_prices[row["cluster_id"]] = [
                (p["cpse"], p["unit_price"]) for p in row["prices"]
            ]
        for row in opportunity.joint_tender_candidates(db_module, REGISTRAR, limit=10**6)[
            "candidates"
        ]:
            registrar_prices.setdefault(row["cluster_id"], []).extend(
                (p["cpse"], p["unit_price"]) for p in row["per_cpse"]
            )
        listed = (
            cpcl["procurement"]["price_variance"]["rows"]
            + cpcl["procurement"]["joint_tenders"]["rows"]
        )
        checked = 0
        for row in listed:
            band = row["market_band"]
            for cpse, exact in registrar_prices.get(row["cluster_id"], []):
                if cpse == "CPCL" or exact in (band["min"], band["max"], band["mean"]):
                    continue
                checked += 1
                assert f'"cpse": "{cpse}", "unit_price": {exact}' not in blob
                assert f"{exact:,.2f}" not in html and f"\u20b9{exact:,.0f}" not in html
        if checked == 0:
            # A two-CPSE estate has two-wide bands, whose edges are the two
            # prices by construction; that is the band's design (§0.9b), and
            # there is no third price for this test to look for.
            assert listed and all(row["market_band"]["n"] == 2 for row in listed)

    def test_the_html_is_self_contained_and_flags_the_synthetic_estate(self, cpcl):
        html = reports.render_html(cpcl)
        assert html.startswith("<!doctype html>")
        assert "http://" not in html and "https://" not in html
        assert "@page" in html and "synthetic" in html
        assert "Assumption." in html and "capturable" in html
        assert "IOCL" in html  # the other CPSE is named; only its price is withheld


class TestApi:
    def test_the_registrar_reads_any_cpse(self, as_registrar, pipeline_run):
        body = as_registrar.get("/api/reports/cpse/IOCL").json()
        assert body["cpse"]["code"] == "IOCL"
        assert body["visibility"]["role"] == "steward" and body["visibility"]["cpse"] == "IOCL"

    def test_html_format_is_a_page(self, as_registrar, pipeline_run):
        response = as_registrar.get("/api/reports/cpse/CPCL?format=html")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "Chennai Petroleum" in response.text

    def test_a_steward_reads_their_own_and_not_anothers(self, as_steward, pipeline_run):
        assert as_steward.get("/api/reports/cpse/CPCL").status_code == 200
        refused = as_steward.get("/api/reports/cpse/IOCL")
        assert refused.status_code == 403
        assert "CPCL" in refused.json()["detail"]

    def test_a_viewer_reads_none(self, as_viewer, pipeline_run):
        assert as_viewer.get("/api/reports/cpse/CPCL").status_code == 403
        assert as_viewer.post("/api/reports/cpse/CPCL/send", json={"to": None}).status_code == 403

    def test_a_stranger_is_turned_away(self, client, pipeline_run):
        assert client.get("/api/reports/cpse/CPCL").status_code == 401

    def test_an_unknown_cpse_is_404(self, as_registrar, pipeline_run):
        assert as_registrar.get("/api/reports/cpse/NOPE").status_code == 404

    def test_the_listing_carries_contact_and_last_sent(self, as_registrar, pipeline_run):
        body = as_registrar.get("/api/reports").json()
        codes = {row["code"] for row in body["cpses"]}
        assert {"CPCL", "IOCL"} <= codes
        cpcl = next(row for row in body["cpses"] if row["code"] == "CPCL")
        assert cpcl["contact_email"] == "materials@cpcl.example"
        assert body["delivery"] == "outbox"

    def test_a_steward_lists_only_their_own(self, as_steward, pipeline_run):
        body = as_steward.get("/api/reports").json()
        assert [row["code"] for row in body["cpses"]] == ["CPCL"]


class TestDelivery:
    def test_send_writes_an_eml_with_html_and_json_attached(
        self, as_registrar, pipeline_run, outbox, db
    ):
        from app.models import AuditEvent

        before = db.execute(
            select(func.count(AuditEvent.id)).where(AuditEvent.action == "report.sent")
        ).scalar()
        response = as_registrar.post("/api/reports/cpse/CPCL/send", json={"to": None})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["mode"] == "outbox" and body["to"] == ["materials@cpcl.example"]
        assert "outbox" in body["note"]
        path = outbox / body["path"].split("/")[-1]
        assert path.exists() and path.suffix == ".eml"

        message = email.message_from_bytes(path.read_bytes(), policy=policy.default)
        assert message["To"] == "materials@cpcl.example"
        assert "CPCL" in message["Subject"]
        html_part = message.get_body(preferencelist=("html",))
        assert html_part is not None and "Chennai Petroleum" in html_part.get_content()
        attachments = list(message.iter_attachments())
        assert len(attachments) == 1 and attachments[0].get_filename().endswith(".json")
        attached = json.loads(attachments[0].get_content())
        assert attached["cpse"]["code"] == "CPCL"

        db.expire_all()
        after = db.execute(
            select(func.count(AuditEvent.id)).where(AuditEvent.action == "report.sent")
        ).scalar()
        assert after == before + 1
        event = (
            db.execute(
                select(AuditEvent)
                .where(AuditEvent.action == "report.sent")
                .order_by(AuditEvent.seq.desc())
            )
            .scalars()
            .first()
        )
        payload = json.loads(event.payload_json)
        assert payload["cpse"] == "CPCL" and payload["mode"] == "outbox"
        assert payload["sha256"] == body["sha256"] and len(payload["sha256"]) == 64
        assert event.entity == "cpse:CPCL" and event.user == "registrar@min.gov.in"

        listing = as_registrar.get("/api/reports").json()
        sent = next(row for row in listing["cpses"] if row["code"] == "CPCL")["last_sent"]
        assert sent["mode"] == "outbox" and sent["to"] == ["materials@cpcl.example"]

    def test_explicit_recipients_win(self, as_steward, pipeline_run, outbox):
        body = as_steward.post(
            "/api/reports/cpse/CPCL/send", json={"to": ["a@x.example", "b@x.example"]}
        ).json()
        assert body["to"] == ["a@x.example", "b@x.example"]

    def test_a_cpse_without_a_contact_is_422(self, as_registrar, pipeline_run, outbox, db):
        cpse = db.execute(select(Cpse).where(Cpse.code == "IOCL")).scalar_one()
        original = cpse.contact_email
        cpse.contact_email = None
        db.commit()
        try:
            response = as_registrar.post("/api/reports/cpse/IOCL/send", json={"to": None})
            assert response.status_code == 422
            assert "contact email" in response.json()["detail"]
        finally:
            cpse.contact_email = original
            db.commit()

    def test_deliver_by_smtp_when_configured(self, cpcl, monkeypatch):
        from app.config import get_settings

        sent = {}

        class FakeSmtp:
            def __init__(self, host, port, timeout=None):
                sent["host"], sent["port"] = host, port

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def starttls(self):
                sent["tls"] = True

            def login(self, user, password):
                sent["login"] = (user, password)

            def send_message(self, msg):
                sent["message"] = msg

        settings = get_settings()
        monkeypatch.setattr(settings, "saman_smtp_host", "relay.example")
        monkeypatch.setattr(settings, "saman_smtp_user", "saman")
        monkeypatch.setattr(settings, "saman_smtp_password", "secret")
        monkeypatch.setattr(reports.smtplib, "SMTP", FakeSmtp)
        result = reports.deliver(cpcl, reports.render_html(cpcl), ["steward@cpcl.example"])
        assert result["mode"] == "smtp" and result["path"] is None
        assert sent["host"] == "relay.example" and sent["port"] == 587 and sent["tls"]
        assert sent["login"] == ("saman", "secret")
        assert sent["message"]["To"] == "steward@cpcl.example"

    def test_no_recipient_is_an_error(self, cpcl, outbox):
        with pytest.raises(ValueError):
            reports.deliver(cpcl, "<html></html>", [" "])


class TestAdmin:
    def test_the_contact_email_is_set_through_the_cpse_patch(self, as_registrar, pipeline_run):
        response = as_registrar.patch(
            "/api/cpses/CPCL", json={"contact_email": "Stores@CPCL.example"}
        )
        assert (
            response.status_code == 200
            and response.json()["contact_email"] == "stores@cpcl.example"
        )
        assert (
            as_registrar.patch(
                "/api/cpses/CPCL", json={"contact_email": "not-an-address"}
            ).status_code
            == 422
        )
        listed = next(
            row for row in as_registrar.get("/api/cpses").json()["cpses"] if row["code"] == "CPCL"
        )
        assert listed["contact_email"] == "stores@cpcl.example"
        as_registrar.patch("/api/cpses/CPCL", json={"contact_email": "materials@cpcl.example"})

    def test_a_steward_may_not_set_it(self, as_steward, pipeline_run):
        assert (
            as_steward.patch("/api/cpses/CPCL", json={"contact_email": "x@y.example"}).status_code
            == 403
        )

    def test_the_cli_writes_the_files(self, pipeline_run, tmp_path):
        from app.cli import main

        assert main(["report", "--cpse", "CPCL", "--out", str(tmp_path)]) == 0
        html = tmp_path / "saman-report-CPCL-"
        written = sorted(p.name for p in tmp_path.iterdir())
        assert len(written) == 2 and written[0].endswith(".html") and written[1].endswith(".json")
        assert str(html.name) in written[0]
        assert main(["report"]) == 2


class TestMinistryRollup:
    def test_every_cpse_on_one_page_with_money_in_bands(self, as_registrar, pipeline_run):
        body = as_registrar.get("/api/reports/rollup").json()
        assert body["kind"] == "rollup"
        codes = [row["cpse"] for row in body["cpses"]]
        assert len(codes) == body["totals"]["cpses"] >= 2
        for row in body["cpses"]:
            # Money never appears as a figure beside a name.
            assert set(row) & {"spend_inr", "saving_inr", "estimated_saving_yours_inr"} == set()
            assert row["spend_quarter"].endswith("quarter")
            assert row["saving_quarter"].endswith("quarter")
        assert body["totals"]["rows"] == sum(r["rows"] for r in body["cpses"])
        assert body["totals"]["estimated_saving_inr"] >= 0
        assert "quarter among its peers" in body["redaction_note"]

    def test_the_html_prints_and_the_steward_is_refused(self, client, pipeline_run):
        client.post("/api/auth/login", json={"email": "registrar@min.gov.in", "password": "demo"})
        html = client.get("/api/reports/rollup?format=html")
        assert html.status_code == 200 and "Ministry roll-up" in html.text
        assert "quarter" in html.text
        client.post("/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"})
        assert client.get("/api/reports/rollup").status_code == 403


class TestDormantCodes:
    def test_the_report_suggests_dormant_duplicate_codes_with_evidence(self, as_steward, pipeline_run):
        body = as_steward.get("/api/reports/cpse/CPCL").json()
        retire = body["retirement"]
        assert retire["rule_months"] == 24
        assert retire["count"] <= retire["considered"]
        for row in retire["examples"]:
            assert row["legacy_code"] and row["other_names"] >= 1
            assert set(row) >= {"survives_as", "last_purchase", "last_movement"}
        assert "never a deletion" in retire["note"]
        if retire["count"]:
            assert any(a["key"] == "retire_dormant" for a in body["actions"])
        html = as_steward.get("/api/reports/cpse/CPCL?format=html").text
        assert "Dormant codes to retire" in html
