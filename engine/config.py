"""Every constant the engine applies, and where it came from.

Nothing numeric may live anywhere else in the engine. Each entry carries a
``label`` the interface can read out loud while the step that uses it runs, and a
``source`` saying who is accountable for the figure. A prospect asking "where did
64.5 come from?" gets an answer from the screen, not from us.

The split that matters:

    PHYSICAL and DISPATCH  are limits and operating choices. A client can argue
                           with them, so they are editable.
    NEW_STEP_RATES         price a step that has never happened. No invoice can
                           evidence them, so they are declared, not derived, and
                           the workbook says so on every dollar they touch.
"""

# --------------------------------------------------------------------------------------
# Physical limits of an outbound container, and the operating targets that decide
# when one is dispatched rather than held for more cargo.
# --------------------------------------------------------------------------------------
CONFIG = {
    "OUT_CBM_MAX": {
        "value": 64.5, "unit": "CBM", "group": "physical",
        "label": "Outbound container volume cap",
        "source": "Client operational SOP figure for a 40'HC. Not ours.",
    },
    "OUT_PALLET_MAX": {
        "value": 48, "unit": "pallets", "group": "physical",
        "label": "Outbound container pallet cap",
        "source": "24 paired floor positions, on the stated assumption that every "
                  "Euro pallet double-stacks.",
    },
    "OUT_WEIGHT_MAX_KG": {
        "value": 26000.0, "unit": "kg", "group": "physical",
        "label": "Outbound container payload cap",
        "source": "Standard 40'HC payload limit.",
    },
    # The inbound trailer. Capped three ways like a container and for the same reason:
    # a load stops at whichever of floor space, volume and payload it reaches first.
    # These decide how many trucks the plan has to buy, so they are as consequential
    # as the container caps and just as editable.
    "TRAILER_PALLET_MAX": {
        "value": 66, "unit": "pallets", "group": "physical",
        "label": "Inbound trailer pallet cap",
        "source": "33 Euro pallet floor positions on a 13.6m curtain-side trailer, "
                  "double stacked. Held to the same stacking assumption as the container "
                  "cap above, because it is the same cargo: allowing pallets to stack in "
                  "a box and not on a truck would make the road leg look worse than it is "
                  "for no reason anybody could point to.",
    },
    "TRAILER_CBM_MAX": {
        "value": 76.0, "unit": "CBM", "group": "physical",
        "label": "Inbound trailer volume cap",
        "source": "Usable load volume of a 13.6m trailer — slightly more than a 40'HC, "
                  "which is why volume rather than floor space is what a full load "
                  "usually runs out of.",
    },
    "TRAILER_WEIGHT_MAX_KG": {
        "value": 24000.0, "unit": "kg", "group": "physical",
        "label": "Inbound trailer payload cap",
        "source": "Typical road payload before an axle permit is needed.",
    },
    # Dispatch targets are a share of their cap, never a free-standing number. Stated
    # absolutely they can drift above the limit they are supposed to sit under, and
    # nothing in the arithmetic notices.
    "OUT_CBM_TARGET_PCT": {
        "value": 0.80, "unit": "of the volume cap", "group": "dispatch",
        "label": "Dispatch at this share of the volume cap",
        "source": "Reaching either target permits dispatch. A container does not have to "
                  "be full to be worth sending.",
    },
    "OUT_PALLET_TARGET_PCT": {
        "value": 0.79, "unit": "of the pallet cap", "group": "dispatch",
        "label": "Dispatch at this share of the pallet cap",
        "source": "Held at roughly the same ratio as the volume target so neither "
                  "measure dominates.",
    },
    "MAX_DWELL_DAYS": {
        "value": 14, "unit": "days", "group": "dispatch",
        "label": "Maximum warehouse dwell",
        "source": "Client-mandated. Measured from the oldest pallet in the box "
                  "becoming ready. A box at the cap sails whether it is full or not.",
    },
    "POOL_KEY": {
        "value": "cfs_pod_site", "unit": "", "group": "dispatch",
        "label": "What may share a container",
        "source": "cfs_pod_site puts exactly one delivery site in every container. "
                  "cfs_pod lets sites mix but never countries.",
    },
    "CFS_TO_VESSEL_DAYS": {
        "value": 1, "unit": "days", "group": "dispatch",
        "label": "Days from last pallet ready to sailing",
        "source": "A box cannot sail on the day its final pallet is declared ready. "
                  "The only invented figure in the lead-time model.",
    },
    # The commercial adoption gate. Packing fewer boxes is necessary but not sufficient:
    # a lane also has to clear either the annual-dollar hurdle or the percentage hurdle.
    # Keeping both figures in CONFIG makes the verdict reproducible and auditable rather
    # than prose invented after the result is known.
    "LANE_MIN_SAVING_USD": {
        "value": 25000.0, "unit": "USD per year", "group": "decision",
        "label": "Minimum annual saving to consolidate a lane",
        "source": "Demo adoption rule. A lane may also qualify by clearing the percentage "
                  "threshold; either hurdle is enough.",
    },
    "LANE_MIN_SAVING_PCT": {
        "value": 0.05, "unit": "of today's lane cost", "group": "decision",
        "label": "Minimum percentage saving to consolidate a lane",
        "source": "Demo adoption rule. Applied to each origin–port–destination-site lane, "
                  "including when several sites share a container.",
    },
    # ----------------------------------------------------------------------------------
    # The consolidation service.
    #
    # Consolidation builds containers at a warehouse the client does not use today, so
    # no invoice in the file prices any of it and no rate card row covers it either.
    # That does NOT make these figures invented. A forwarder quotes this service, and a
    # quoted rate for work not yet bought is evidence -- it is simply evidence of a
    # different kind from an invoice.
    #
    # So each of these carries a pricing source. Marked as quoted, it is the client's
    # own commercial number and the model rests on nothing asserted. Marked as a
    # benchmark, it is our figure standing in until they get a real quote, and the
    # provenance strip says so and counts the dollars.
    # ----------------------------------------------------------------------------------
    "CFS_INBOUND_PER_DELIVERY": {
        "value": 145.0, "unit": "USD per delivery", "group": "service",
        "label": "Receiving an inbound delivery",
        "source": "Every load that arrives at the consolidation warehouse has to be "
                  "unloaded, checked against its packing list, labelled and put away "
                  "before it can be built into anything. Charged once per delivery "
                  "received, so it is the cost of how *often* cargo turns up rather than "
                  "how much of it there is -- which is why buying the inbound leg as "
                  "fewer, fuller loads reduces it.",
        "quoted_note": "Your forwarder's inbound receiving charge at the consolidation "
                       "warehouse.",
        "benchmark_note": "Our benchmark for receiving and putting away one inbound "
                          "delivery, standing in until you have a quote.",
    },
    "CFS_HANDLING_PER_CONTAINER": {
        "value": 1000.0, "unit": "USD per container", "group": "service",
        "label": "Building a container at the warehouse",
        "source": "Charged once per container built at the consolidation warehouse.",
        "quoted_note": "Your forwarder's quote for handling at the consolidation warehouse.",
        "benchmark_note": "Our benchmark for CFS handling on an Asia-Europe lane, standing "
                          "in until you have a quote.",
    },
    "CFS_DRAYAGE_PER_CONTAINER": {
        "value": 325.0, "unit": "USD per container", "group": "service",
        "label": "Warehouse to port drayage",
        "source": "Short haul from the consolidation warehouse to the loading port.",
        "quoted_note": "Your forwarder's quote for the warehouse-to-port move.",
        "benchmark_note": "Our benchmark for a short port drayage, standing in until you "
                          "have a quote.",
    },
    "CFS_STORAGE_FREE_DAYS": {
        "value": 7, "unit": "days", "group": "service",
        "label": "Storage free period",
        "source": "Days a pallet may sit before storage begins to bill.",
        "quoted_note": "The free period in your forwarder's warehouse terms.",
        "benchmark_note": "A typical free period, standing in until you have terms.",
    },
    "CFS_STORAGE_PER_CBM_DAY": {
        "value": 0.45, "unit": "USD per CBM per day", "group": "service",
        "label": "Storage beyond the free period",
        "source": "Charged on pallet volume for each day past the free period.",
        "quoted_note": "Your forwarder's storage rate.",
        "benchmark_note": "Our benchmark storage rate, standing in until you have a quote.",
    },
    "DECONSOL_PER_EXTRA_SITE": {
        "value": 850.0, "unit": "USD per extra site", "group": "service",
        "label": "Destination strip",
        "source": "Only bites when sites are allowed to share a container, and it is four "
                  "jobs rather than one: the box is drayed to a bond store instead of "
                  "straight to the door, devanned and re-palletised, held and re-loaded, "
                  "then delivered a second time. That is the cost the fuller container "
                  "has to cover. Zero under one-site-per-container.",
        "quoted_note": "Your forwarder's quote for stripping and onward local delivery.",
        "benchmark_note": "Our benchmark for a destination strip, standing in until you "
                          "have a quote.",
    },
}

