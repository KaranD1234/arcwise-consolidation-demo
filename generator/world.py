"""What every invented world in this demo has in common.

The demo ships three fictional importers rather than one, because the first question
in a client meeting is not "does it work on your data?" but **"what happens when my
data isn't as good as that?"** Answering it needs more than one input file, and the
three differ along the axis that actually matters: how the forwarder bills.

    northgate    every EXW charge itemised on its own coded line
    calderwood   origin billed as one all-in line
    meritt       origin bundled AND destination folded into the freight line

The rate provenance in the finished demo is a consequence of that, not a script.
Where a charge is itemised the engine can reconstruct its rate from the client's own
invoices; where it is bundled, nothing in the file can price the leg and the interface
has to ask for a rate card. Neither behaviour is coded per scenario -- both fall out
of the data.

This module holds only what all three share: the charge-code register and its long
tail, the bundled codes, reporting FX, and the per-world contract documented in
``REQUIRED_WORLD_NAMES``.

Each world lives in ``generator/worlds/`` and supplies the rest: identity, geography,
suppliers, sites (with its own deliberate string drift), true pricing, and a billing
block naming its granularity.
"""

# ----------------------------------------------------------------------------------
# Charge register. ``pool`` is the cost pool the code rolls into.
#
# ``spellings`` reproduces the single most consequential piece of real-world mess:
# one code arriving under several free-text descriptions. Code 1638 is the
# destination delivery charge the engine derives a per-container rate from, and it
# turns up under four different names.
# ----------------------------------------------------------------------------------
CHARGE_CODES = {
    # --- freight --------------------------------------------------------------
    "1301": {"pool": "Freight", "spellings": [
        "Oceanfreight - FCL", "Oceanfreight - FCL & Services", "Ocean Freight FCL"]},
    "1302": {"pool": "Freight", "spellings": ["Oceanfreight - LCL", "Ocean Freight - LCL"]},
    "1101": {"pool": "Freight", "spellings": ["Airfreight"]},
    "1401": {"pool": "Freight", "spellings": ["Road Freight - Domestic"]},
    # --- origin, itemised. Every EXW component is its own coded line, which is
    #     what lets the engine derive origin rates without a rate card.
    "1631": {"pool": "Origin Pickup", "spellings": ["EXW Collection", "EXW Collection Charges"]},
    "1632": {"pool": "Origin Other", "spellings": ["EXW Terminal Handling (THC)"]},
    "1633": {"pool": "Origin Other", "spellings": ["EXW VGM Filing"]},
    "1634": {"pool": "Origin Other", "spellings": ["EXW Seal Fee"]},
    "1635": {"pool": "Origin Other", "spellings": ["EXW Export Documentation"]},
    "1636": {"pool": "Origin Other", "spellings": ["EXW Customs Export Declaration"]},
    "1637": {"pool": "Origin Other", "spellings": ["EXW Origin Service Fee"]},
    "1601": {"pool": "Origin Other", "spellings": ["Origin Handling"]},
    "1602": {"pool": "Origin Other", "spellings": ["Origin Drayage to Port"]},
    # --- destination ----------------------------------------------------------
    # The rate the engine derives. Four descriptions, one code.
    "1638": {"pool": "Destination Drop-off", "spellings": [
        "DAP Charges - 40' HC",
        "DAP + Clearance",
        "Destination DAP Charges + Delivery",
        "DAP Delivery Charges",
    ]},
    # These sit in the same pool but must never enter the 1638 rate.
    "1503": {"pool": "Destination Drop-off", "spellings": ["Import Trucking", "Import Trucking - 40'hc"]},
    "1505": {"pool": "Destination CFS", "spellings": ["Destination Terminal Handling"]},
    "1511": {"pool": "Destination Other", "spellings": ["Destination Port Charges"]},
    # A lookalike description under a different code. Excluded from the 1638 rate,
    # exactly as in the live model.
    "1411": {"pool": "Destination Other", "spellings": ["Destination DAP charges"]},
    # --- documentation --------------------------------------------------------
    "1620": {"pool": "Origin Other", "spellings": ["Bill of Lading Fee"]},
    "1600": {"pool": "Origin Other", "spellings": ["Outlay Fee", "Outlay Fee 2.5 %"]},
    # --- the bundles ----------------------------------------------------------
    # Codes that carry several legs on one line. A forwarder billing this way costs
    # the client nothing in dollars and everything in attributability: the money
    # reconciles to the cent and no rate can be derived from any of it.
    #
    # The spellings are deliberately reassuring, because that is how they read on a
    # real invoice. "Origin Charges - All In" looks like an answer and is a wall.
    "1630": {"pool": "Origin Pickup", "spellings": [
        "Origin Charges - All In", "Origin Charges (All Inclusive)",
        "EXW Origin Charges - Consolidated"]},
    "1300": {"pool": "Freight", "spellings": [
        "Ocean Freight & Delivery", "Oceanfreight incl. Destination Delivery",
        "Ocean Freight - Port to Door"]},
}

