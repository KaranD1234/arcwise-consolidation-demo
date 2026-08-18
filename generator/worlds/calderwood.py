"""Calderwood Brands -- the bundled-origin world.

A fictional German importer of household and garden goods, buying out of Qingdao and
Chennai into Hamburg, Rotterdam and Gdansk. Invented from scratch, like every world
here, and deliberately unlike any live engagement.

Calderwood exists to answer the question Northgate cannot: **what happens when the
forwarder does not itemise?** Its origin charges arrive as a single all-in line, code
1630. The dollars are all present and reconcile to the cent, but they cannot be
attributed to a leg, so no origin rate can be derived from any of them. The engine has
to say so and ask for a rate card -- which is the honest answer, and the one most
prospects will actually get.

Two further differences from Northgate, both deliberate:

*   **No code 1602.** Northgate's origin drayage gives the warehouse-to-port leg an
    analogue to reach for. Calderwood has none, so that leg has nothing in the data at
    all and depends entirely on the forwarder's quote. It is the only drayage number in
    this world, which is what makes it the counterparty when FTL is tested.

*   **The FTL rate loses.** Calderwood's warehouse sits inland of Qingdao and the run
    to the berth is long, so the haulier's FTL tender comes in dearer than the
    forwarder's drayage. The engine tests it and reports that the drayage was cheaper.
    A demo that only ever confirms the client's hopes is worth less than one that
    occasionally tells them no, and this is where it does that.
"""

SCENARIO_ID = "calderwood"
CLIENT_SHORT = "Calderwood"
SUMMARY = "Origin billed as one all-in line; freight and delivery itemised."
SEED = 20260818
N_GROUPS = 760
INVOICE_PREFIX = "CB"

# ----------------------------------------------------------------------------------
# Client identity
# ----------------------------------------------------------------------------------
CLIENT_COMPANY = "Calderwood Brands GmbH (DE)"
BILL_TO_PARTY = "Calderwood Brands GmbH - Hamburg"
CONSIGNEE_BY_COUNTRY = {
    "Germany": "Calderwood Brands GmbH - Hamburg",
    "Netherlands": "Calderwood Benelux B.V. - Eindhoven",
    "Poland": "Calderwood Polska Sp. z o.o. - Poznan",
}
INVOICE_CLERKS = [
    "Bettina Schroeder", "Jakub Zielinski", "Lena Brandt",
    "Ruben Oosterhuis", "Sanne de Waard",
]

# A German importer bills mostly in euro.
CURRENCY_WEIGHTS = {"EUR": 0.63, "USD": 0.29, "GBP": 0.08}

# ----------------------------------------------------------------------------------
# Origins
# ----------------------------------------------------------------------------------
ORIGINS = {
    "Qingdao, China": {"cfs": "Qingdao", "country": "China"},
    "Chennai, India": {"cfs": "Chennai", "country": "India"},
}

ORIGIN_WEIGHTS = {
    "Qingdao, China": 0.71,
    "Chennai, India": 0.29,
}

TRANSSHIP = {
    "Chennai": {"share": 0.34, "ports": ["Colombo, Sri Lanka", "Jebel Ali, UAE"]},
}

# ----------------------------------------------------------------------------------
# Discharge ports, and nominal transit days from each origin.
# ----------------------------------------------------------------------------------
PORTS = {
    "Hamburg, Germany": {"country": "Germany", "transit": {"Qingdao": 36, "Chennai": 27}},
    "Rotterdam, Netherlands": {"country": "Netherlands", "transit": {"Qingdao": 34, "Chennai": 25}},
    "Gdansk, Poland": {"country": "Poland", "transit": {"Qingdao": 39, "Chennai": 30}},
}

POD_WEIGHTS = {
    "Hamburg, Germany": 0.46,
    "Rotterdam, Netherlands": 0.31,
    "Gdansk, Poland": 0.23,
}