# The consolidation-service rates, in the order they occur physically. Each is priced
# from an uploaded quote, from a figure the client typed on the settings step, or from
# our benchmark.
#
# The default is the benchmark, and it has to be: it applies where the client has told us
# nothing about a rate, and a figure nobody has given us is ours. Defaulting to "quoted"
# had the provenance strip crediting a quote that had never arrived — and that strip is
# the one claim on the results screen that must be beyond argument.
SERVICE_RATE_KEYS = [k for k, v in CONFIG.items() if v["group"] == "service"]
SERVICE_PRICING_DEFAULT = "benchmark"     # "quoted" | "edited" | "benchmark"


# --------------------------------------------------------------------------------------
# Cost pools. Fixed order -- the workbook, the waterfall and the ledger all read
# left to right in this sequence, following the cargo from factory to warehouse.
# --------------------------------------------------------------------------------------
COST_POOLS = [
    "Freight",
    "Origin Pickup",
    "Origin CFS",
    "Origin Other",
    "Destination CFS",
    "Destination Drop-off",
    "Destination Other",
]

# Pools that exist only because consolidation introduces them. Zero in every
# historical invoice, non-zero in the model -- which is why the cost waterfall has
# to show origin cost rising even as the total falls.
NEW_STEP_POOLS = {"Origin CFS"}