# What each bundled code swallows.
#
# The generator sums the true component amounts onto the bundle rather than inventing
# a separate figure, so a bundled world charges its client exactly what the itemised
# equivalent would. Only the visibility differs -- which is precisely what makes the
# three scenarios comparable, and what lets the demo say "the money is all here, it
# just cannot be attributed to a leg" and mean it.
BUNDLES = {
    "1630": ["1631", "1632", "1633", "1634", "1635", "1636", "1637"],
    "1300": ["1301", "1638"],
}

# The long tail. Real charge-line exports carry dozens of codes that fire a
# handful of times a year -- an exam fee here, a detention charge there. They are
# a small share of the dollars and none of them drive a rate.
#
# Every code the seeded demo can emit has an explicit pool. Unknown codes remain a real
# upload condition that the engine detects, but deliberately manufacturing that failure
# into the sample files made a successful demo depend on costs it could not classify.
RARE_CHARGE_CODES = {
    "1199": {"pool": "Destination Other", "spellings": ["Customs Check and Exam Fee"]},
    "1203": {"pool": "Destination Other", "spellings": ["Import Customs Formalities"]},
    "1217": {"pool": "Destination Other", "spellings": ["Import VAT Outlay"]},
    "1314": {"pool": "Destination Other", "spellings": ["Demurrage / Detention"]},
    "1336": {"pool": "Destination Other", "spellings": ["Detention"]},
    "1618": {"pool": "Origin Other", "spellings": ["Hazardous Surcharge"]},
    "1619": {"pool": "Origin Other", "spellings": ["Overweight Surcharge"]},
    "1621": {"pool": "Origin Other", "spellings": ["Telex Release Fee"]},
    "1641": {"pool": "Destination Other", "spellings": ["ISC2 Fee (Destination Europe)"]},
    "1706": {"pool": "Destination CFS", "spellings": ["Customs Storage Charges"]},
    "1713": {"pool": "Destination CFS", "spellings": ["Bonded Warehouse Charges"]},
    "1299": {"pool": "Destination Other",
             "spellings": ["Other Customs Charges - stamp duty",
                           "Other Customs Charges - bonded transfer"]},
    "1799": {"pool": "Destination CFS",
             "spellings": ["Miscellaneous Warehouse Charge"]},
    "1888": {"pool": "Destination Other",
             "spellings": ["Adjustment - Prior Period"]},
    "1902": {"pool": "Destination Other",
             "spellings": ["Third Party Survey Fee"]},
}

# Every code the generator can emit, main register and long tail together.
ALL_CHARGE_CODES = {**CHARGE_CODES, **RARE_CHARGE_CODES}

# Reporting FX. The demo bills in three currencies; everything reports in USD.
FX_TO_USD = {"USD": 1.0, "GBP": 1.34, "EUR": 1.09}