# Hamburg serves four sites, so four weights are needed.
SITE_WEIGHTS = [0.44, 0.26, 0.18, 0.12]

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
        "site_id": "DE_LUBECK", "site": "Lubeck, DE", "country": "Germany",
        "pod": "Hamburg, Germany",
        "raw": [
            ("Lehmann Distribution GmbH - Lubeck", None),
            ("Lehmann Distribution G.m.b.H - Luebeck", None),
        ],
    },
    {
        "site_id": "DE_HANNOVER", "site": "Hannover, DE", "country": "Germany",
        "pod": "Hamburg, Germany",
        "raw": [("Nordfracht Kontraktlogistik - Hannover", None)],
    },
    {
        "site_id": "DE_LEIPZIG", "site": "Leipzig, DE", "country": "Germany",
        "pod": "Hamburg, Germany",
        "raw": [
            ("Saalepark Logistikzentrum - Leipzig", None),
            # The client's own name leads the string, so it looks nothing like the
            # canonical form. Same warehouse.
            ("Calderwood Brands c/o Saalepark - Leipzig", "alias_hard"),
        ],
    },
    {
        "site_id": "DE_KASSEL", "site": "Kassel, DE", "country": "Germany",
        "pod": "Hamburg, Germany",
        "raw": [("Fuldatal Warehousing AG - Kassel ", None)],
    },
    {
        "site_id": "NL_EINDHOVEN", "site": "Eindhoven, NL", "country": "Netherlands",
        "pod": "Rotterdam, Netherlands",
        "raw": [("Dommelvracht Logistiek BV - Eindhoven", None)],
    },
    {
        "site_id": "NL_BORN", "site": "Born, NL", "country": "Netherlands",
        "pod": "Rotterdam, Netherlands",
        "raw": [
            ("Maasgouw Contract Logistics - Born", None),
        ],
    },
    {
        "site_id": "NL_ROOSENDAAL", "site": "Roosendaal, NL", "country": "Netherlands",
        "pod": "Rotterdam, Netherlands",
        "raw": [("Westhoek Opslag en Transport - Roosendaal", None)],
    },
    {
        "site_id": "PL_POZNAN", "site": "Poznan, PL", "country": "Poland",
        "pod": "Gdansk, Poland",
        "raw": [
            ("Wisla Logistyka Kontraktowa - Poznan", None),
            # The address field holds a placeholder. This is the escalation that
            # genuinely needs a human.
            ("Wisla Logistyka Kontraktowa Sp. z o.o. - N/A", "not_a_place"),
        ],
    },
    {
        "site_id": "PL_GLIWICE", "site": "Gliwice, PL", "country": "Poland",
        "pod": "Gdansk, Poland",
        # Same operator as PL_POZNAN's neighbour below, at a different city. Must NOT
        # be merged with it.
        "raw": [("Karpaty Magazyny Sp. z o.o. - Gliwice", None)],
    },
    {
        "site_id": "PL_LODZ", "site": "Lodz, PL", "country": "Poland",
        "pod": "Gdansk, Poland",
        "raw": [("Karpaty Magazyny Spolka - Lodz", None)],
    },
]