# --------------------------------------------------------------------------------------
# The engine's charge-code register.
#
# This is the engine's own knowledge, not the client's. A code absent from here is
# NOT dropped: it is reported, its dollars stay in the reconciliation, and the
# interface says how many and how much. Silently discarding a charge is the
# fastest way to lose an audit.
# --------------------------------------------------------------------------------------
CHARGE_CODE_POOLS = {
    # freight
    "1101": "Freight", "1301": "Freight", "1302": "Freight", "1401": "Freight",
    # origin, itemised
    "1631": "Origin Pickup",
    "1632": "Origin Other", "1633": "Origin Other", "1634": "Origin Other",
    "1635": "Origin Other", "1636": "Origin Other", "1637": "Origin Other",
    "1601": "Origin Other", "1602": "Origin Other",
    "1618": "Origin Other", "1619": "Origin Other", "1620": "Origin Other",
    "1621": "Origin Other", "1600": "Origin Other",
    # destination
    "1638": "Destination Drop-off", "1503": "Destination Drop-off",
    "1505": "Destination CFS", "1706": "Destination CFS", "1713": "Destination CFS",
    "1511": "Destination Other", "1411": "Destination Other",
    "1199": "Destination Other", "1203": "Destination Other",
    "1217": "Destination Other", "1314": "Destination Other",
    "1299": "Destination Other", "1336": "Destination Other",
    "1641": "Destination Other", "1799": "Destination CFS",
    "1888": "Destination Other", "1902": "Destination Other",
    # bundled codes -- see BUNDLED_CODES below
    "1630": "Origin Pickup", "1300": "Freight",
}

