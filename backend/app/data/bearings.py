"""ISO deep-groove ball bearing dimension table.

A designation like 6205-2Z encodes its own geometry: series 62, bore code 05
(= 25 mm), seal ZZ. Bore follows a rule; outer diameter and width come from the
standard series table below. Real material-master systems carry exactly such a
table, and it is what lets SAMAN match "6205-2Z" against a description that
spells the dimensions out instead (spec §2B evidence source 1).

Keyed by 4-digit designation -> (bore_mm, outer_dia_mm, width_mm).
"""

DEEP_GROOVE_DIMS: dict[str, tuple[float, float, float]] = {
    # 60xx — extra light
    "6000": (10, 26, 8), "6001": (12, 28, 8), "6002": (15, 32, 9),
    "6003": (17, 35, 10), "6004": (20, 42, 12), "6005": (25, 47, 12),
    "6006": (30, 55, 13), "6007": (35, 62, 14), "6008": (40, 68, 15),
    "6009": (45, 75, 16), "6010": (50, 80, 16),
    # 62xx — light
    "6200": (10, 30, 9), "6201": (12, 32, 10), "6202": (15, 35, 11),
    "6203": (17, 40, 12), "6204": (20, 47, 14), "6205": (25, 52, 15),
    "6206": (30, 62, 16), "6207": (35, 72, 17), "6208": (40, 80, 18),
    "6209": (45, 85, 19), "6210": (50, 90, 20),
    # 63xx — medium
    "6300": (10, 35, 11), "6301": (12, 37, 12), "6302": (15, 42, 13),
    "6303": (17, 47, 14), "6304": (20, 52, 15), "6305": (25, 62, 17),
    "6306": (30, 72, 19), "6307": (35, 80, 21), "6308": (40, 90, 23),
    "6309": (45, 100, 25), "6310": (50, 110, 27),
    # larger bores, same three series
    "6011": (55, 90, 18), "6012": (60, 95, 18), "6013": (65, 100, 18),
    "6014": (70, 110, 20), "6015": (75, 115, 20), "6016": (80, 125, 22),
    "6017": (85, 130, 22), "6018": (90, 140, 24), "6019": (95, 145, 24),
    "6020": (100, 150, 24),
    "6211": (55, 100, 21), "6212": (60, 110, 22), "6213": (65, 120, 23),
    "6214": (70, 125, 24), "6215": (75, 130, 25), "6216": (80, 140, 26),
    "6217": (85, 150, 28), "6218": (90, 160, 30), "6219": (95, 170, 32),
    "6220": (100, 180, 34),
    "6311": (55, 120, 29), "6312": (60, 130, 31), "6313": (65, 140, 33),
    "6314": (70, 150, 35), "6315": (75, 160, 37), "6316": (80, 170, 39),
    "6317": (85, 180, 41), "6318": (90, 190, 43), "6319": (95, 200, 45),
    "6320": (100, 215, 47),
}

#: Seal/shield suffixes seen across manufacturers, mapped to our enum.
SEAL_SUFFIXES: dict[str, str] = {
    "2Z": "ZZ", "ZZ": "ZZ", "2ZR": "ZZ", "Z": "ZZ", "2ZN": "ZZ",
    "2RS": "2RS", "RS": "2RS", "2RS1": "2RS", "DDU": "2RS", "2RSR": "2RS",
    "": "OPEN", "C3": "OPEN", "OPEN": "OPEN",
}


def bore_from_code(code: str) -> float | None:
    """ISO bore code -> millimetres. 00=10, 01=12, 02=15, 03=17, then code x 5."""
    if not code.isdigit() or len(code) != 2:
        return None
    n = int(code)
    special = {0: 10.0, 1: 12.0, 2: 15.0, 3: 17.0}
    return special.get(n, float(n * 5)) if n <= 96 else None