# ----------------------------------------------------------------------------------
# Suppliers.
#
# ``office`` is effectively what the shipment file records, which is not always where
# the goods come from -- a procurement office in Hamburg or Dubai appears as the
# shipper on cargo that physically leaves Qingdao. ``region`` is the true pickup
# region and is what an origin rate is priced against, so a supplier whose office is
# not in the origin country has to be resolved before it can be costed.
# ``queue: proxy`` marks the two that also have no rate-card row.
# ----------------------------------------------------------------------------------
SUPPLIERS = [
    # --- Qingdao catchment ------------------------------------------------------
    {"name": "Qingdao Haiyue Garden Tools Co., Ltd. - Qingdao", "cfs": "Qingdao", "region": "QINGDAO", "queue": None},
    {"name": "Jiaozhou Fengtai Housewares Co., Ltd. - Jiaozhou", "cfs": "Qingdao", "region": "QINGDAO", "queue": None},
    {"name": "Weifang Zhenghe Ceramics Co., Ltd. - Weifang", "cfs": "Qingdao", "region": "WEIFANG", "queue": None},
    {"name": "Zibo Guangming Glassware Co., Ltd. - Zibo", "cfs": "Qingdao", "region": "WEIFANG", "queue": None},
    {"name": "Yantai Ruixin Small Appliances Co., Ltd. - Yantai", "cfs": "Qingdao", "region": "YANTAI", "queue": None},
    {"name": "Penglai Dongsheng Metal Furniture Co., Ltd. - Penglai", "cfs": "Qingdao", "region": "YANTAI", "queue": None},
    {"name": "Linyi Hongfa Woodware Co., Ltd. - Linyi", "cfs": "Qingdao", "region": "WEIFANG", "queue": None},
    {"name": "Rizhao Changtai Outdoor Products Co., Ltd. - Rizhao", "cfs": "Qingdao", "region": "QINGDAO", "queue": None},
    {"name": "Jinan Baohe Kitchenware Co., Ltd. - Jinan", "cfs": "Qingdao", "region": "WEIFANG", "queue": None},
    {"name": "Dezhou Xingyuan Textile Homeware Co., Ltd. - Dezhou", "cfs": "Qingdao", "region": "WEIFANG", "queue": None},
    {"name": "Laixi Zhongtian Plastic Mouldings Co., Ltd. - Laixi", "cfs": "Qingdao", "region": "QINGDAO", "queue": None},
    # Recorded at a German procurement office; goods leave Qingdao. No rate-card row.
    {"name": "Calderwood Sourcing Nord GmbH - Hamburg", "cfs": "Qingdao", "region": "QINGDAO", "queue": "proxy"},
    # --- Chennai catchment ------------------------------------------------------
    {"name": "Chennai Aravind Brassware Pvt. Ltd. - Chennai", "cfs": "Chennai", "region": "CHENNAI", "queue": None},
    {"name": "Sriperumbudur Kalyan Enclosures Pvt. Ltd. - Sriperumbudur", "cfs": "Chennai", "region": "CHENNAI", "queue": None},
    {"name": "Coimbatore Vasanth Pump Components Pvt. Ltd. - Coimbatore", "cfs": "Chennai", "region": "COIMBATORE", "queue": None},
    {"name": "Tiruppur Meenakshi Home Textiles Pvt. Ltd. - Tiruppur", "cfs": "Chennai", "region": "COIMBATORE", "queue": None},
    {"name": "Hosur Anand Wire Products Pvt. Ltd. - Hosur", "cfs": "Chennai", "region": "COIMBATORE", "queue": None},
    {"name": "Ranipet Devi Leather Goods Pvt. Ltd. - Ranipet", "cfs": "Chennai", "region": "CHENNAI", "queue": None},
    # Recorded at a Gulf trading office; goods leave Chennai. No rate-card row.
    # Recorded where the goods actually leave from, so it resolves on its own. One
    # foreign procurement office per world is the point; two made the same decision twice.
    {"name": "Calderwood Trading India Pvt Ltd - Ranipet", "cfs": "Chennai", "region": "CHENNAI", "queue": None},
]

# Pickup regions an origin rate can be priced against.
PICKUP_REGIONS = ["QINGDAO", "WEIFANG", "YANTAI", "CHENNAI", "COIMBATORE"]