# --------------------------------------------------------------------------------------
# Codes that arrive as a bundle.
#
# Not every forwarder itemises. Some bill one all-in line where another bills seven,
# and a bundled line is the single most consequential difference between one client's
# export and another's: the dollars are all present and reconcile to the cent, but
# they cannot be attributed to a leg, so no rate can be derived from them.
#
# Declaring the bundles here rather than inferring them means the interface can say
# exactly why a leg is unpriceable -- "code 1630 rolls collection, terminal handling,
# VGM, seal, documents, customs and the origin service fee into one line" -- instead of
# reporting an absence it cannot explain.
#
# ``pool`` is a compromise and the register admits it. A bundle spanning pools has to
# land in one of them, so it lands where the largest share of its money belongs. That
# distorts the pool breakdown, which is a real cost of bundled billing and is reported
# rather than smoothed over.
# --------------------------------------------------------------------------------------
BUNDLED_CODES = {
    "1630": {
        "covers": ["1631", "1632", "1633", "1634", "1635", "1636", "1637"],
        "label": "Origin Charges - All In",
        "note": "Collection, terminal handling, VGM, seal, export documents, customs "
                "declaration and the origin service fee, on one line.",
        "blocks": "No origin rate can be derived: the collection charge cannot be "
                  "separated from the terminal mechanics bundled with it.",
    },
    "1300": {
        "covers": ["1301", "1638"],
        "label": "Ocean Freight & Delivery",
        "note": "Sea freight and destination delivery billed together, port to door.",
        "blocks": "Neither an ocean rate nor a delivery rate can be derived: the two "
                  "legs share one figure and consolidation changes only one of them.",
    },
}

# The destination delivery rate is code 1638 and nothing else.
#
# These codes sit in destination pools and look like delivery charges -- 1411's
# description is literally "Destination DAP charges" -- but they price different
# work. Letting any of them into the per-container rate would inflate every
# modelled delivery. The rule is the same one the live model applies.
DAP_RATE_CODE = "1638"
DAP_RATE_EXCLUDED_CODES = frozenset({"1503", "1505", "1511", "1411", "1706", "1713"})

# The itemised origin components, in the order they occur physically.
EXW_COMPONENT_CODES = ["1631", "1632", "1633", "1634", "1635", "1636", "1637"]

# Collection is the one origin component that is not bought per outbound container.
#
# Every other component on this list is incurred by a container: a terminal handles one,
# a document covers one, a VGM weighs one. Collection is incurred by *cargo*. A truck goes
# to a factory, takes what is there and brings it in, and how many truck runs that needs
# is set by the volume the supplier has ready -- not by how the warehouse later chooses to
# pack it. Consolidation does not visit fewer factories or move fewer cubic metres, so it
# does not buy fewer collections.
#
# Charging it per modelled container, as every other origin component correctly is, had
# the plan paying collection on 420 boxes where the client pays it on 521 inbound loads:
# roughly $100k a year of saving that came from nothing but the denominator, on a leg the
# plan does not touch. So the rate stays per container -- that is how the invoices bill it
# and how the card quotes it -- and the QUANTITY charged is the shipment's own inbound load
# count, spread across whichever containers its pallets end up in. Modelled collection
# then equals invoiced collection, and the only way to move it is to buy the leg
# differently, which is what the FTL alternative on this component is for.
PICKUP_CODE = "1631"
CONTAINER_COMPONENT_CODES = [c for c in EXW_COMPONENT_CODES if c != PICKUP_CODE]


