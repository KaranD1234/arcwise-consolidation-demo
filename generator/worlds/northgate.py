"""Northgate Supply Co. -- the well-billed world, and the demo's primary scenario.

A fictional UK importer of industrial components, buying out of Ningbo and Ho Chi
Minh City. The geography, suppliers, sites and rates were independently invented to
be plausible demo inputs.

Northgate's distinguishing feature is that its forwarder **itemises everything**.
Every EXW component arrives on its own coded line, so the engine can rebuild almost
the entire cost model from the client's own invoices without being handed a rate
card. That is the best case, and it is the right scenario to open on.

Three things here are load-bearing and must not be casually edited:

1.  ``TRUE_RATES`` is the world's real pricing. Charge-line amounts are generated
    from it with noise, and a *subset* is published as the client's rate card.
    That is what makes the demo's rate provenance honest -- rates the card covers,
    rates the engine must derive from invoices, and rates nobody can price because
    the step has never happened.

2.  ``DELIVERY_SITES`` carries deliberate raw-string variants -- spelling drift,
    trailing spaces, a county with no town, and one address that is not a place.
    Those are the resolution queue's work. Removing them empties the queue and
    removes the most product-specific part of the demo.

3.  ``SEED`` and every weight below are what make this scenario rehearsable. The
    published figures come out of these numbers, so changing any of them
    re-baselines the manifest, validate.py's expectations and the README.
"""

SCENARIO_ID = "northgate"
CLIENT_SHORT = "Northgate"
SUMMARY = "Every EXW charge on its own coded line, and delivery itemised too."
SEED = 20260817
N_GROUPS = 900
INVOICE_PREFIX = "NG"

# ----------------------------------------------------------------------------------
# Client identity
# ----------------------------------------------------------------------------------
CLIENT_COMPANY = "Northgate Supply Co. (UK)"
BILL_TO_PARTY = "Northgate Supply Co. Ltd. (UK) - Manchester"
CONSIGNEE_BY_COUNTRY = {
    "Netherlands": "Northgate Supply Co. Europe BV - Venlo",
    "Germany": "Northgate Supply Co. Deutschland GmbH - Bremen",
    "United Kingdom": "Northgate Supply Co. Ltd. (UK) - Manchester",
    "Spain": "Northgate Supply Iberia S.L. - Valencia",
}
INVOICE_CLERKS = [
    "Anneke Visser", "Dilan Kaya", "Marcus Oyelaran",
    "Priya Raghunathan", "Tomas Halvorsen",
]

# A UK importer bills mostly in sterling. The mix is what gives the model a real FX
# exposure figure to publish rather than an assumed one.
CURRENCY_WEIGHTS = {"GBP": 0.52, "USD": 0.30, "EUR": 0.18}

# ----------------------------------------------------------------------------------
# Origins. The CFS is the consolidation warehouse the plan would build boxes at.
# ----------------------------------------------------------------------------------
ORIGINS = {
    "Ningbo, China": {"cfs": "Ningbo", "country": "China"},
    "Ho Chi Minh City, Vietnam": {"cfs": "Ho Chi Minh City", "country": "Vietnam"},
}

# Share of volume by origin. Keyed by name rather than position so adding an origin
# without weighting it is an error rather than a silently dead lane.
#
# Ho Chi Minh City carries the larger share, which is worth stating explicitly because
# it is the opposite of what the ordering above suggests. The published dataset has 595
# groups out of 900 leaving Vietnam, and the demo's rehearsed figures follow from that
# split -- so these two numbers are load-bearing and swapping them re-baselines
# everything downstream.
ORIGIN_WEIGHTS = {
    "Ho Chi Minh City, Vietnam": 0.66,
    "Ningbo, China": 0.34,
}

# Origins whose cargo sometimes routes via a hub, and the hubs it routes through.
TRANSSHIP = {
    "Ho Chi Minh City": {"share": 0.28,
                         "ports": ["Singapore", "Port Klang, Malaysia"]},
}

# Discharge ports, and the transit days from each origin. Transit is sampled around
# these; they are not exact.
PORTS = {
    "Rotterdam, Netherlands": {"country": "Netherlands", "transit": {"Ningbo": 34, "Ho Chi Minh City": 32}},
    "Hamburg, Germany": {"country": "Germany", "transit": {"Ningbo": 37, "Ho Chi Minh City": 35}},
    "Felixstowe, United Kingdom": {"country": "United Kingdom", "transit": {"Ningbo": 33, "Ho Chi Minh City": 31}},
    "Valencia, Spain": {"country": "Spain", "transit": {"Ningbo": 28, "Ho Chi Minh City": 26}},
}

