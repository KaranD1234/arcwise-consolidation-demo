"""Meritt Hardware Group -- the world where almost nothing derives.

A fictional Spanish importer of fixings, fittings and hand tools, buying out of
Shenzhen into Valencia and Barcelona. Invented from scratch, and deliberately unlike
any live engagement.

Meritt is the hard case, and it is the one worth rehearsing most. Its forwarder
bundles twice over:

*   origin arrives as one all-in line, code 1630
*   **ocean freight and destination delivery share a single line**, code 1300, billed
    port to door

That second bundle is the one that hurts. Consolidation changes the freight leg and
leaves the delivery leg alone, so a figure covering both cannot inform either. Exactly
one component still derives from this file -- destination terminal and port charges,
which the forwarder happens to itemise -- and everything else has to come off a rate
card or be quoted.

That makes the References board mostly red on arrival, which is the correct answer for
a file like this and is far more useful to show than a board that goes green because we
quietly reached for a benchmark. The prospect whose data looks like Meritt's is the
prospect who most needs to know what we will and will not claim.

Note what does NOT degrade: the file is still charge-line grain, still carries the
``-related-`` sentinel and the blank-equipment mess, and still reconciles to the cent.
Meritt is a poor file, not a broken one -- so the calibration control, the ledger
checks and the resolution queue all still have real work to do.
"""

SCENARIO_ID = "meritt"
CLIENT_SHORT = "Meritt"
SUMMARY = "Origin bundled, and freight billed port-to-door on a single line."
SEED = 20260819
N_GROUPS = 520
INVOICE_PREFIX = "MH"

# ----------------------------------------------------------------------------------
# Client identity
# ----------------------------------------------------------------------------------
CLIENT_COMPANY = "Meritt Hardware Group S.A. (ES)"
BILL_TO_PARTY = "Meritt Hardware Group S.A. - Valencia"
CONSIGNEE_BY_COUNTRY = {
    "Spain": "Meritt Hardware Group S.A. - Valencia",
    "Portugal": "Meritt Ferragens Lda. - Lisboa",
    "France": "Meritt Quincaillerie SARL - Perpignan",
}
INVOICE_CLERKS = [
    "Alba Ferreiro", "Guillem Ortiz", "Nuria Bastida",
    "Rui Camposinhos", "Xavier Mendoza",
]

# A Spanish importer bills almost entirely in euro.
CURRENCY_WEIGHTS = {"EUR": 0.74, "USD": 0.22, "GBP": 0.04}

# ----------------------------------------------------------------------------------
# Origins. A single-origin network, which is itself a difference worth showing: the
# consolidation decision turns entirely on destination geography here.
# ----------------------------------------------------------------------------------
ORIGINS = {
    "Shenzhen, China": {"cfs": "Shenzhen", "country": "China"},
}

ORIGIN_WEIGHTS = {
    "Shenzhen, China": 1.0,
}

TRANSSHIP = {
    "Shenzhen": {"share": 0.19, "ports": ["Singapore", "Tanger Med, Morocco"]},
}

# ----------------------------------------------------------------------------------
# Discharge ports, and nominal transit days from origin.
# ----------------------------------------------------------------------------------
PORTS = {
    "Valencia, Spain": {"country": "Spain", "transit": {"Shenzhen": 27}},
    "Barcelona, Spain": {"country": "Spain", "transit": {"Shenzhen": 29}},
}

POD_WEIGHTS = {
    "Valencia, Spain": 0.58,
    "Barcelona, Spain": 0.42,
}

# Valencia serves four sites, so four weights are needed.
SITE_WEIGHTS = [0.41, 0.27, 0.19, 0.13]