# --------------------------------------------------------------------------------------
# The cost components the model has to price, and where each one can get its price.
#
# This is the sourcing plan, and it is the part of the engine a client actually argues
# with. Every leg of the journey is one component, and each component lists the sources
# that could price it, best first. The engine works down the list, takes the first that
# holds, and says which one it took.
#
# Source kinds:
#   derive     reconstruct the rate from the client's own charge lines, using the codes
#              named here. The gold standard: their money, their volumes.
#   analogue   the same, but the population prices ADJACENT work -- the right kind of
#              charge on the wrong leg. Directionally sound, and labelled as such,
#              because presenting it as a clean derivation would be a quiet lie.
#   card       a rate card the client uploaded. Beats a derivation when present: a
#              contracted rate is what they will actually be billed.
#   service    the consolidation service, priced from their forwarder's quote or from
#              our benchmark -- see the ``service`` group above.
#
# A component whose every source fails is UNPRICED, and the interface asks for a rate
# card rather than quietly reaching for a number.
# --------------------------------------------------------------------------------------
COST_COMPONENTS = [
    {
        "key": "origin_collection",
        "label": "Supplier to warehouse",
        "leg": "Origin",
        "sub": "Collecting finished goods from the supplier and running them into the "
               "consolidation warehouse. Bought per load on the road, so consolidating "
               "changes it only if the loads themselves change.",
        "pools": ["Origin Pickup"],
        "sources": [
            {"kind": "card", "category": "ORIGIN_COMPONENT", "codes": [PICKUP_CODE]},
            {"kind": "derive", "codes": [PICKUP_CODE], "term": "EXW",
             "note": "Your EXW collection charges, which already price this exact move."},
        ],
        # An alternative is not a fallback. Every source above prices this leg the way the
        # client already buys it -- one collection charge per shipment, however small the
        # shipment is -- and an alternative prices it a different way, displacing the
        # chosen source only if it actually comes out cheaper against the plan's real
        # volumes.
        #
        # This is the leg where that question is worth asking, and it is worth asking
        # because consolidation changes the physics of it. Today every load on the road
        # carries one supplier's cargo, because it is going to a port CFS to be stuffed
        # into that supplier's own container. Under the plan the destination is a warehouse
        # that is going to mix the cargo anyway, so one trailer can sweep up three
        # suppliers in a region on the same day -- and the trailer count is a bin-pack
        # against real dates, not a shipment count.
        #
        # Two costs move together when it does, and the second is the one that gets
        # forgotten: the haul is bought per trailer instead of per load, and the warehouse
        # receives far fewer deliveries, so it charges for far fewer. That second effect is
        # usually what decides it, and it is a warehouse saving rather than a trucking one.
        "alternatives": [
            {"key": "ftl", "kind": "card", "category": "FTL", "codes": ["INBOUND_FTL"],
             "label": "Full trailer loads, tendered by pickup region",
             "basis": "per trailer load",
             "note": "One dedicated trailer per region per day instead of one collection "
                     "per shipment, with the load bin-packed against the trailer's pallet, "
                     "volume and payload caps.",
             "ask": "Consolidating lets the same cargo come in as full trailer loads "
                    "instead of one collection per shipment. That is enough volume to "
                    "tender, and you have no trailer rate on file. Give us one and we "
                    "will pack the trailers off your own dates and test it.",
             "plan_neutral": "The container plan is identical either way — how cargo "
                             "reaches the warehouse does not change what gets built "
                             "there. Only the inbound bill moves."},
        ],
    },
    {
        "key": "origin_terminal",
        "label": "Origin terminal and export documents",
        "leg": "Origin",
        "sub": "Terminal handling, VGM, seal, export declaration and documentation at the "
               "loading port.",
        "pools": ["Origin Other"],
        "sources": [
            {"kind": "card", "category": "ORIGIN_COMPONENT",
             "codes": ["1632", "1633", "1634", "1635", "1636", "1637"]},
            {"kind": "derive", "codes": ["1632", "1633", "1634", "1635", "1636", "1637"],
             "term": "EXW",
             "note": "Your itemised origin charges, one derived rate per component."},
        ],
    },
    {
        "key": "warehouse_inbound",
        "label": "Receiving cargo at the warehouse",
        "leg": "Origin",
        "sub": "Unloading each inbound delivery, checking it against its packing list and "
               "putting it away. Charged per delivery received, so fewer and fuller loads "
               "cost less.",
        "pools": ["Origin CFS"],
        "sources": [
            {"kind": "card", "category": "CONSOLIDATION", "codes": ["CFS_INBOUND"]},
            {"kind": "service", "config_key": "CFS_INBOUND_PER_DELIVERY"},
        ],
    },
    {
        "key": "warehouse_handling",
        "label": "Building the container at the warehouse",
        "leg": "Origin",
        "sub": "Receiving pallets, building and sealing the outbound container. The step "
               "consolidation is entirely made of.",
        "pools": ["Origin CFS"],
        "sources": [
            {"kind": "card", "category": "CONSOLIDATION", "codes": ["CFS_HANDLING"]},
            {"kind": "service", "config_key": "CFS_HANDLING_PER_CONTAINER"},
        ],
    },
    {
        "key": "warehouse_to_port",
        "label": "Warehouse to loading port",
        "leg": "Origin",
        "sub": "Moving the finished container from the warehouse to the quay. Priced as a "
               "drayage or as an FTL run depending on the distance.",
        "pools": ["Origin CFS"],
        "sources": [
            {"kind": "card", "category": "CONSOLIDATION", "codes": ["CFS_DRAYAGE"]},
            # The right charge on the wrong leg: this population is the supplier-to-port
            # run, and what the model needs is warehouse-to-port. Same truck, same
            # region, different journey -- usable, and only with the caveat attached.
            #
            # Note there is deliberately no clean ``card`` source on code 1602. A carded
            # 1602 rate has exactly the same wrong-leg problem as a derived one, so it
            # arrives here as an analogue whichever file it came in. Accepting it as a
            # firm card rate while caveating the identical derived figure would be
            # incoherent, and the incoherence would be invisible on screen.
            {"kind": "analogue", "codes": ["1602"], "term": "EXW",
             "cards": [{"category": "ORIGIN_COMPONENT", "codes": ["1602"]}],
             "note": "Your origin drayage charges price the supplier-to-port run, not the "
                     "warehouse-to-port run the plan needs. Same truck and same region, "
                     "shorter journey — a sound starting point, not the real rate.",
             "caveat": "priced off the supplier-to-port move, not warehouse-to-port"},
            {"kind": "service", "config_key": "CFS_DRAYAGE_PER_CONTAINER"},
        ],
        # There is deliberately no alternative here. Moving a sealed 40' box from the
        # warehouse to the quay IS a drayage: there is no cheaper way to buy it and no
        # bin-packing to do, because the unit being moved is one container. The question
        # of how to buy road transport belongs on the inbound leg, where the unit is a
        # pallet and the count is therefore ours to change.
    },
    {
        "key": "warehouse_storage",
        "label": "Storage while a container fills",
        "leg": "Origin",
        "sub": "Pallets waiting at the warehouse for the rest of their container, beyond "
               "the free period.",
        "pools": ["Origin CFS"],
        "sources": [
            {"kind": "card", "category": "CONSOLIDATION", "codes": ["CFS_STORAGE"]},
            {"kind": "service", "config_key": "CFS_STORAGE_PER_CBM_DAY"},
        ],
    },
    {
        "key": "ocean_freight",
        "label": "Ocean freight",
        "leg": "Freight",
        "sub": "Loading port to discharge port, per container.",
        "pools": ["Freight"],
        "sources": [
            {"kind": "card", "category": "OCEAN", "codes": ["1301"]},
            {"kind": "derive", "codes": ["1301"],
             "note": "Your own ocean freight invoices, divided by the containers they moved."},
        ],
    },
    {
        "key": "destination_delivery",
        "label": "Discharge port to warehouse",
        "leg": "Destination",
        "sub": "The last mile from the quay to the delivery site, per container.",
        "pools": ["Destination Drop-off"],
        "sources": [
            {"kind": "card", "category": "DEST_DELIVERY", "codes": [DAP_RATE_CODE]},
            {"kind": "derive", "codes": [DAP_RATE_CODE],
             "note": "Your code-1638 delivery charges only. Codes that look like delivery "
                     "but price other work are excluded."},
        ],
    },
    {
        "key": "destination_terminal",
        "label": "Destination terminal, port charges and the strip",
        "leg": "Destination",
        "sub": "Terminal handling and port charges at destination, plus breaking apart any "
               "container carrying cargo for more than one warehouse.",
        "pools": ["Destination CFS", "Destination Other"],
        "sources": [
            {"kind": "card", "category": "DEST_TERMINAL",
             "codes": ["1505", "1511", "1411"]},
            {"kind": "derive", "codes": ["1505", "1511", "1411"], "fleet_wide": True,
             "note": "Your destination terminal and port charges, spread across every "
                     "container in the period."},
            {"kind": "service", "config_key": "DECONSOL_PER_EXTRA_SITE"},
        ],
    },
]