# Share of volume by discharge port.
POD_WEIGHTS = {
    "Felixstowe, United Kingdom": 0.30,
    "Hamburg, Germany": 0.24,
    "Rotterdam, Netherlands": 0.28,
    "Valencia, Spain": 0.18,
}

# How volume falls away across the sites a single port serves, busiest first.
#
# A real network runs two or three major DCs per region and a tail of smaller ones,
# and that skew is what decides whether consolidation is worth doing on a lane: busy
# lanes fill containers comfortably, thin ones cannot gather enough cargo inside the
# dwell allowance to fill anything. A uniform network would make every lane look
# identical and hide the only judgement the client actually has to make.
SITE_WEIGHTS = [0.55, 0.28, 0.17]

# ----------------------------------------------------------------------------------
# Delivery sites.
#
# ``raw`` holds the strings that actually appear in the charge-line file. Anything
# beyond the first entry is drift the resolution queue has to deal with. ``queue``
# marks a variant that is deliberately hard, so it escalates instead of
# auto-resolving:
#   alias_hard  -- same physical site, but the string shares little with the canonical
#   not_a_place -- the address field holds a placeholder, not a location
#   county_only -- a county with no town, so the site cannot be pinned precisely
# ----------------------------------------------------------------------------------
DELIVERY_SITES = [
    {
        "site_id": "NL_VENLO", "site": "Venlo, NL", "country": "Netherlands",
        "pod": "Rotterdam, Netherlands",
        "raw": [
            ("Broekman Logistics - Venlo", None),
            ("Broekman Logistics BV c/o - Venlo", None),
        ],
    },
    {
        "site_id": "NL_TILBURG", "site": "Tilburg, NL", "country": "Netherlands",
        "pod": "Rotterdam, Netherlands",
        "raw": [("Rhenus Logistics - Tilburg", None)],
    },
    {
        "site_id": "NL_MOERDIJK", "site": "Moerdijk, NL", "country": "Netherlands",
        "pod": "Rotterdam, Netherlands",
        "raw": [("De Rijke Group - Moerdijk", None)],
    },
    {
        "site_id": "DE_BREMEN", "site": "Bremen, DE", "country": "Germany",
        "pod": "Hamburg, Germany",
        "raw": [
            ("BLG Logistics GmbH - Bremen", None),
            # Punctuation drift plus a trailing space -- the commonest real variant.
            ("BLG Logistics G.m.b.H. - Bremen ", None),
        ],
    },
    {
        "site_id": "DE_DUISBURG", "site": "Duisburg, DE", "country": "Germany",
        "pod": "Hamburg, Germany",
        # Same operator as NL_TILBURG at a different city. Must NOT be merged with it.
        "raw": [("Rhenus Warehousing Solutions - Duisburg", None)],
    },
    {
        "site_id": "DE_HANNOVER", "site": "Hannover, DE", "country": "Germany",
        "pod": "Hamburg, Germany",
        "raw": [("Hellmann Worldwide Logistics - Hannover", None)],
    },
    {
        # Independently invented operator and town pairing.
        "site_id": "UK_LUTTERWORTH", "site": "Lutterworth, UK", "country": "United Kingdom",
        "pod": "Felixstowe, United Kingdom",
        "raw": [("Harbrook Contract Logistics - Lutterworth", None)],
    },
    {
        "site_id": "UK_CORBY", "site": "Corby, UK", "country": "United Kingdom",
        "pod": "Felixstowe, United Kingdom",
        "raw": [
            ("Bleckmann UK Ltd - Corby", None),
            # The client's own name leads the string, so it looks nothing like the
            # canonical form. Same warehouse.
            ("Northgate Supply Co. c/o Bleckmann - Corby", "alias_hard"),
        ],
    },
    {
        # This site used to be recorded as a county rather than a town, which escalated a
        # fourth decision -- "we cannot pin this to a warehouse". It is an ordinary town
        # now, on purpose: the review step is held to three decisions, one of each kind,
        # and a county is the least interesting of the four to watch somebody answer.
        # `resolve.py` still handles a region string, and still has to, because a
        # prospect's own file will contain them.
        "site_id": "UK_TELFORD", "site": "Telford, UK", "country": "United Kingdom",
        "pod": "Felixstowe, United Kingdom",
        "raw": [("Marchfield Cold Storage - Telford", None)],
    },
    {
        "site_id": "ES_VALENCIA", "site": "Valencia, ES", "country": "Spain",
        "pod": "Valencia, Spain",
        "raw": [("Grupo Raminatrans - Valencia", None)],
    },
    {
        "site_id": "ES_ZARAGOZA", "site": "Zaragoza, ES", "country": "Spain",
        "pod": "Valencia, Spain",
        "raw": [
            ("DHL Supply Chain Iberia - Zaragoza", None),
            ("DHL Supply Chain (Iberia) S.A.U. c/o - Zaragoza", "alias_hard"),
        ],
    },
    {
        "site_id": "ES_BARCELONA", "site": "Barcelona, ES", "country": "Spain",
        "pod": "Valencia, Spain",
        "raw": [
            ("Sese Logistics - Barcelona", None),
            # The address field holds a placeholder. This is the escalation that
            # genuinely needs a human.
            ("Sese Logistics S.L. - City", "not_a_place"),
        ],
    },
]

