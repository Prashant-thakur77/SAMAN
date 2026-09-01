"""Known OEM brands per class, used for brand extraction and blocking keys."""

BRANDS_BY_CLASS: dict[str, tuple[str, ...]] = {
    "bearing.ball.deep_groove": ("SKF", "FAG", "NSK", "NTN", "TIMKEN", "KOYO"),
    "valve.gate": ("KITZ", "AUDCO", "BDK", "KSB", "FLOWSERVE", "LT"),
    "gasket.spiral_wound": ("LEADER", "CHAMPION", "GARLOCK", "FLEXITALLIC"),
    "pipe.seamless": ("JINDAL", "TATA", "MSL", "ISMT"),
    "fastener.bolt.hex": ("UNBRAKO", "TVS", "SUNDRAM", "APL"),
    "cable.power": ("POLYCAB", "HAVELLS", "FINOLEX", "KEI"),
    "chemical.reagent": ("MERCK", "RANKEM", "FISHER", "THERMO"),
    "ppe.helmet": ("KARAM", "VENUS", "3M", "HONEYWELL"),
}

ALL_BRANDS: tuple[str, ...] = tuple(
    sorted({b for brands in BRANDS_BY_CLASS.values() for b in brands})
)

#: Canonical alias -> preferred brand spelling (§2D "brand/OEM to the canonical alias").
BRAND_ALIASES: dict[str, str] = {
    "SKF INDIA": "SKF",
    "FAG SCHAEFFLER": "FAG",
    "SCHAEFFLER": "FAG",
    "NSK LTD": "NSK",
    "L&T": "LT",
    "LARSEN": "LT",
    "MAHARASHTRA SEAMLESS": "MSL",
    "3M INDIA": "3M",
}