COMPONENTS_BY_KEY = {c["key"]: c for c in COST_COMPONENTS}
COMPONENT_LEGS = ["Origin", "Freight", "Destination"]

# A derivation needs enough invoices behind it to be a rate rather than an anecdote.
# Below this, the population is reported as thin and the interface asks for a card --
# three invoices can produce a confident-looking number that means nothing.
MIN_DERIVE_GROUPS = 25

# --------------------------------------------------------------------------------------
# Limits that come in pairs: a hard cap, and the share of it that releases a container
# for dispatch. Weight is deliberately absent -- a container is never sent because it
# is heavy enough, only because it is full enough, so a weight target would be a
# control that changes nothing.
# --------------------------------------------------------------------------------------
LIMIT_PAIRS = [
    {"max": "OUT_CBM_MAX", "pct": "OUT_CBM_TARGET_PCT",
     "derived": "OUT_CBM_TARGET", "unit": "CBM", "decimals": 1},
    {"max": "OUT_PALLET_MAX", "pct": "OUT_PALLET_TARGET_PCT",
     "derived": "OUT_PALLET_TARGET", "unit": "pallets", "decimals": 0},
]
UNPAIRED_LIMITS = ["OUT_WEIGHT_MAX_KG"]


# Convenience: bare values, for the arithmetic.
def values(overrides=None):
    """CONFIG as a plain name -> value dict, with any user edits applied.

    Dispatch targets are computed from their cap rather than stored, so a target can
    never exceed the limit it sits under.

    The interface hands back only the keys a user actually changed, so an
    unrecognised key is a bug rather than something to tolerate quietly.
    """
    out = {k: v["value"] for k, v in CONFIG.items()}
    for key, value in (overrides or {}).items():
        if key not in out:
            raise KeyError(f"unknown configuration key: {key}")
        out[key] = value

    for pair in LIMIT_PAIRS:
        cap, share = out[pair["max"]], out[pair["pct"]]
        target = cap * share
        out[pair["derived"]] = (max(1, int(round(target))) if pair["decimals"] == 0
                                else round(target, pair["decimals"]))
    return out