# ----------------------------------------------------------------------------------
# Suppliers.
#
# ``office`` is what the shipment file records, which is not always where the goods
# come from -- a procurement office in Manchester or Chicago appears as the shipper
# on cargo that physically leaves Ningbo. ``region`` is the true pickup region and
# is what an origin rate is priced against, so a supplier whose office is not in
# origin country has to be resolved before it can be costed. ``queue: proxy`` marks
# the two that also have no rate-card row, so they need a proxy decision as well.
# ----------------------------------------------------------------------------------
SUPPLIERS = [
    # --- Ningbo catchment -------------------------------------------------------
    {"name": "Ningbo Yongtai Precision Components Co., Ltd. - Ningbo", "cfs": "Ningbo", "region": "NINGBO", "queue": None},
    {"name": "Cixi Hongsheng Fasteners Co., Ltd. - Cixi", "cfs": "Ningbo", "region": "NINGBO", "queue": None},
    {"name": "Zhejiang Deqing Valve Manufacturing Co., Ltd. - Deqing", "cfs": "Ningbo", "region": "HANGZHOU", "queue": None},
    {"name": "Hangzhou Weiming Industrial Seals Co., Ltd. - Hangzhou", "cfs": "Ningbo", "region": "HANGZHOU", "queue": None},
    {"name": "Taizhou Kaiyuan Moulded Plastics Co., Ltd. - Taizhou", "cfs": "Ningbo", "region": "NINGBO", "queue": None},
    {"name": "Suzhou Jinlong Metal Pressings Co., Ltd. - Suzhou", "cfs": "Ningbo", "region": "SUZHOU", "queue": None},
    {"name": "Wuxi Changrong Bearing Works Co., Ltd. - Wuxi", "cfs": "Ningbo", "region": "SUZHOU", "queue": None},
    {"name": "Kunshan Ruitai Electrical Fittings Co., Ltd. - Kunshan", "cfs": "Ningbo", "region": "SUZHOU", "queue": None},
    {"name": "Jiaxing Antai Wire Goods Co., Ltd. - Jiaxing", "cfs": "Ningbo", "region": "HANGZHOU", "queue": None},
    {"name": "Shaoxing Fenghua Textile Hardware Co., Ltd. - Shaoxing", "cfs": "Ningbo", "region": "HANGZHOU", "queue": None},
    {"name": "Yuyao Guanghe Injection Mouldings Co., Ltd. - Yuyao", "cfs": "Ningbo", "region": "NINGBO", "queue": None},
    {"name": "Changzhou Beite Tooling Co., Ltd. - Changzhou", "cfs": "Ningbo", "region": "SUZHOU", "queue": None},
    # Recorded at a UK procurement office; goods leave Ningbo. No rate-card row.
    {"name": "Northgate Sourcing Partners Ltd. - Manchester", "cfs": "Ningbo", "region": "NINGBO", "queue": "proxy"},
    # --- Ho Chi Minh catchment --------------------------------------------------
    {"name": "Binh Duong Truong Phat Metalworks JSC - Binh Duong", "cfs": "Ho Chi Minh City", "region": "BINH_DUONG", "queue": None},
    {"name": "Dong Nai Tan Loi Rubber Products Co., Ltd. - Bien Hoa", "cfs": "Ho Chi Minh City", "region": "BINH_DUONG", "queue": None},
    {"name": "Long An Phuoc Thanh Wire Assemblies Co., Ltd. - Long An", "cfs": "Ho Chi Minh City", "region": "BINH_DUONG", "queue": None},
    {"name": "Vietnam Precision Turned Parts Co., Ltd. - Ho Chi Minh City", "cfs": "Ho Chi Minh City", "region": "HCMC", "queue": None},
    {"name": "Saigon Hi-Tech Enclosures JSC - Ho Chi Minh City", "cfs": "Ho Chi Minh City", "region": "HCMC", "queue": None},
    {"name": "Tay Ninh Duc Thanh Castings Co., Ltd. - Tay Ninh", "cfs": "Ho Chi Minh City", "region": "BINH_DUONG", "queue": None},
    {"name": "Can Tho Mekong Fabrication Co., Ltd. - Can Tho", "cfs": "Ho Chi Minh City", "region": "HCMC", "queue": None},
    # Recorded where the goods actually leave from, so it resolves on its own. One
    # foreign procurement office per world is the point; two made the same decision twice.
    {"name": "Meridian Industrial Trading LLC - Can Tho", "cfs": "Ho Chi Minh City", "region": "HCMC", "queue": None},
]