# ----------------------------------------------------------------------------------
# Delivery sites.
#
# ``raw`` holds the strings that actually appear in the charge-line file. Anything
# beyond the first entry is drift the resolution queue has to deal with. ``queue``
# marks a variant that is deliberately hard, so it escalates instead of
# auto-resolving:
#   alias_hard  -- same physical site, but the string shares little with the canonical
#   not_a_place -- the address field holds a placeholder, not a location
#   county_only -- a region with no town, so the site cannot be pinned precisely
# ----------------------------------------------------------------------------------
DELIVERY_SITES = [
    {
        "site_id": "ES_RIBARROJA", "site": "Ribarroja, ES", "country": "Spain",
        "pod": "Valencia, Spain",
        "raw": [
            ("Turia Almacenes Logisticos S.L. - Ribarroja", None),
            ("Turia Almacenes Logisticos SL - Riba-roja de Turia", None),
        ],
    },
    {
        "site_id": "ES_ALICANTE", "site": "Alicante, ES", "country": "Spain",
        "pod": "Valencia, Spain",
        # The second string is the same operator as ES_RIBARROJA at a different town --
        # a Valencian 3PL with two depots. It must NOT be merged: this is the decision
        # only a human can take, and every world carries one.
        "raw": [
            ("Costa Blanca Distribucion S.A. - Alicante", None),
            ("Turia Almacenes Logisticos S.L. - Alicante", "multi_city"),
        ],
    },
    {
        "site_id": "ES_MADRID", "site": "Madrid, ES", "country": "Spain",
        "pod": "Valencia, Spain",
        "raw": [
            ("Getafe Plataforma Logistica - Madrid", None),
            # The client's own name leads the string, so it looks nothing like the
            # canonical form. Same warehouse.
            ("Meritt Hardware c/o Getafe Plataforma - Madrid", "alias_hard"),
        ],
    },
    {
        "site_id": "PT_LISBOA", "site": "Lisboa, PT", "country": "Portugal",
        "pod": "Valencia, Spain",
        "raw": [("Tejo Armazenagem e Distribuicao Lda - Lisboa ", None)],
    },
    {
        "site_id": "ES_GRANOLLERS", "site": "Granollers, ES", "country": "Spain",
        "pod": "Barcelona, Spain",
        "raw": [
            ("Valles Oriental Logistica S.L. - Granollers", None),
            # The address field holds a placeholder. The escalation that genuinely
            # needs a human.
            ("Valles Oriental Logistica S.L. - TBC", "not_a_place"),
        ],
    },
    {
        "site_id": "ES_ZARAGOZA", "site": "Zaragoza, ES", "country": "Spain",
        "pod": "Barcelona, Spain",
        "raw": [("Plaza Zaragoza Servicios Logisticos - Zaragoza", None)],
    },
    {
        "site_id": "FR_PERPIGNAN", "site": "Perpignan, FR", "country": "France",
        "pod": "Barcelona, Spain",
        "raw": [("Roussillon Entrepots SAS - Perpignan", None)],
    },
]