def describe_pair(cfg, pair):
    """'80% of 64.5 CBM = 51.6 CBM' -- so the resulting figure is never a mystery."""
    fmt = f"{{:,.{pair['decimals']}f}}"
    return (f"{cfg[pair['pct']]:.0%} of {fmt.format(cfg[pair['max']])} "
            f"= {fmt.format(cfg[pair['derived']])} {pair['unit']}")


# --------------------------------------------------------------------------------------
# Scope. Consolidation applies to ocean cargo the client controls the origin of.
# Air and road cannot be consolidated into a container, and on DAP/DDP/CIF terms
# the supplier or carrier controls the leg, so there is nothing for us to combine.
# --------------------------------------------------------------------------------------
IN_SCOPE_TERMS = frozenset({"EXW", "FOB"})
IN_SCOPE_MODE_SUBSTRING = "OCEAN"
FCL_MODE = "OCEAN - FCL (AW)"

EQUIPMENT_COLS = ["20", "40", "40HQ", "45"]

# Container equivalents. The model builds 40'HC only, but the history books all
# four, and a container count that treats a 20ft as equal to a 45ft would misstate
# both today's cost and the saving.
EQUIPMENT_TEU_CBM = {"20": 33.0, "40": 64.5, "40HQ": 64.5, "45": 76.0}

# --------------------------------------------------------------------------------------
# Reporting FX. The client bills in three currencies and reports in USD. Rates are
# stated here so the share of cost carrying FX exposure can be published.
# --------------------------------------------------------------------------------------
REPORTING_FX_TO_USD = {"USD": 1.0, "GBP": 1.34, "EUR": 1.09}