# ----------------------------------------------------------------------------------
# The world's true pricing.
#
# ``carded`` decides provenance in the finished demo:
#   True  -> the row appears on the client rate card, so the engine prices from it
#   False -> the row is withheld, so the engine must derive it from the invoices
#
# The origin components are ALL carded here, and that is not generosity -- it is
# necessity. Calderwood's forwarder bundles them into code 1630, so the invoices
# cannot price them and the card is the only thing that can. Withholding one would
# leave a leg permanently unpriceable, which is a different demo.
#
# Ocean and destination are mostly UNcarded, because those lines are still itemised
# and the engine can rebuild them. The contrast is the whole point of this world: the
# same client, half derived and half carded, with the split decided by how the
# forwarder chose to bill rather than by anything we control.
# ----------------------------------------------------------------------------------
TRUE_RATES = {
    # Ocean freight, USD per 40'HC, by (origin CFS, port of discharge).
    "ocean": {
        ("Qingdao", "Hamburg, Germany"): {"rate": 4290.0, "carded": True},
        ("Qingdao", "Rotterdam, Netherlands"): {"rate": 4150.0, "carded": False},
        ("Qingdao", "Gdansk, Poland"): {"rate": 4480.0, "carded": False},
        ("Chennai", "Hamburg, Germany"): {"rate": 3620.0, "carded": True},
        ("Chennai", "Rotterdam, Netherlands"): {"rate": 3480.0, "carded": False},
        ("Chennai", "Gdansk, Poland"): {"rate": 3910.0, "carded": False},
    },
    # Destination delivery, USD per container, by (port of discharge, site).
    # The code-1638 rate the engine reverse-engineers where uncarded.
    "dest": {
        ("Hamburg, Germany", "Lubeck, DE"): {"rate": 940.0, "carded": True},
        ("Hamburg, Germany", "Hannover, DE"): {"rate": 1580.0, "carded": False},
        ("Hamburg, Germany", "Leipzig, DE"): {"rate": 2080.0, "carded": False},
        ("Hamburg, Germany", "Kassel, DE"): {"rate": 1890.0, "carded": False},
        ("Rotterdam, Netherlands", "Eindhoven, NL"): {"rate": 1420.0, "carded": True},
        ("Rotterdam, Netherlands", "Born, NL"): {"rate": 1655.0, "carded": False},
        ("Rotterdam, Netherlands", "Roosendaal, NL"): {"rate": 1075.0, "carded": False},
        ("Gdansk, Poland", "Poznan, PL"): {"rate": 1240.0, "carded": True},
        ("Gdansk, Poland", "Gliwice, PL"): {"rate": 1810.0, "carded": False},
        ("Gdansk, Poland", "Lodz, PL"): {"rate": 1495.0, "carded": False},
    },
    # Itemised origin components, USD per container, by pickup region. Bundled into
    # code 1630 on the way into the file, so the amounts here are what the client
    # actually paid and the card is the only place they are visible.
    "exw": {
        "QINGDAO": {"carded": True, "components": {
            "1631": 585.0, "1632": 295.0, "1633": 44.0, "1634": 36.0,
            "1635": 68.0, "1636": 92.0, "1637": 115.0}},
        "WEIFANG": {"carded": True, "components": {
            "1631": 910.0, "1632": 295.0, "1633": 44.0, "1634": 36.0,
            "1635": 68.0, "1636": 92.0, "1637": 115.0}},
        "YANTAI": {"carded": True, "components": {
            "1631": 780.0, "1632": 295.0, "1633": 44.0, "1634": 36.0,
            "1635": 68.0, "1636": 92.0, "1637": 115.0}},
        "CHENNAI": {"carded": True, "components": {
            "1631": 495.0, "1632": 330.0, "1633": 52.0, "1634": 41.0,
            "1635": 76.0, "1636": 118.0, "1637": 142.0}},
        "COIMBATORE": {"carded": True, "components": {
            "1631": 865.0, "1632": 330.0, "1633": 52.0, "1634": 41.0,
            "1635": 76.0, "1636": 118.0, "1637": 142.0}},
    },
    # Miscellaneous per-shipment charges, USD.
    #
    # Note the absence of code 1602. Calderwood's forwarder does not bill origin
    # drayage separately, so nothing in this world prices a road move at origin and
    # the warehouse-to-port leg has no analogue to fall back on.
    "misc": {
        "1601": {"rate": 162.0, "carded": True},
        "1620": {"rate": 72.0, "carded": True},
        "1600": {"rate": 95.0, "carded": False},
        "1505": {"rate": 248.0, "carded": True},
        "1511": {"rate": 191.0, "carded": False},
    },
}