# ----------------------------------------------------------------------------------
# Suppliers.
#
# ``region`` is the true pickup region and is what an origin rate is priced against.
# ``queue: proxy`` marks the supplier recorded at a non-origin office, which has to be
# resolved before it can be costed and has no rate-card row either.
# ----------------------------------------------------------------------------------
SUPPLIERS = [
    # --- Shenzhen catchment -----------------------------------------------------
    {"name": "Shenzhen Baoan Weiheng Fasteners Co., Ltd. - Shenzhen", "cfs": "Shenzhen", "region": "SHENZHEN", "queue": None},
    {"name": "Longgang Yidatong Hand Tools Co., Ltd. - Shenzhen", "cfs": "Shenzhen", "region": "SHENZHEN", "queue": None},
    {"name": "Dongguan Humen Jinhui Hinges Co., Ltd. - Dongguan", "cfs": "Shenzhen", "region": "DONGGUAN", "queue": None},
    {"name": "Changan Ruicheng Precision Screws Co., Ltd. - Dongguan", "cfs": "Shenzhen", "region": "DONGGUAN", "queue": None},
    {"name": "Foshan Shunde Kaiyi Door Hardware Co., Ltd. - Foshan", "cfs": "Shenzhen", "region": "FOSHAN", "queue": None},
    {"name": "Nanhai Chengfeng Aluminium Fittings Co., Ltd. - Foshan", "cfs": "Shenzhen", "region": "FOSHAN", "queue": None},
    {"name": "Zhongshan Guzhen Lighting Accessories Co., Ltd. - Zhongshan", "cfs": "Shenzhen", "region": "FOSHAN", "queue": None},
    {"name": "Huizhou Boluo Tianxin Castings Co., Ltd. - Huizhou", "cfs": "Shenzhen", "region": "DONGGUAN", "queue": None},
    {"name": "Jiangmen Pengjiang Hengli Locksets Co., Ltd. - Jiangmen", "cfs": "Shenzhen", "region": "FOSHAN", "queue": None},
    {"name": "Guangzhou Panyu Sanhe Abrasives Co., Ltd. - Guangzhou", "cfs": "Shenzhen", "region": "FOSHAN", "queue": None},
    {"name": "Shenzhen Pingshan Antai Wire Forms Co., Ltd. - Shenzhen", "cfs": "Shenzhen", "region": "SHENZHEN", "queue": None},
    # Recorded at a Hong Kong buying office; goods leave Shenzhen. No rate-card row.
    {"name": "Meritt Sourcing Asia Ltd. - Singapore", "cfs": "Shenzhen", "region": "SHENZHEN", "queue": "proxy"},
]

# Pickup regions an origin rate can be priced against.
PICKUP_REGIONS = ["SHENZHEN", "DONGGUAN", "FOSHAN"]

# ----------------------------------------------------------------------------------
# The world's true pricing.
#
# Nearly everything is carded, and again that is necessity rather than generosity.
# With origin bundled into 1630 and freight bundled into 1300, the invoices can price
# exactly one component -- destination terminal and port charges -- so the card is the
# only thing standing between this world and an unpriceable model.
#
# What the demo shows on this scenario is therefore a board that arrives almost
# entirely red and goes green on a single upload. That is a genuine product story: the
# engine did not need the client's data to be good, it needed the client to say which
# rates apply, and it was explicit about which was which.
# ----------------------------------------------------------------------------------
TRUE_RATES = {
    # Ocean freight, USD per 40'HC, by (origin CFS, port of discharge). Bundled into
    # code 1300 on the way into the file, so the card is the only place these appear.
    "ocean": {
        ("Shenzhen", "Valencia, Spain"): {"rate": 3540.0, "carded": True},
        ("Shenzhen", "Barcelona, Spain"): {"rate": 3675.0, "carded": True},
    },
    # Destination delivery, USD per container, by (port of discharge, site). Also
    # bundled into code 1300, hence carded throughout.
    "dest": {
        ("Valencia, Spain", "Ribarroja, ES"): {"rate": 615.0, "carded": True},
        ("Valencia, Spain", "Alicante, ES"): {"rate": 890.0, "carded": True},
        ("Valencia, Spain", "Madrid, ES"): {"rate": 1560.0, "carded": True},
        ("Valencia, Spain", "Lisboa, PT"): {"rate": 2340.0, "carded": True},
        ("Barcelona, Spain", "Granollers, ES"): {"rate": 580.0, "carded": True},
        ("Barcelona, Spain", "Zaragoza, ES"): {"rate": 1185.0, "carded": True},
        ("Barcelona, Spain", "Perpignan, FR"): {"rate": 1020.0, "carded": True},
    },
    # Itemised origin components, USD per container, by pickup region. Bundled into
    # code 1630, so likewise carded throughout.
    "exw": {
        "SHENZHEN": {"carded": True, "components": {
            "1631": 430.0, "1632": 275.0, "1633": 40.0, "1634": 34.0,
            "1635": 62.0, "1636": 88.0, "1637": 108.0}},
        "DONGGUAN": {"carded": True, "components": {
            "1631": 560.0, "1632": 275.0, "1633": 40.0, "1634": 34.0,
            "1635": 62.0, "1636": 88.0, "1637": 108.0}},
        "FOSHAN": {"carded": True, "components": {
            "1631": 745.0, "1632": 275.0, "1633": 40.0, "1634": 34.0,
            "1635": 62.0, "1636": 88.0, "1637": 108.0}},
    },
    # Miscellaneous per-shipment charges, USD.
    #
    # These are the only codes Meritt's forwarder itemises, and 1505/1511 are what
    # keeps a single component derivable. No code 1602: no origin road move is billed
    # separately, so the warehouse-to-port leg has no analogue here either.
    "misc": {
        "1601": {"rate": 138.0, "carded": True},
        "1620": {"rate": 58.0, "carded": True},
        "1600": {"rate": 81.0, "carded": False},
        "1505": {"rate": 212.0, "carded": False},
        "1511": {"rate": 164.0, "carded": False},
    },
}