def exw_ready_weekday(region):
    """The weekday a region's suppliers declare cargo ready.

    Factories do not finish production on uniformly random days. They work to a weekly
    ex-works schedule -- goods are packed, declared ready and made available for
    collection on the same day each week -- and a forwarder's collection round follows it.

    Modelling ready dates as a uniform draw over the year, which is the obvious thing to
    do, quietly destroys the structure the whole inbound question turns on: with no two
    suppliers in a region ever ready on the same day, no trailer can ever pool anything,
    and the model concludes that tendering the inbound leg is worthless for a reason that
    is an artefact of the generator rather than a property of freight.

    Derived from the region's name rather than drawn, so it is stable across regenerations
    and consumes no randomness.
    """
    return sum(ord(ch) for ch in str(region)) % 5


# ----------------------------------------------------------------------------------
# The per-world contract.
#
# A world module is a plain module supplying every name below. It is checked at load
# time rather than discovered halfway through a run, because a missing name would
# otherwise surface as an AttributeError three thousand rows in.
# ----------------------------------------------------------------------------------
REQUIRED_WORLD_NAMES = [
    # identity
    "SCENARIO_ID", "CLIENT_COMPANY", "CLIENT_SHORT", "SUMMARY", "SEED",
    "INVOICE_PREFIX", "BILL_TO_PARTY", "CONSIGNEE_BY_COUNTRY", "INVOICE_CLERKS",
    "CURRENCY_WEIGHTS",
    # geography
    "ORIGINS", "ORIGIN_WEIGHTS", "PORTS", "POD_WEIGHTS", "TRANSSHIP",
    "DELIVERY_SITES", "SITE_WEIGHTS", "SUPPLIERS", "PICKUP_REGIONS",
    # commercial
    "TRUE_RATES", "SERVICE_QUOTE", "FTL_QUOTE", "BILLING", "BOOKING",
    # scale
    "N_GROUPS",
]

BILLING_KEYS = {"origin", "destination", "origin_drayage_share"}


def check(world):
    """Fail loudly and early if a world module is incomplete or self-contradictory."""
    name = getattr(world, "SCENARIO_ID", world.__name__)
    missing = [n for n in REQUIRED_WORLD_NAMES if not hasattr(world, n)]
    if missing:
        raise AttributeError(f"world {name} is missing {', '.join(missing)}")

    unknown = set(world.BILLING) - BILLING_KEYS
    if unknown:
        raise ValueError(f"world {name}: unknown BILLING keys {sorted(unknown)}")
    for field in ("origin", "destination"):
        if world.BILLING.get(field) not in ("itemised", "bundled"):
            raise ValueError(
                f"world {name}: BILLING[{field!r}] must be 'itemised' or 'bundled'")

    # Weights are keyed by name rather than positionally, so a port added to PORTS and
    # forgotten in POD_WEIGHTS is a hard error instead of a silently-zero lane.
    if set(world.POD_WEIGHTS) != set(world.PORTS):
        raise ValueError(f"world {name}: POD_WEIGHTS does not cover PORTS exactly")
    if set(world.ORIGIN_WEIGHTS) != set(world.ORIGINS):
        raise ValueError(f"world {name}: ORIGIN_WEIGHTS does not cover ORIGINS exactly")

    # Every site has to be reachable from the port that serves it, and every supplier
    # has to sit in a region the origin pricing knows about.
    pods = {s["pod"] for s in world.DELIVERY_SITES}
    if not pods <= set(world.PORTS):
        raise ValueError(f"world {name}: sites served by unknown ports "
                         f"{sorted(pods - set(world.PORTS))}")
    regions = {s["region"] for s in world.SUPPLIERS}
    if not regions <= set(world.TRUE_RATES["exw"]):
        raise ValueError(f"world {name}: suppliers in unpriced regions "
                         f"{sorted(regions - set(world.TRUE_RATES['exw']))}")

    # The busiest port must have at least as many site weights as it has sites.
    busiest = max(sum(1 for s in world.DELIVERY_SITES if s["pod"] == p)
                  for p in world.PORTS)
    if len(world.SITE_WEIGHTS) < busiest:
        raise ValueError(f"world {name}: SITE_WEIGHTS has {len(world.SITE_WEIGHTS)} "
                         f"entries but one port serves {busiest} sites")
    return world
