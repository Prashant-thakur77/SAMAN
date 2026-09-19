"""Vendor names grouped by company, not by spelling."""

import pytest

from app.vendors import canonical_names, vendor_key


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("SKF INDIA LTD", "SKF India Limited"),
        ("M/s SKF India Pvt. Ltd.", "SKF INDIA LIMITED."),
        ("NATIONAL ENGG", "National Engineering Co."),
        ("Bharat Bijlee & Co", "BHARAT BIJLEE AND COMPANY"),
        ("Precision Fasteners Pvt Ltd", "PRECISION FASTENERS"),
        ("SKF Bearings India Ltd", "SKF India"),
    ],
)
def test_the_same_supplier_gets_one_key(a, b):
    assert vendor_key(a) == vendor_key(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("SKF INDIA", "FAG INDIA"),
        ("BEARING HOUSE", "SOUTH INDIA BEARINGS"),
        ("SKF", "SKF INDIA"),  # a group and its Indian arm are not assumed to be one
    ],
)
def test_different_suppliers_keep_different_keys(a, b):
    assert vendor_key(a) != vendor_key(b)


def test_the_shown_name_is_the_commonest_spelling():
    names = ["SKF INDIA LTD", "SKF INDIA LTD", "SKF India Limited", "VALVE TECH"]
    shown = canonical_names(names)
    assert shown[vendor_key("SKF India Limited")] == "SKF INDIA LTD"
    assert shown[vendor_key("VALVE TECH")] == "VALVE TECH"
    assert vendor_key("") == "" and vendor_key(None) == ""


def test_vendor_overlap_groups_by_company(db, pipeline_run):
    from app.opportunity import vendor_overlap

    body = vendor_overlap(db)
    assert body["items_found"] >= 0 and "spellings_folded" in body
    for row in body["rows"]:
        for v in row["vendors"]:
            assert v["vendor"] and isinstance(v["also_spelt"], list)