# Pickup regions an origin rate can be priced against.
PICKUP_REGIONS = ["NINGBO", "HANGZHOU", "SUZHOU", "BINH_DUONG", "HCMC"]

# ----------------------------------------------------------------------------------
# The world's true pricing. Invoices are generated from this with noise; a subset
# is published as the client's rate card.
#
# ``carded`` decides provenance in the finished demo:
#   True  -> the row appears on the client rate card, so the engine prices from it
#   False -> the row is withheld, so the engine must derive it from the invoices
# ----------------------------------------------------------------------------------
TRUE_RATES = {
    # Ocean freight, USD per 40'HC, by (origin CFS, port of discharge).
    "ocean": {
        ("Ningbo", "Rotterdam, Netherlands"): {"rate": 4180.0, "carded": True},
        ("Ningbo", "Hamburg, Germany"): {"rate": 4340.0, "carded": True},
        ("Ningbo", "Felixstowe, United Kingdom"): {"rate": 4025.0, "carded": True},
        ("Ningbo", "Valencia, Spain"): {"rate": 3760.0, "carded": True},
        ("Ho Chi Minh City", "Rotterdam, Netherlands"): {"rate": 4460.0, "carded": True},
        ("Ho Chi Minh City", "Hamburg, Germany"): {"rate": 4615.0, "carded": False},
        ("Ho Chi Minh City", "Felixstowe, United Kingdom"): {"rate": 4290.0, "carded": True},
        ("Ho Chi Minh City", "Valencia, Spain"): {"rate": 3985.0, "carded": False},
    },
    # Destination delivery, USD per container, by (port of discharge, site).
    # This is the code-1638 rate the engine reverse-engineers where uncarded.
    "dest": {
        ("Rotterdam, Netherlands", "Venlo, NL"): {"rate": 1485.0, "carded": True},
        ("Rotterdam, Netherlands", "Tilburg, NL"): {"rate": 1610.0, "carded": True},
        ("Rotterdam, Netherlands", "Moerdijk, NL"): {"rate": 1395.0, "carded": False},
        ("Hamburg, Germany", "Bremen, DE"): {"rate": 1720.0, "carded": True},
        ("Hamburg, Germany", "Duisburg, DE"): {"rate": 2140.0, "carded": True},
        ("Hamburg, Germany", "Hannover, DE"): {"rate": 1965.0, "carded": False},
        ("Felixstowe, United Kingdom", "Lutterworth, UK"): {"rate": 1840.0, "carded": True},
        ("Felixstowe, United Kingdom", "Corby, UK"): {"rate": 1795.0, "carded": True},
        ("Felixstowe, United Kingdom", "Telford, UK"): {"rate": 1465.0, "carded": False},
        ("Valencia, Spain", "Valencia, ES"): {"rate": 985.0, "carded": True},
        ("Valencia, Spain", "Zaragoza, ES"): {"rate": 1560.0, "carded": True},
        ("Valencia, Spain", "Barcelona, ES"): {"rate": 1340.0, "carded": False},
    },
    # Itemised origin components, USD per container, by pickup region. Only the
    # collection charge varies much by region; the rest are terminal mechanics.
    "exw": {
        "NINGBO": {"carded": True, "components": {
            "1631": 640.0, "1632": 285.0, "1633": 42.0, "1634": 38.0,
            "1635": 65.0, "1636": 95.0, "1637": 120.0}},
        "HANGZHOU": {"carded": True, "components": {
            "1631": 880.0, "1632": 285.0, "1633": 42.0, "1634": 38.0,
            "1635": 65.0, "1636": 95.0, "1637": 120.0}},
        "SUZHOU": {"carded": True, "components": {
            "1631": 1045.0, "1632": 285.0, "1633": 42.0, "1634": 38.0,
            "1635": 65.0, "1636": 95.0, "1637": 120.0}},
        "BINH_DUONG": {"carded": False, "components": {
            "1631": 725.0, "1632": 310.0, "1633": 45.0, "1634": 40.0,
            "1635": 70.0, "1636": 105.0, "1637": 135.0}},
        "HCMC": {"carded": False, "components": {
            "1631": 520.0, "1632": 310.0, "1633": 45.0, "1634": 40.0,
            "1635": 70.0, "1636": 105.0, "1637": 135.0}},
    },
    # Miscellaneous per-shipment charges, USD.
    "misc": {
        "1601": {"rate": 145.0, "carded": True},
        "1602": {"rate": 310.0, "carded": True},
        "1620": {"rate": 65.0, "carded": True},
        "1600": {"rate": 88.0, "carded": False},
        "1505": {"rate": 235.0, "carded": True},
        "1511": {"rate": 178.0, "carded": False},
    },
}

