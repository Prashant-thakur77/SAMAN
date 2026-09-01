"""Domain abbreviation dictionary — spec §2 M2 requires at least 120 entries.

Kept as data in its own module so `normalize.py` stays readable and a steward
can extend it without touching pipeline code.

Expansion is applied on WHOLE TOKENS only, so "SS316" is never mangled into
"STAINLESS STEEL316" by the "SS" entry.
"""

# --- nouns and equipment ---------------------------------------------------
NOUNS = {
    "BRG": "BEARING", "BRNG": "BEARING", "BEARNG": "BEARING", "BRGS": "BEARING",
    "VLV": "VALVE", "VV": "VALVE", "VALV": "VALVE",
    "GSKT": "GASKET", "GSK": "GASKET", "GASKT": "GASKET",
    "PIP": "PIPE", "PP": "PIPE", "TUB": "TUBE",
    "BLT": "BOLT", "NT": "NUT", "WSHR": "WASHER", "WSR": "WASHER", "STD": "STUD",
    "SCR": "SCREW", "SCRW": "SCREW",
    "CBL": "CABLE", "CBLE": "CABLE", "WR": "WIRE",
    "HLMT": "HELMET", "GLV": "GLOVE", "GOG": "GOGGLE",
    "FLG": "FLANGE", "ELB": "ELBOW", "RED": "REDUCER", "CPLG": "COUPLING",
    "BSH": "BUSH", "SPRG": "SPRING", "SHFT": "SHAFT", "IMPLR": "IMPELLER",
    "MOT": "MOTOR", "PMP": "PUMP", "CMPR": "COMPRESSOR", "FLTR": "FILTER",
    "ASSY": "ASSEMBLY", "EQPT": "EQUIPMENT", "INSTR": "INSTRUMENT",
    "CONN": "CONNECTOR", "TERM": "TERMINAL", "SWG": "SPIRAL WOUND GASKET",
    "ORING": "O RING", "SEAL": "SEAL", "BRKT": "BRACKET", "CVR": "COVER",
}

# --- materials -------------------------------------------------------------
MATERIALS = {
    "SS": "STAINLESS STEEL", "S.S": "STAINLESS STEEL", "S.S.": "STAINLESS STEEL",
    "STNLS": "STAINLESS STEEL", "STAINLESS": "STAINLESS STEEL",
    "MS": "MILD STEEL", "M.S": "MILD STEEL", "M.S.": "MILD STEEL",
    "CS": "CARBON STEEL", "C.S": "CARBON STEEL", "C.S.": "CARBON STEEL",
    "CI": "CAST IRON", "C.I": "CAST IRON", "DI": "DUCTILE IRON",
    "GI": "GALVANISED IRON", "G.I": "GALVANISED IRON",
    "AL": "ALUMINIUM", "ALU": "ALUMINIUM", "ALUM": "ALUMINIUM",
    "CU": "COPPER", "BRS": "BRASS", "BRZ": "BRONZE",
    "PTFE": "PTFE", "GRPH": "GRAPHITE", "GRAPH": "GRAPHITE",
    "RBR": "RUBBER", "NBR": "NITRILE RUBBER", "EPDM": "EPDM",
    "HDPE": "HDPE", "LDPE": "LDPE", "FRP": "FRP", "ABS": "ABS",
    "CAF": "COMPRESSED ASBESTOS FIBRE",
}

# --- dimensions and descriptors -------------------------------------------
DESCRIPTORS = {
    "DIA": "DIAMETER", "DIAM": "DIAMETER", "OD": "OUTER DIAMETER",
    "ID": "INNER DIAMETER", "NB": "NOMINAL BORE", "NPS": "NOMINAL PIPE SIZE",
    "THK": "THICKNESS", "THKNS": "THICKNESS", "LG": "LENGTH", "LGTH": "LENGTH",
    "WD": "WIDTH", "WDTH": "WIDTH", "HT": "HEIGHT", "HGT": "HEIGHT",
    "SZ": "SIZE", "HEX": "HEXAGON", "HEXA": "HEXAGON", "SQ": "SQUARE",
    "RD": "ROUND", "RND": "ROUND", "CYL": "CYLINDRICAL",
    "LH": "LEFT HAND", "RH": "RIGHT HAND",
    "MAX": "MAXIMUM", "MIN": "MINIMUM", "NOM": "NOMINAL", "APPROX": "APPROXIMATE",
    "TEMP": "TEMPERATURE", "PRESS": "PRESSURE", "PR": "PRESSURE",
    "CL": "CLASS", "GRD": "GRADE", "TYP": "TYPE",
    "STD": "STANDARD", "SPEC": "SPECIFICATION",
    "W/": "WITH", "W/O": "WITHOUT",
}

# --- valves, fittings, piping ---------------------------------------------
PIPING = {
    "GT": "GATE", "GLB": "GLOBE", "CHK": "CHECK", "BFLY": "BUTTERFLY",
    "NRV": "NON RETURN VALVE", "SRV": "SAFETY RELIEF VALVE",
    "FLGD": "FLANGED", "THRD": "THREADED", "THD": "THREADED",
    "BW": "BUTTWELD", "SW": "SOCKETWELD", "SCRD": "SCREWED",
    "SCH": "SCHEDULE",
    "SMLS": "SEAMLESS", "ERW": "ERW", "RF": "RAISED FACE", "FF": "FLAT FACE",
    "RTJ": "RING TYPE JOINT", "WN": "WELD NECK", "SO": "SLIP ON", "BLND": "BLIND",
}