# ----------------------------------------------------------------------------------
# How the forwarder bills.
#
# Origin is one all-in line, code 1630. Destination is still itemised under 1638, so
# this world derives its freight and delivery rates and cannot derive a single origin
# rate. ``origin_drayage_share`` is zero: no code 1602 at all.
# ----------------------------------------------------------------------------------
BILLING = {
    "origin": "bundled",
    "destination": "itemised",
    "origin_drayage_share": 0.0,
}

# ----------------------------------------------------------------------------------
# The forwarder's quote for the consolidation service.
#
# The drayage figure here matters more than it looks: with no code 1602 anywhere in
# the file, it is the ONLY warehouse-to-port number in this world. It is what the FTL
# rate gets tested against.
# ----------------------------------------------------------------------------------
# How this client books, and therefore how much consolidation has to recover.
#
# Calderwood is the borderline case, deliberately. Its consignments are larger than
# Northgate's and its bookings tighter -- boxes leave 80-97% of what the planner thought
# would fit -- so there is a real saving in it and not much of one. Which side of "worth
# doing" it lands on is then decided by the settings rather than by the freight: letting
# sites share a container roughly doubles it, and holding the warehouse to a three-day
# dwell takes most of it away.
BOOKING = {
    "pallets": (3.78, 0.40),          # lognormal mu/sigma -> median ~44 pallets
    "pallets_max": 150,
    "cbm_per_pallet": (1.12, 1.48),
    "efficiency": (0.80, 0.97),       # how full a booked box actually leaves
}

SERVICE_QUOTE = {
    "CFS_INBOUND": {"rate": 165.0, "basis": "Per Inbound Delivery",
                    "item": "Receiving an inbound delivery: unload, check, put away"},
    "CFS_HANDLING": {"rate": 1085.0, "basis": "Per Container",
                     "item": "Warehouse handling per container built"},
    "CFS_DRAYAGE": {"rate": 340.0, "basis": "Per Container",
                    "item": "Warehouse to Qingdao/Chennai port, per container"},
    "CFS_STORAGE": {"rate": 0.52, "basis": "Per CBM Per Day",
                    "item": "Storage beyond the free period"},
    # Five free days, against Northgate's seven. The same figure quoted differently is
    # exactly why it has to come off their file rather than out of our config.
    "CFS_FREE_DAYS": {"rate": 5.0, "basis": "Days",
                      "item": "Free storage period before storage bills"},
    "DECONSOL": {"rate": 860.0, "basis": "Per Extra Site",
                 "item": "Destination strip and onward local delivery"},
}

# The FTL rate -- and here it LOSES.
#
# The consolidation warehouse sits inland of Qingdao and the run to the berth is long
# enough that a dedicated truck costs more than the forwarder's drayage tariff. The
# engine tests it, reports that the drayage is cheaper, and keeps the drayage. That
# outcome is the reason this world exists.
# Supplied, tested, and rejected -- which is the outcome that earns the other two any
# credit. The regions here are spread out and the suppliers are large, so the loads this
# world already runs are close to full and a trailer tender has almost nothing to pool.
# It buys a handful of receiving charges back and charges more per load than it saves.
FTL_QUOTE = {
    "INBOUND_FTL": {
        "basis": "Per Trailer Load",
        "item": "Dedicated trailer, supplier region to consolidation warehouse",
        "note": "Direct haulier tender, priced per full trailer load by pickup region. "
                "Long inland runs and a night curfew on the ring road.",
        "rates": {"QINGDAO": 785.0, "WEIFANG": 1100.0, "YANTAI": 990.0,
                  "CHENNAI": 825.0, "COIMBATORE": 1050.0},
    },
}