# --------------------------------------------------------------------------------------
# Resolution thresholds. Above the auto threshold the engine resolves a mapping on
# its own and records the evidence; below it, a human decides. Tuned so the queue
# holds the genuinely ambiguous cases and nothing else -- a queue of thirty is a
# chore nobody works through, and a queue of zero means the engine is guessing
# silently.
# --------------------------------------------------------------------------------------
RESOLVE = {
    "AUTO_MATCH_RATIO": 0.86,       # string similarity above which a site alias auto-merges
    "UNLISTED_SITE_PALLET_SHARE": 0.07,  # unlisted site bigger than this needs confirming
    # Tokens that read like a region rather than a place you can deliver to.
    #
    # This is a HINT, not a classifier, and the distinction is the whole point. An
    # earlier version escalated a location only if it appeared on this list, which
    # meant every region the list had never heard of passed through as a town, with
    # no warning. Generic region names still need careful boundary matching.
    # -- and it caught Kent only because Kent was copied off a real file into the
    # list.
    #
    # Escalation is now decided by whether a location could be pinned to a site at
    # all. This list only reorders the options and adds a line of evidence once the
    # question is already being asked, so its gaps cost a slightly worse suggestion
    # rather than a silently wrong answer. It is non-exhaustive by design.
    "REGION_HINTS": frozenset({
        "kent", "essex", "surrey", "yorkshire", "midlands", "cornwall",
        "bavaria", "brabant", "limburg", "kocaeli", "cremona",
        "catalonia", "andalusia", "galicia", "veneto", "lombardy",
        "aragon", "wielkopolskie", "silesia", "normandie", "alentejo",
        "shropshire", "cumbria", "herefordshire", "lincolnshire",
    }),
    # Tokens that are not locations at all. Real exports are full of these.
    "PLACEHOLDER_TOKENS": frozenset({
        "city", "n/a", "na", "tbc", "tbd", "unknown", "-", "none", "various",
    }),
}

# --------------------------------------------------------------------------------------
# Which cities belong to which origin pickup region.
#
# An origin charge is priced against a region, so a supplier can only be costed
# once its pickup city is known to sit in one. The shipment file records whatever
# the booking system holds, which is frequently a procurement or head office
# rather than the factory the goods leave from -- a Manchester or Chicago address
# against cargo that sails from Asia.
#
# The engine will NOT guess a region from a supplier's name. An unrecognised city
# goes to the review queue with a proposal and its evidence, and the answer is
# recorded as a mapping the next run can simply read. Guessing here would put an
# invented rate into a costed model, which is the one thing the provenance claim
# cannot survive.
# --------------------------------------------------------------------------------------
PICKUP_REGION_CITIES = {
    # --- eastern China, Ningbo catchment ------------------------------------------
    "NINGBO": ["ningbo", "cixi", "taizhou", "yuyao", "zhoushan"],
    "HANGZHOU": ["hangzhou", "deqing", "jiaxing", "shaoxing", "shangyu"],
    "SUZHOU": ["suzhou", "wuxi", "kunshan", "changzhou", "taicang"],
    # --- Vietnam ------------------------------------------------------------------
    "BINH_DUONG": ["binh duong", "bien hoa", "long an", "tay ninh", "dong nai"],
    "HCMC": ["ho chi minh city", "can tho", "vung tau"],
    # --- northern China, Qingdao catchment ----------------------------------------
    "QINGDAO": ["qingdao", "jiaozhou", "rizhao", "laixi", "jimo"],
    "WEIFANG": ["weifang", "zibo", "linyi", "jinan", "dezhou", "zaozhuang"],
    "YANTAI": ["yantai", "penglai", "longkou", "weihai"],
    # --- India, Chennai catchment -------------------------------------------------
    "CHENNAI": ["chennai", "sriperumbudur", "ranipet", "kanchipuram", "gummidipoondi"],
    "COIMBATORE": ["coimbatore", "tiruppur", "hosur", "erode", "salem"],
    # --- southern China, Shenzhen catchment ---------------------------------------
    "SHENZHEN": ["shenzhen", "pingshan", "longgang", "baoan"],
    "DONGGUAN": ["dongguan", "humen", "changan", "huizhou", "boluo"],
    "FOSHAN": ["foshan", "shunde", "nanhai", "zhongshan", "jiangmen", "guangzhou"],
}

# Presentational pacing only. The engine's real work on this dataset finishes in
# about a second; each step is held to this floor so the build reads at human
# speed instead of flashing past. It changes no number. Set to 0.0 for tests.
STEP_MIN_SECONDS = 1.2