# ----------------------------------------------------------------------------------
# How the forwarder bills.
#
# Northgate's forwarder itemises everything, which is the best case and the reason
# this is the primary scenario: the engine can rebuild almost every rate from the
# client's own invoices without being handed a single rate card.
#
# ``origin_drayage_share`` is the share of EXW groups carrying code 1602. Northgate
# has it, which is what gives the warehouse-to-port leg an analogue to reach for --
# the right kind of charge on the wrong leg. The other two worlds have none, so that
# leg has nothing to fall back on and has to be quoted.
# ----------------------------------------------------------------------------------
BILLING = {
    "origin": "itemised",
    "destination": "itemised",
    "origin_drayage_share": 0.55,
}

# ----------------------------------------------------------------------------------
# The forwarder's quote for the consolidation service.
#
# None of this is on an invoice, because none of it has happened: consolidation
# builds containers at a warehouse the client does not use today. A quote for work
# not yet bought is still evidence -- it is the client's own commercial number -- so
# it ships as a reference file rather than being asserted by the engine.
# ----------------------------------------------------------------------------------
# How this client books, and therefore how much consolidation has to recover.
#
# Northgate buys in small lots from many suppliers and books each one on its own, so its
# containers leave well short: a median consignment of about 35 pallets in a box that
# holds 48, and a planner filling to 60-86% of what would fit. That headroom is the whole
# opportunity, and it is why this is the strong case of the three.
BOOKING = {
    "pallets": (3.55, 0.60),          # lognormal mu/sigma -> median ~35 pallets
    "pallets_max": 190,
    "cbm_per_pallet": (1.05, 1.55),
    "efficiency": (0.60, 0.86),       # how full a booked box actually leaves
}

SERVICE_QUOTE = {
    "CFS_INBOUND": {"rate": 145.0, "basis": "Per Inbound Delivery",
                    "item": "Receiving an inbound delivery: unload, check, put away"},
    "CFS_HANDLING": {"rate": 1000.0, "basis": "Per Container",
                     "item": "Warehouse handling per container built"},
    "CFS_DRAYAGE": {"rate": 310.0, "basis": "Per Container",
                    "item": "Warehouse to Ningbo/HCMC port, per container"},
    "CFS_STORAGE": {"rate": 0.45, "basis": "Per CBM Per Day",
                    "item": "Storage beyond the free period"},
    # On the quote because it prices a real line. The storage rate is only half the
    # arithmetic -- the free period decides how many CBM-days ever bill -- so leaving it
    # to a figure of ours would put part of a cost in the model on nobody's authority.
    "CFS_FREE_DAYS": {"rate": 7.0, "basis": "Days",
                      "item": "Free storage period before storage bills"},
    "DECONSOL": {"rate": 780.0, "basis": "Per Extra Site",
                 "item": "Destination strip and onward local delivery"},
}

# The inbound trailer tender, which the client does NOT supply until asked.
#
# It ships as its own file so the demo can show the engine noticing the gap, quantifying
# what a trailer rate would have to beat, and then testing the one it is given. Here the
# tender wins -- the regions are compact, so trailers pack full and the warehouse receives
# far fewer deliveries -- so the engine adopts it and the saving grows. See calderwood for
# the opposite outcome, which matters more.
FTL_QUOTE = {
    "INBOUND_FTL": {
        "basis": "Per Trailer Load",
        "item": "Dedicated trailer, supplier region to consolidation warehouse",
        "note": "Direct haulier tender, priced per full trailer load by pickup region.",
        "rates": {"NINGBO": 720.0, "HANGZHOU": 940.0, "SUZHOU": 1050.0,
                  "BINH_DUONG": 640.0, "HCMC": 520.0},
    },
}
