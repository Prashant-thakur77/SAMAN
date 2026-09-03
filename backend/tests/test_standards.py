"""Public classification codes on the golden record: every class carries a
UNSPSC code and, where the class alone determines it, an HSN heading; both are
served with the item and the cluster, each with the level it was assigned at."""

import pytest

from app.taxonomy import HSN_LEVELS, UNSPSC_LEVELS, _parse_standards, real_classes


class TestSchema:
    def test_every_class_maps_to_unspsc(self):
        for schema in real_classes():
            unspsc = schema.standards.get("unspsc")
            assert unspsc, schema.code
            assert len(unspsc["code"]) == 8 and unspsc["level"] in UNSPSC_LEVELS

    def test_hsn_is_a_heading_or_subheading_when_present(self):
        with_hsn = [s for s in real_classes() if "hsn" in s.standards]
        assert len(with_hsn) >= 7
        for schema in with_hsn:
            hsn = schema.standards["hsn"]
            assert len(hsn["code"]) in (4, 6, 8) and hsn["level"] in HSN_LEVELS

    def test_chemicals_do_not_get_a_class_level_hsn(self):
        """The heading depends on the substance; a class default would be a lie."""
        chem = next(s for s in real_classes() if s.code == "chemical.reagent")
        assert "hsn" not in chem.standards

    def test_a_bad_code_is_a_data_error(self):
        with pytest.raises(ValueError):
            _parse_standards({"unspsc": {"code": "3117", "title": "x", "level": "class"}})
        with pytest.raises(ValueError):
            _parse_standards({"hsn": {"code": "8482", "title": "x", "level": "commodity"}})


class TestServed:
    def test_the_item_carries_its_codes(self, client, pipeline_run):
        item = client.get("/api/items/1").json()
        assert "standards" in item
        if item["class_code"] != "unclassified":
            assert item["standards"]["unspsc"]["level"] in UNSPSC_LEVELS

    def test_the_cluster_carries_its_codes(self, client, pipeline_run):
        cluster_id = client.get("/api/items/1").json()["cluster_id"]
        body = client.get(f"/api/clusters/{cluster_id}").json()
        assert body["standards"] == client.get("/api/items/1").json()["standards"]