# --- electrical ------------------------------------------------------------
ELECTRICAL = {
    "COND": "CONDUCTOR", "ARM": "ARMOURED", "ARMD": "ARMOURED",
    "UNARM": "UNARMOURED", "XLPE": "XLPE", "PVC": "PVC",
    "SQMM": "SQUARE MILLIMETRE", "SQ.MM": "SQUARE MILLIMETRE",
    "KV": "KILOVOLT", "VLT": "VOLT", "AMP": "AMPERE", "HZ": "HERTZ",
    "PH": "PHASE", "ELEC": "ELECTRICAL", "CORE": "CORE", "MCB": "MCB", "MCCB": "MCCB",
}

# --- chemicals -------------------------------------------------------------
CHEMICALS = {
    "NAOH": "SODIUM HYDROXIDE", "HCL": "HYDROCHLORIC ACID",
    "H2SO4": "SULPHURIC ACID", "HNO3": "NITRIC ACID",
    "CACL2": "CALCIUM CHLORIDE", "NACL": "SODIUM CHLORIDE",
    "MEOH": "METHANOL", "ETOH": "ETHANOL", "IPA": "ISOPROPYL ALCOHOL",
    "CAUSTIC": "SODIUM HYDROXIDE", "SODA": "SODIUM CARBONATE",
    "LR": "LABORATORY REAGENT", "AR": "ANALYTICAL REAGENT",
    "TECH": "TECHNICAL", "ANHY": "ANHYDROUS", "CONC": "CONCENTRATED",
}

# --- safety / PPE ----------------------------------------------------------
SAFETY = {
    "SFTY": "SAFETY", "PROT": "PROTECTIVE", "IND": "INDUSTRIAL",
    "RATCH": "RATCHET", "PINLK": "PINLOCK", "HDHT": "HARD HAT",
}

# --- general MRO -----------------------------------------------------------
GENERAL = {
    "MTL": "MATERIAL", "QTY": "QUANTITY", "MFR": "MANUFACTURER",
    "MFG": "MANUFACTURING", "REPL": "REPLACEMENT", "SPR": "SPARE",
    "SER": "SERIES", "MDL": "MODEL", "PN": "PART NUMBER",
    "PART": "PART", "NO": "NUMBER", "REF": "REFERENCE",
    "MECH": "MECHANICAL", "HYD": "HYDRAULIC", "PNEU": "PNEUMATIC",
    "INSUL": "INSULATION", "LUBR": "LUBRICANT", "GRS": "GREASE",
    "ACC": "ACCESSORY", "KIT": "KIT", "SET": "SET",
}

#: Abbreviation -> canonical expansion, applied token-wise by normalize.py.
ABBREVIATIONS: dict[str, str] = {
    **NOUNS,
    **MATERIALS,
    **DESCRIPTORS,
    **PIPING,
    **ELECTRICAL,
    **CHEMICALS,
    **SAFETY,
    **GENERAL,
}

# --- Hindi domain terms ----------------------------------------------------
# Applied BEFORE character transliteration so common domain words land on the
# exact English term rather than a phonetic approximation (spec §2A.1:
# "बेयरिंग 6205" must match "BEARING 6205" even on the TF-IDF fallback path).
HINDI_TERMS: dict[str, str] = {
    "बेयरिंग": "BEARING", "बियरिंग": "BEARING", "बेअरिंग": "BEARING",
    "वाल्व": "VALVE", "वॉल्व": "VALVE", "वाल्ब": "VALVE",
    "गैसकेट": "GASKET", "गास्केट": "GASKET",
    "पाइप": "PIPE", "पाईप": "PIPE", "नली": "PIPE",
    "बोल्ट": "BOLT", "नट": "NUT", "वॉशर": "WASHER", "पेंच": "SCREW",
    "केबल": "CABLE", "तार": "WIRE", "केबिल": "CABLE",
    "हेलमेट": "HELMET", "टोपी": "HELMET", "दस्ताने": "GLOVE", "चश्मा": "GOGGLE",
    "इस्पात": "STEEL", "स्टील": "STEEL", "लोहा": "IRON", "तांबा": "COPPER",
    "पीतल": "BRASS", "एल्युमिनियम": "ALUMINIUM",
    "रसायन": "CHEMICAL", "अम्ल": "ACID", "तेल": "OIL", "ग्रीस": "GREASE",
    "सुरक्षा": "SAFETY", "औद्योगिक": "INDUSTRIAL",
    "पंप": "PUMP", "मोटर": "MOTOR", "फ्लैंज": "FLANGE", "गेट": "GATE",
    "सील": "SEAL", "स्प्रिंग": "SPRING", "गोल": "ROUND",
    "आकार": "SIZE", "लंबाई": "LENGTH", "चौड़ाई": "WIDTH", "मोटाई": "THICKNESS",
    "व्यास": "DIAMETER", "दबाव": "PRESSURE", "तापमान": "TEMPERATURE",
    "संख्या": "NUMBER", "नग": "EA", "मीटर": "METRE", "किलो": "KILOGRAM",
    "लीटर": "LITRE", "सेट": "SET", "डिब्बा": "BOX",
}