# ----------------------------------------------------------------------------------
# How the forwarder bills. Both bundles, which is what makes this the hard case.
# ----------------------------------------------------------------------------------
BILLING = {
    "origin": "bundled",
    "destination": "bundled",
    "origin_drayage_share": 0.0,
}

# ----------------------------------------------------------------------------------
# The forwarder's quote for the consolidation service.
# ----------------------------------------------------------------------------------
# How this client books, and therefore how much consolidation has to recover.
#
# Meritt is the marginal case. They buy in container-sized lots and plan tightly, but not
# perfectly: a small, credible pocket of fragmented bookings remains for consolidation
# to find. This keeps the weak-data scenario useful without making every lane flattering.
BOOKING = {
    # Orders are container-sized, so most lanes remain difficult opportunities.
    "lot_fill": (0.90, 0.99),
    "two_box_share": 0.22,
    "cbm_per_pallet": (1.30, 1.45),
    # A 96-100% operational fill range is disciplined but realistic. The narrow amount of
    # air is enough for a few dense lanes to clear the same commercial rule as every other
    # dataset, while the remainder are honestly left alone.
    "efficiency": (0.96, 1.00),
    # A container-load buyer barely uses groupage.
    "lcl_share": 0.04,
    # Unused in this mode, kept so the shape of the block matches the other worlds.
    "pallets": (3.79, 0.30),
    "pallets_max": 96,
}

SERVICE_QUOTE = {
    "CFS_INBOUND": {"rate": 130.0, "basis": "Per Inbound Delivery",
                    "item": "Receiving an inbound delivery: unload, check, put away"},
    "CFS_HANDLING": {"rate": 925.0, "basis": "Per Container",
                     "item": "Warehouse handling per container built"},
    "CFS_DRAYAGE": {"rate": 295.0, "basis": "Per Container",
                    "item": "Warehouse to Shenzhen/Yantian port, per container"},
    "CFS_STORAGE": {"rate": 0.38, "basis": "Per CBM Per Day",
                    "item": "Storage beyond the free period"},
    "CFS_FREE_DAYS": {"rate": 10.0, "basis": "Days",
                      "item": "Free storage period before storage bills"},
    "DECONSOL": {"rate": 910.0, "basis": "Per Extra Site",
                 "item": "Destination strip and onward local delivery"},
}

# Meritt never supplies an FTL rate.
#
# So the warehouse-to-port component stays in its ``opportunity`` state for the whole
# demo: the engine quantifies what an FTL rate would have to beat, asks for one, and
# reports the saving without it. Leaving one scenario with the question open is
# deliberate -- it is the state a real prospect is actually in when they walk out of
# the room, and pretending otherwise would make the other two less believable.
FTL_QUOTE = {}
