#!/usr/bin/env python3
"""Generate the demo datasets -- one per invented client.

    python3 generator/make_demo_data.py                # all three
    python3 generator/make_demo_data.py --scenario meritt

Each scenario gets its own directory under ``data/``:

    <id>/charge_lines_raw.csv      the transactional upload -- messy, charge-line grain
    <id>/reference_pack.csv        every reference rate in one file: the one-click path
    <id>/door_charges.csv          \\
    <id>/port_and_ocean.csv         |  the same rows split three ways, so the demo can
    <id>/consolidation_quote.csv   /   show partial coverage instead of instant green
    <id>/ftl_rate_card.csv         the optional second click -- absent for meritt
    <id>/ground_truth_manifest.json  what the screen will say, so it can be rehearsed

plus ``data/scenarios.json``, the registry the app reads.

Everything is seeded per world, all iteration order is sorted, and no wall-clock is
read, so repeated runs are byte-identical. That is what makes the demo rehearsable: you
know the numbers before you walk into the room.

The charge-line files reproduce three specific pieces of real-world mess, each of which
stands between a raw invoice and a defensible rate:

    1.  ``USD Sales Amount`` carries the invoice total on the first line of an
        invoice and the literal string ``-related-`` on every other line. Summing
        the column multiplies the baseline by the number of charges per invoice.
    2.  The equipment columns are blank on roughly four rows in five. Container
        counts have to be rebuilt as max-per-master-bill.
    3.  One charge code arrives under several free-text descriptions -- code 1638,
        the destination delivery charge, appears under four.

Mixed date formats, a three-currency billing mix and out-of-scope transport modes
are also present but are handled quietly; they move no headline number. Duplicate
and credit lines are deliberately NOT generated -- they would cost demo time
without changing an answer.

The fourth difference is the one this file exists to produce, and it is not mess at
all: **how much the forwarder itemises.** Each world's ``BILLING`` block decides
whether origin charges arrive as seven coded lines or one, and whether freight and
delivery share a line. Nothing else about the world changes -- the client pays the
same money either way, and ``BUNDLES`` sums the true components onto the bundle rather
than inventing a figure. Only attributability differs, and that is what the References
board reads.
"""

import argparse
import csv
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

import scenarios as SC
import world as W

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# 18 months of history. Fixed, never read from the clock.
HISTORY_START = date(2025, 1, 6)
HISTORY_END = date(2026, 6, 26)

# Share of shipment groups that are in scope for consolidation: ocean freight on
# EXW or FOB terms. Everything else -- air, road, DAP/DDP/CIF -- is in the file
# because it is in the client's billing, and the engine has to exclude it.
IN_SCOPE_SHARE = 0.40

CHARGE_LINE_COLUMNS = [
    "CT #", "GRP #", "M #", "Client Company", "Shipping Term", "Transport Mode",
    "Shipper", "Consignee", "Origin Country", "Destination Country", "Origin",
    "Destination", "Delivery", "Port of Loading", "Transshipment Port",
    "Port of Discharge", "Act Port Load", "Act Port Disch", "Cargo Ready",
    "Act Depart", "Act Arriv", "Act Deliv", "CT Conts ST", "20", "40", "40HQ",
    "45", "CT CBM", "CT CWT", "CT GWT kg", "CT Plts", "Sales Invoice #",
    "Date Issued", "Issued by", "Bill To Party Company", "Status", "Currency",
    "Billed Sales Amount", "USD Sales Amount", "Sales Invoice #", "SI CC",
    "SI CC Description", "USD SI CC",
]

# Column indices used when reading the finished rows back to build the manifest.
# Counted off the file rather than the world model on purpose: a group with fewer
# charges than shipments leaves one unbilled, and unbilled cargo never reaches the
# file -- so counting the world would claim volume the engine has no way to see.
COL_CT, COL_MB = 0, 2
COL_CBM, COL_PLTS = 27, 30
COL_INVOICE, COL_USD_SALES = 31, 38
COL_CODE, COL_USD = 40, 42
COL_EQUIP_40HQ = 25

OUT_OF_SCOPE_MODES = [
    ("AIR", 0.55), ("Trucking-Domestic", 0.20), ("Trucking-Cross Border", 0.10),
    ("OCEAN - FCL (AW)", 0.15),   # in-scope mode but an out-of-scope term
]
OUT_OF_SCOPE_TERMS = [("DAP", 0.40), ("DDP", 0.34), ("CIF", 0.14), ("BRK", 0.12)]

RATE_CARD_FIELDS = ["Rate_ID", "Category", "Item", "Rate", "Currency", "Rate_Basis",
                    "Node_From", "Node_To", "Ch_Code", "Min_Charge", "Effective_From",
                    "Source"]


# --------------------------------------------------------------------------------------
# Small deterministic helpers
# --------------------------------------------------------------------------------------
def pick_weighted(rng, options):
    """Choose from [(value, weight), ...]. Sorted input keeps this reproducible."""
    total = sum(w for _, w in options)
    r = rng.random() * total
    upto = 0.0
    for value, weight in options:
        upto += weight
        if r <= upto:
            return value
    return options[-1][0]


def jitter(rng, value, pct):
    """A contract rate and an invoice rarely agree exactly. This is that gap.

    It is why the derived-rate audit can show an observed min/median/max spread
    around a single derived figure instead of one repeated number.
    """
    return round(value * (1.0 + rng.uniform(-pct, pct)), 2)


def fmt_date(d, iso):
    return d.isoformat() if iso else d.strftime("%d-%b-%Y")


def money(v):
    return f"{v:.2f}"


def weighted_in_sorted_order(weights):
    """[(name, weight), ...] in sorted-name order.

    Sorted rather than insertion order because the draw has to be stable against
    someone reordering a dict literal, which is the kind of edit that looks cosmetic
    and silently regenerates a rehearsed dataset.
    """
    return [(name, weights[name]) for name in sorted(weights)]


def slug(text, n=8):
    return "".join(ch for ch in text.split(",")[0] if ch.isalnum()).upper()[:n]


# --------------------------------------------------------------------------------------
# Cargo
# --------------------------------------------------------------------------------------
# The box every booking is measured against: a 40' high cube.
BOX_CBM = 64.5
BOX_PALLETS = 48.0


def draw_cargo(rng, w, in_scope):
    """Pallet count, CBM and gross weight for one shipment group.

    Consignment size is a property of the client, not of freight, and it is the single
    biggest determinant of whether consolidating is worth anything. An importer buying in
    small lots from many suppliers ships part-full boxes and has a great deal to recover;
    one buying in forty-pallet lots is already filling containers and has nothing to
    give. So it comes off the world rather than being a constant here.
    """
    if in_scope and w.BOOKING.get("lot_fill"):
        # A client who buys by the container. Orders are raised to fill a box rather than
        # to meet a demand forecast, so the consignment *is* one or two containers and
        # arrives already close to full. There is nothing here for a warehouse to recover,
        # which is a real answer and one the engine has to be able to reach.
        boxes = 2 if rng.random() < w.BOOKING.get("two_box_share", 0.2) else 1
        fill = rng.uniform(*w.BOOKING["lot_fill"])
        cbm = round(boxes * BOX_CBM * fill, 3)
        cbm_per_pallet = rng.uniform(*w.BOOKING["cbm_per_pallet"])
        pallets = min(int(round(cbm / cbm_per_pallet)), int(BOX_PALLETS * boxes * 0.96))
        gwt = round(pallets * rng.uniform(215.0, 520.0), 2)
        return pallets, cbm, gwt
    if in_scope:
        mu, sigma = w.BOOKING["pallets"]
        pallets = int(round(rng.lognormvariate(mu, sigma)))
        pallets = max(4, min(pallets, w.BOOKING["pallets_max"]))
    else:
        pallets = max(1, int(round(rng.lognormvariate(1.9, 0.85))))
        pallets = min(pallets, 40)

    lo, hi = w.BOOKING["cbm_per_pallet"]
    cbm_per_pallet = rng.uniform(lo, hi)
    kg_per_pallet = rng.uniform(215.0, 520.0)
    cbm = round(pallets * cbm_per_pallet, 3)
    gwt = round(pallets * kg_per_pallet, 2)
    return pallets, cbm, gwt


def container_count(rng, w, cbm, pallets):
    """How many 40'HC the group actually books today.

    Not how many it *could* fit into. Bookings are made one shipment at a time against a
    standard box, without a plan for what else is sailing, so a real container leaves
    short of its limits -- part loads, awkward stacks, cargo held back for a later
    vessel. ``efficiency`` is that gap, and the space it wastes is precisely what
    consolidation later recovers.

    It is a world-level figure because booking discipline differs by client. A shipper
    whose planner already fills boxes to 95% has done most of this work themselves, and a
    demo that assumed everybody books at 70% would find a saving that is not there.
    """
    lo, hi = w.BOOKING["efficiency"]
    efficiency = rng.uniform(lo, hi)
    return max(1, math.ceil(max(cbm / (BOX_CBM * efficiency),
                                pallets / (BOX_PALLETS * efficiency))))


# --------------------------------------------------------------------------------------
# Shipment groups
# --------------------------------------------------------------------------------------
def build_groups(rng, w):
    sites_by_pod = {}
    for s in w.DELIVERY_SITES:
        sites_by_pod.setdefault(s["pod"], []).append(s)

    suppliers_by_cfs = {}
    for s in w.SUPPLIERS:
        suppliers_by_cfs.setdefault(s["cfs"], []).append(s)

    origin_options = weighted_in_sorted_order(w.ORIGIN_WEIGHTS)
    pod_options = weighted_in_sorted_order(w.POD_WEIGHTS)
    currency_options = list(w.CURRENCY_WEIGHTS.items())

    groups = []
    ct_seq = 720000
    mb_seq = 41000
    inv_seq = 100200

    for i in range(w.N_GROUPS):
        in_scope = rng.random() < IN_SCOPE_SHARE

        origin = pick_weighted(rng, origin_options)
        cfs = w.ORIGINS[origin]["cfs"]
        supplier = rng.choice(sorted(suppliers_by_cfs[cfs], key=lambda s: s["name"]))

        pod = pick_weighted(rng, pod_options)
        # Volume is concentrated, not spread evenly -- see SITE_WEIGHTS on the world.
        ranked = sorted(sites_by_pod[pod], key=lambda s: s["site_id"])
        weights = w.SITE_WEIGHTS[:len(ranked)]
        site = pick_weighted(rng, list(zip(ranked, weights)))
        raw_delivery, _ = rng.choice(site["raw"])

        if in_scope:
            term = pick_weighted(rng, [("EXW", 0.56), ("FOB", 0.44)])
            lcl = w.BOOKING.get("lcl_share", 0.14)
            mode = pick_weighted(rng, [("OCEAN - FCL (AW)", 1.0 - lcl),
                                       ("OCEAN - LCL", lcl)])
        else:
            term = pick_weighted(rng, OUT_OF_SCOPE_TERMS)
            mode = pick_weighted(rng, OUT_OF_SCOPE_MODES)

        pallets, cbm, gwt = draw_cargo(rng, w, in_scope)
        conts = (container_count(rng, w, cbm, pallets)
                 if mode == "OCEAN - FCL (AW)" else 0)

        # Dates. Cargo ready anywhere in the window; the vessel leaves a few days
        # later; transit is the lane's nominal time with real-world spread; the
        # last mile is a few more days.
        span = (HISTORY_END - HISTORY_START).days
        ready = HISTORY_START + timedelta(days=rng.randint(0, span))
        if in_scope and term == "EXW":
            # Snapped forward to the region's ex-works day. See W.exw_ready_weekday.
            wanted = W.exw_ready_weekday(supplier["region"])
            ready += timedelta(days=(wanted - ready.weekday()) % 7)
        # Days from cargo ready to the vessel leaving. Kept realistic and fairly
        # tight: cargo is normally booked onto the next scheduled sailing. A wide
        # spread here would hand the consolidation model a pile of booking slack to
        # "cure", and it would report a lead-time improvement that is really just an
        # artefact of loose bookings in the history.
        depart = ready + timedelta(days=rng.randint(3, 9))
        if mode.startswith("OCEAN"):
            transit = w.PORTS[pod]["transit"][cfs] + rng.randint(-4, 11)
        elif mode == "AIR":
            transit = rng.randint(2, 6)
        else:
            transit = rng.randint(2, 9)
        arrive = depart + timedelta(days=max(1, transit))
        deliver = arrive + timedelta(days=rng.randint(1, 12))

        # Most groups are a single shipment. Where a group holds several, they
        # share one master bill unless the group is large enough to have been
        # booked twice.
        # Cargo is split across the shipments in a group, so a group can never hold
        # more shipments than it has pallets to give them.
        n_cts = min(pick_weighted(rng, [(1, 0.72), (2, 0.20), (3, 0.08)]), pallets)
        # A booking is a master bill, and a bill has to be stated against a
        # shipment to appear in the file at all, so a group can never carry more
        # bills than it has shipments.
        n_master_bills = 2 if (conts >= 2 and n_cts >= 2 and rng.random() < 0.30) else 1

        cts = []
        for k in range(n_cts):
            ct_seq += 1
            cts.append(ct_seq)
        master_bills = []
        for k in range(n_master_bills):
            mb_seq += 1
            master_bills.append(mb_seq)

        # GRP # mirrors the source system: a lone shipment reuses its own CT
        # number with a CT prefix, a genuine group gets its own short number.
        grp = f"CT{cts[0]}" if n_cts == 1 else str(10000 + i)

        inv_seq += 1
        currency = pick_weighted(rng, currency_options)

        groups.append({
            "grp": grp, "cts": cts, "master_bills": master_bills,
            "in_scope": in_scope, "term": term, "mode": mode,
            "origin": origin, "cfs": cfs, "supplier": supplier,
            "pod": pod, "site": site, "raw_delivery": raw_delivery,
            "pallets": pallets, "cbm": cbm, "gwt": gwt, "conts": conts,
            "ready": ready, "depart": depart, "arrive": arrive, "deliver": deliver,
            "invoice": f"{w.INVOICE_PREFIX}{inv_seq}", "currency": currency,
            "iso_dates": rng.random() < 0.15,
            # Note there is no "sometimes the booking is missing entirely" case.
            # A real export states the equipment block on the opening rows of an
            # invoice and drops it thereafter, so most rows are blank but every
            # booking is recorded somewhere. That is what makes the rebuild the
            # right answer rather than a guess: the information is present, just
            # not on the rows a naive read would total up.
            "clerk": rng.choice(w.INVOICE_CLERKS),
        })
    return groups


# --------------------------------------------------------------------------------------
# Charges
# --------------------------------------------------------------------------------------
def apply_bundles(charges, billing):
    """Collapse itemised charges onto their bundled code, where the world bills that way.

    The amounts are summed, never re-drawn: a bundled world charges its client exactly
    what the itemised equivalent charges. Only attributability is lost, which is the
    entire point -- the reconciliation still balances to the cent while the derivation
    engine has nothing to work with.

    Consumes no randomness, so a world that bundles nothing is byte-identical to one
    generated before this function existed.
    """
    bundle_for = {}
    if billing["origin"] == "bundled":
        bundle_for["1630"] = W.BUNDLES["1630"]
    if billing["destination"] == "bundled":
        bundle_for["1300"] = W.BUNDLES["1300"]
    if not bundle_for:
        return charges

    absorbed = {code for codes in bundle_for.values() for code in codes}
    out, totals, anchor = [], {}, {}
    for code, usd in charges:
        if code not in absorbed:
            out.append((code, usd))
            continue
        bundle = next(b for b, codes in bundle_for.items() if code in codes)
        totals[bundle] = round(totals.get(bundle, 0.0) + usd, 2)
        # The bundle takes the position of the first line it swallows, so the file
        # still reads in physical order rather than putting origin charges last.
        anchor.setdefault(bundle, len(out))
        out.append(None)

    for bundle, total in sorted(totals.items()):
        out[anchor[bundle]] = (bundle, total)
    return [c for c in out if c is not None]


def build_charges(rng, w, g):
    """The charge lines for one shipment group, as (code, usd) pairs.

    Amounts come from the world's true rates with a little spread, so a rate the
    engine later derives from these invoices lands near -- but not exactly on --
    the contract figure. Term drives what exists at all: FOB cargo reaches the
    port at the supplier's cost, so none of the itemised origin components appear
    on it. That asymmetry is real and the cost model depends on it.

    Bundling is applied last, once every amount has been drawn, so the randomness a
    world consumes does not depend on how its forwarder chose to invoice.
    """
    charges = []
    conts = max(1, g["conts"])
    mode, term = g["mode"], g["term"]
    rates = w.TRUE_RATES

    # --- freight -------------------------------------------------------------
    if mode == "OCEAN - FCL (AW)":
        base = rates["ocean"][(g["cfs"], g["pod"])]["rate"]
        charges.append(("1301", jitter(rng, base * conts, 0.07)))
    elif mode == "OCEAN - LCL":
        charges.append(("1302", jitter(rng, max(180.0, g["cbm"] * 68.0), 0.10)))
    elif mode == "AIR":
        chargeable = max(g["gwt"], g["cbm"] * 167.0)
        charges.append(("1101", jitter(rng, chargeable * 3.35, 0.12)))
    else:
        charges.append(("1401", jitter(rng, 780.0 + g["cbm"] * 24.0, 0.10)))

    # --- origin, itemised where the client bought on EXW terms ---------------
    if term == "EXW":
        components = rates["exw"][g["supplier"]["region"]]["components"]
        for code in sorted(components):
            charges.append((code, jitter(rng, components[code] * conts, 0.05)))
    if rng.random() < 0.80:
        charges.append(("1601", jitter(rng, rates["misc"]["1601"]["rate"] * conts, 0.08)))
    # Origin drayage, where the world's forwarder bills it separately. The share is
    # zero for the two bundled worlds, so no 1602 line ever reaches their files and
    # the warehouse-to-port leg has no analogue to reach for.
    #
    # The short-circuit on ``term`` is load-bearing: it is what the published Northgate
    # dataset was generated with, and moving the draw ahead of it consumes randomness
    # on every FOB group and regenerates the whole file.
    if term == "EXW" and rng.random() < w.BILLING["origin_drayage_share"]:
        charges.append(("1602", jitter(rng, rates["misc"]["1602"]["rate"] * conts, 0.09)))

    # --- destination ---------------------------------------------------------
    # Code 1638 is the charge the engine derives a per-container delivery rate
    # from. Only ocean FCL carries it; the rest of the file bills the last mile
    # under trucking codes, which must never enter that rate.
    if mode == "OCEAN - FCL (AW)":
        dest = rates["dest"][(g["pod"], g["site"]["site"])]["rate"]
        charges.append(("1638", jitter(rng, dest * conts, 0.06)))
        if rng.random() < 0.44:
            charges.append(("1505", jitter(rng, rates["misc"]["1505"]["rate"] * conts, 0.10)))
        if rng.random() < 0.30:
            charges.append(("1511", jitter(rng, rates["misc"]["1511"]["rate"] * conts, 0.10)))
    else:
        charges.append(("1503", jitter(rng, 420.0 + g["cbm"] * 31.0, 0.11)))
        # A handful of invoices bill the last mile under a lookalike description
        # on a different code. It reads like the delivery charge and is not one.
        if rng.random() < 0.12:
            charges.append(("1411", jitter(rng, 260.0 + g["cbm"] * 9.0, 0.12)))

    # --- documentation -------------------------------------------------------
    if rng.random() < 0.58:
        charges.append(("1620", jitter(rng, rates["misc"]["1620"]["rate"], 0.06)))
    if rng.random() < 0.26:
        charges.append(("1600", jitter(rng, rates["misc"]["1600"]["rate"], 0.15)))

    # --- the long tail -------------------------------------------------------
    # A small share of invoices carry a one-off charge. They are unusual, but every
    # generated code has a documented pool: a demo result must not rely on the engine
    # guessing where its own deliberately-created costs belong.
    if rng.random() < 0.14:
        code = rng.choice(sorted(W.RARE_CHARGE_CODES))
        charges.append((code, jitter(rng, rng.uniform(65.0, 940.0), 0.20)))

    return apply_bundles(charges, w.BILLING)


# --------------------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------------------
def build_rows(rng, w, groups):
    rows = []
    for g in sorted(groups, key=lambda x: x["cts"][0]):
        iso = g["iso_dates"]
        site = g["site"]
        fx = W.FX_TO_USD[g["currency"]]

        # Charges belong to the group; they are apportioned across its shipments
        # so that every shipment carries at least one line.
        charges = build_charges(rng, w, g)
        n_cts = len(g["cts"])
        per_ct = [[] for _ in range(n_cts)]
        for idx, c in enumerate(charges):
            per_ct[idx % n_cts].append(c)

        # Cargo is stated per shipment, and the group is the sum of its shipments.
        # Writing the group total against each shipment would multiply volume by
        # the number of shipments the moment anything aggregated it.
        ct_pallets = [g["pallets"] // n_cts] * n_cts
        for k in range(g["pallets"] - sum(ct_pallets)):
            ct_pallets[k] += 1
        ct_cbm = [round(g["cbm"] * p / g["pallets"], 3) for p in ct_pallets]
        ct_gwt = [round(g["gwt"] * p / g["pallets"], 2) for p in ct_pallets]
        # Rounding the shares must not lose or invent volume.
        ct_cbm[0] = round(ct_cbm[0] + g["cbm"] - sum(ct_cbm), 3)
        ct_gwt[0] = round(ct_gwt[0] + g["gwt"] - sum(ct_gwt), 2)

        # Equipment is stated against master bills, not shipments -- which is why
        # counting rows inflates containers and why the rebuild takes the maximum
        # per master bill and sums those.
        mb_conts = [0] * len(g["master_bills"])
        for k in range(g["conts"]):
            mb_conts[k % len(g["master_bills"])] += 1

        for ci, ct in enumerate(g["cts"]):
            mb_index = ci % len(g["master_bills"])
            master_bill = g["master_bills"][mb_index]
            ct_charges = per_ct[ci]
            if not ct_charges:
                continue

            invoice_usd = round(sum(v for _, v in ct_charges), 2)
            billed = round(invoice_usd / fx, 2)

            # Origin Country is unreliable in real exports -- a Hong Kong or
            # regional-office country against a mainland port. Origin itself is
            # always right, which is why the engine keys off it.
            origin_country = w.ORIGINS[g["origin"]]["country"]
            if rng.random() < 0.05:
                origin_country = rng.choice(["Hong Kong", "Taiwan", ""])

            transship = ""
            hub = w.TRANSSHIP.get(g["cfs"])
            if hub and rng.random() < hub["share"]:
                transship = rng.choice(hub["ports"])

            pallets_ct, cbm_ct, gwt_ct = ct_pallets[ci], ct_cbm[ci], ct_gwt[ci]
            cwt = gwt_ct if g["mode"] != "AIR" else round(max(gwt_ct, cbm_ct * 167.0), 2)

            for li, (code, usd) in enumerate(ct_charges):
                first = li == 0

                # --- mess 1: the sentinel -------------------------------------
                # The invoice total is stated once. Every later line of the same
                # invoice says "-related-" instead of repeating it.
                usd_sales = money(invoice_usd) if first else "-related-"

                # --- mess 2: blank equipment ---------------------------------
                # The export carries the shipment-level block on the opening rows
                # of an invoice and drops it thereafter, and some shipments never
                # carry it at all. Counting rows would multiply containers by the
                # number of charges; the rebuild takes the maximum per master bill
                # and sums those, which is why repeating the figure here is safe.
                heading = li < 2
                if heading and g["mode"] == "OCEAN - FCL (AW)":
                    eq = ["0", "0", str(mb_conts[mb_index]), "0"]
                elif heading and g["mode"] == "OCEAN - LCL":
                    eq = ["0", "0", "0", "0"]
                else:
                    eq = ["", "", "", ""]

                # --- mess 3: one code, several descriptions -------------------
                description = rng.choice(W.ALL_CHARGE_CODES[code]["spellings"])

                rows.append([
                    str(ct), g["grp"], str(master_bill), w.CLIENT_COMPANY,
                    g["term"], g["mode"], g["supplier"]["name"],
                    w.CONSIGNEE_BY_COUNTRY[site["country"]],
                    origin_country, w.PORTS[g["pod"]]["country"],
                    g["origin"], g["pod"], g["raw_delivery"],
                    g["origin"], transship, g["pod"],
                    fmt_date(g["depart"], iso), fmt_date(g["arrive"], iso),
                    fmt_date(g["ready"], iso), fmt_date(g["depart"], iso),
                    fmt_date(g["arrive"], iso), fmt_date(g["deliver"], iso),
                    "", eq[0], eq[1], eq[2], eq[3],
                    f"{cbm_ct:.3f}" if first else "",
                    money(cwt) if first else "",
                    money(gwt_ct) if first else "",
                    str(pallets_ct) if first else "",
                    g["invoice"], fmt_date(g["deliver"] + timedelta(days=rng.randint(2, 21)), iso),
                    g["clerk"], w.BILL_TO_PARTY, "open", g["currency"],
                    money(billed), usd_sales,
                    g["invoice"], code, description, money(usd),
                ])
    return rows


# --------------------------------------------------------------------------------------
# Reference files
#
# Grouped the way a forwarder actually quotes, not the way the engine finds convenient:
#
#   door_charges     the road legs at each end -- EXW collection from the supplier and
#                    DAP delivery from the discharge port. Whether these are itemised at
#                    all is the client's billing habit, which is exactly what varies
#                    between the three worlds.
#   port_and_ocean   the port-to-port tariff and everything charged at a quay: ocean
#                    freight per lane, origin THC, VGM, seal, export declaration and
#                    documentation, and the destination terminal and port charges.
#   consolidation    the quote for the warehouse work. Not a rate card at all -- it
#                    prices work never bought, and is tagged QUOTED_NOT_YET_BOUGHT.
#   ftl              the optional tender for the warehouse-to-quay run.
#
# ``reference_pack.csv`` is the first three concatenated, which is the demo path: one
# upload and the board resolves. The split files exist so the same board can be shown
# half-answered, which is the more honest picture of a first engagement.
# --------------------------------------------------------------------------------------
def door_charge_rows(w):
    """The two road legs at the ends of the journey.

    Collection from the supplier into the warehouse at origin, and the run from the
    discharge port to the delivery site at destination. They are one document because
    they are one kind of charge -- a truck, priced per container, at a door -- and
    because whether a client itemises them at all is a single billing habit rather than
    two.

    The origin drayage code lands here for the same reason: it is a road move. It is
    still only ever an *analogue* for the warehouse-to-port leg, because it prices the
    supplier-to-port run. Arriving on a rate card does not change which journey it paid
    for.
    """
    rows = []
    for region, spec in sorted(w.TRUE_RATES["exw"].items()):
        if not spec["carded"] or "1631" not in spec["components"]:
            continue
        rows.append({
            "Rate_ID": f"ORIG-{region}-1631",
            "Category": "ORIGIN_COMPONENT",
            "Item": f"{W.CHARGE_CODES['1631']['spellings'][0]} ({region})",
            "Rate": f"{spec['components']['1631']:.2f}", "Currency": "USD",
            "Rate_Basis": "Per Container", "Node_From": region,
            "Node_To": f"{region} port", "Ch_Code": "1631", "Min_Charge": "",
            "Effective_From": "2025-01-01", "Source": "CLIENT_RATE_CARD",
        })
    spec = w.TRUE_RATES["misc"].get("1602")
    if spec and spec["carded"]:
        rows.append({
            "Rate_ID": "ORIG-MISC-1602", "Category": "ORIGIN_COMPONENT",
            "Item": W.CHARGE_CODES["1602"]["spellings"][0],
            "Rate": f"{spec['rate']:.2f}", "Currency": "USD",
            "Rate_Basis": "Per Container", "Node_From": "", "Node_To": "",
            "Ch_Code": "1602", "Min_Charge": "", "Effective_From": "2025-01-01",
            "Source": "CLIENT_RATE_CARD",
        })
    for (pod, site), spec in sorted(w.TRUE_RATES["dest"].items()):
        if not spec["carded"]:
            continue
        rows.append({
            "Rate_ID": f"DEST-{pod[:3].upper()}-{slug(site)}",
            "Category": "DEST_DELIVERY", "Item": f"Port {pod} to warehouse {site}",
            "Rate": f"{spec['rate']:.2f}", "Currency": "USD",
            "Rate_Basis": "Per Container", "Node_From": pod, "Node_To": site,
            "Ch_Code": "1638", "Min_Charge": "", "Effective_From": "2025-01-01",
            "Source": "CLIENT_RATE_CARD",
        })
    return rows


def port_and_ocean_rows(w):
    """The port-to-port tariff, and everything charged at a quay.

    Ocean freight per lane, and the terminal charges at both ends that travel with it --
    origin THC, VGM, seal, export declaration, documentation, and the destination
    terminal and port charges. One document, because a client who has a freight tariff
    almost always has these on the same piece of paper.

    Freight is *usually* derivable from the invoices without any of this: it is normally
    one charge code against one lane. Usually is not always -- a forwarder who bills
    ocean and delivery together on one line leaves neither derivable, and then this card
    is the only thing that prices the leg.
    """
    rows = []
    for (cfs, pod), spec in sorted(w.TRUE_RATES["ocean"].items()):
        if not spec["carded"]:
            continue
        rows.append({
            "Rate_ID": f"OCEAN-{slug(cfs, 6)}-{pod[:3].upper()}",
            "Category": "OCEAN", "Item": f"Ocean freight {cfs} to {pod}",
            "Rate": f"{spec['rate']:.2f}", "Currency": "USD",
            "Rate_Basis": "Per Container", "Node_From": cfs, "Node_To": pod,
            "Ch_Code": "1301", "Min_Charge": "", "Effective_From": "2025-01-01",
            "Source": "CLIENT_RATE_CARD",
        })
    for region, spec in sorted(w.TRUE_RATES["exw"].items()):
        if not spec["carded"]:
            continue
        for code in sorted(c for c in spec["components"] if c != "1631"):
            rows.append({
                "Rate_ID": f"ORIG-{region}-{code}",
                "Category": "ORIGIN_COMPONENT",
                "Item": f"{W.CHARGE_CODES[code]['spellings'][0]} ({region})",
                "Rate": f"{spec['components'][code]:.2f}", "Currency": "USD",
                "Rate_Basis": "Per Container", "Node_From": region,
                "Node_To": f"{region} port", "Ch_Code": code, "Min_Charge": "",
                "Effective_From": "2025-01-01", "Source": "CLIENT_RATE_CARD",
            })
    # Terminal and port charges at destination are their own category, because the
    # component that needs them is not the delivery component. Filing them under
    # "other" would leave the destination-terminal card looking for a rate that is
    # sitting in the file under a heading it does not read.
    for code in ("1505", "1511", "1411"):
        spec = w.TRUE_RATES["misc"].get(code)
        if not spec or not spec["carded"]:
            continue
        rows.append({
            "Rate_ID": f"DTERM-{code}", "Category": "DEST_TERMINAL",
            "Item": W.CHARGE_CODES[code]["spellings"][0],
            "Rate": f"{spec['rate']:.2f}", "Currency": "USD",
            "Rate_Basis": "Per Container", "Node_From": "", "Node_To": "",
            "Ch_Code": code, "Min_Charge": "", "Effective_From": "2025-01-01",
            "Source": "CLIENT_RATE_CARD",
        })
    for code in ("1601", "1620", "1600"):
        spec = w.TRUE_RATES["misc"].get(code)
        if not spec or not spec["carded"]:
            continue
        rows.append({
            "Rate_ID": f"ORIG-MISC-{code}", "Category": "OTHER",
            "Item": W.CHARGE_CODES[code]["spellings"][0],
            "Rate": f"{spec['rate']:.2f}", "Currency": "USD",
            "Rate_Basis": "Per Container", "Node_From": "", "Node_To": "",
            "Ch_Code": code, "Min_Charge": "", "Effective_From": "2025-01-01",
            "Source": "CLIENT_RATE_CARD",
        })
    return rows


def consolidation_quote_rows(w):
    """The forwarder's quote for the consolidation service.

    Priced but not yet bought, so it is tagged QUOTED_NOT_YET_BOUGHT rather than
    CLIENT_RATE_CARD. That distinction is the whole reason the demo can claim every
    modelled dollar is evidenced without claiming any of it is invoiced.
    """
    rows = []
    for key, spec in sorted(w.SERVICE_QUOTE.items()):
        rows.append({
            "Rate_ID": f"CONSOL-{key}", "Category": "CONSOLIDATION",
            "Item": spec["item"], "Rate": f"{spec['rate']:.2f}", "Currency": "USD",
            "Rate_Basis": spec["basis"], "Node_From": "", "Node_To": "",
            "Ch_Code": key, "Min_Charge": "", "Effective_From": "2025-01-01",
            "Source": "QUOTED_NOT_YET_BOUGHT",
        })
    return rows


def ftl_card_rows(w):
    """The trailer tender -- the file the engine asks for and does not start with.

    One row per pickup region, because a trailer rate is a distance and a region is how
    hauliers price distance. A partial tender is therefore a real possibility and the
    engine has to notice one: covering three regions of five prices three regions of
    five, and comparing that against the whole inbound bill would credit it with the two
    it does not touch.
    """
    rows = []
    for key, spec in sorted(w.FTL_QUOTE.items()):
        for region, rate in sorted(spec["rates"].items()):
            rows.append({
                "Rate_ID": f"FTL-{key}-{region}", "Category": "FTL",
                "Item": f"{spec['item']} ({region})", "Rate": f"{rate:.2f}",
                "Currency": "USD", "Rate_Basis": spec["basis"], "Node_From": region,
                "Node_To": "consolidation warehouse", "Ch_Code": key, "Min_Charge": "",
                "Effective_From": "2025-01-01", "Source": "QUOTED_NOT_YET_BOUGHT",
            })
    return rows


def write_card(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=RATE_CARD_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


# --------------------------------------------------------------------------------------
# Ground truth
# --------------------------------------------------------------------------------------
def build_manifest(w, groups, rows, counts):
    in_scope = [g for g in groups if g["in_scope"]]
    fcl = [g for g in in_scope if g["mode"] == "OCEAN - FCL (AW)"]
    sentinel = sum(1 for r in rows if r[COL_USD_SALES] == "-related-")
    blank_equipment = sum(1 for r in rows if r[COL_EQUIP_40HQ] == "")
    invoiced_usd = round(sum(float(r[COL_USD]) for r in rows), 2)
    in_scope_cts = {ct for g in in_scope for ct in g["cts"]}
    in_scope_usd = round(
        sum(float(r[COL_USD]) for r in rows if int(r[COL_CT]) in in_scope_cts), 2)

    in_scope_blocks = [r for r in rows
                       if r[COL_PLTS] != "" and int(r[COL_CT]) in in_scope_cts]
    in_scope_pallets = sum(int(r[COL_PLTS]) for r in in_scope_blocks)
    in_scope_cbm = round(sum(float(r[COL_CBM]) for r in in_scope_blocks), 1)

    # Codes the engine cannot place in a cost pool. This must be empty for every seeded
    # demo; it remains in the manifest so generation itself proves that invariant.
    codes_present = {r[COL_CODE] for r in rows}
    unmapped_codes = sorted(
        c for c in codes_present
        if W.ALL_CHARGE_CODES.get(c, {}).get("pool") is None)
    unmapped_rows = [r for r in rows if r[COL_CODE] in unmapped_codes]

    # Which of the bundled codes actually reached the file, and what each is hiding.
    # The board reads this to explain an unpriceable leg in the client's own terms
    # rather than reporting a bare absence.
    bundles_present = {
        code: {
            "rows": sum(1 for r in rows if r[COL_CODE] == code),
            "usd": round(sum(float(r[COL_USD]) for r in rows if r[COL_CODE] == code), 2),
            "covers": W.BUNDLES[code],
        }
        for code in sorted(W.BUNDLES) if code in codes_present
    }

    return {
        "scenario": w.SCENARIO_ID,
        "seed": w.SEED,
        "generated_by": "generator/make_demo_data.py",
        "client": w.CLIENT_COMPANY,
        "summary": w.SUMMARY,
        "billing": dict(w.BILLING),
        "history_window": [HISTORY_START.isoformat(), HISTORY_END.isoformat()],
        "charge_lines": len(rows),
        # Shipments that actually reach the file. A group with fewer charges than
        # shipments leaves one unbilled, and an unbilled shipment has no rows.
        "shipments": len({r[COL_CT] for r in rows}),
        "shipment_groups": len(groups),
        "invoices": len({r[COL_INVOICE] for r in rows}),
        "master_bills": len({r[COL_MB] for r in rows}),
        "total_invoiced_usd": invoiced_usd,
        "mess": {
            "related_sentinel_rows": sentinel,
            "related_sentinel_share": round(sentinel / len(rows), 4),
            "blank_equipment_rows": blank_equipment,
            "blank_equipment_share": round(blank_equipment / len(rows), 4),
            "code_1638_spellings": len(W.CHARGE_CODES["1638"]["spellings"]),
            "distinct_charge_codes": len(codes_present),
            "unrecognised_codes": unmapped_codes,
            "unrecognised_code_rows": len(unmapped_rows),
            "unrecognised_code_usd": round(
                sum(float(r[COL_USD]) for r in unmapped_rows), 2),
        },
        "bundling": {
            "origin": w.BILLING["origin"],
            "destination": w.BILLING["destination"],
            "codes": bundles_present,
        },
        "in_scope": {
            "definition": "ocean freight on EXW or FOB terms with a mapped origin",
            "shipment_groups": len(in_scope),
            "fcl_groups": len(fcl),
            "containers_today": sum(g["conts"] for g in fcl),
            "pallets": in_scope_pallets,
            "cbm": in_scope_cbm,
            "invoiced_usd": in_scope_usd,
        },
        "reference_files": dict(counts, sites_in_world=len(w.DELIVERY_SITES)),
        "rate_coverage": {
            "ocean_lanes": len(w.TRUE_RATES["ocean"]),
            "ocean_carded": sum(1 for v in w.TRUE_RATES["ocean"].values() if v["carded"]),
            "dest_lanes": len(w.TRUE_RATES["dest"]),
            "dest_carded": sum(1 for v in w.TRUE_RATES["dest"].values() if v["carded"]),
            "origin_regions": len(w.TRUE_RATES["exw"]),
            "origin_carded": sum(1 for v in w.TRUE_RATES["exw"].values() if v["carded"]),
        },
    }


# --------------------------------------------------------------------------------------
def generate(w):
    """Write one scenario's whole directory, and return its registry entry."""
    out = DATA / w.SCENARIO_ID
    out.mkdir(parents=True, exist_ok=True)

    rng = random.Random(w.SEED)
    groups = build_groups(rng, w)
    rows = build_rows(rng, w, groups)

    with open(out / "charge_lines_raw.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CHARGE_LINE_COLUMNS)
        writer.writerows(rows)

    door = door_charge_rows(w)
    port = port_and_ocean_rows(w)
    consol = consolidation_quote_rows(w)
    ftl = ftl_card_rows(w)

    counts = {
        "door_charges_rows": write_card(out / "door_charges.csv", door),
        "port_and_ocean_rows": write_card(out / "port_and_ocean.csv", port),
        "consolidation_quote_rows": write_card(out / "consolidation_quote.csv", consol),
        # The pack is the three of them, and deliberately NOT the FTL card. One upload
        # should answer everything the client already knows the price of; the FTL rate
        # is the thing they have to go and get, so it stays a separate act.
        "reference_pack_rows": write_card(out / "reference_pack.csv",
                                          door + port + consol),
    }
    if ftl:
        counts["ftl_rate_card_rows"] = write_card(out / "ftl_rate_card.csv", ftl)

    manifest = build_manifest(w, groups, rows, counts)
    with open(out / "ground_truth_manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"\n{w.CLIENT_COMPANY}")
    print(f"  charge lines      {manifest['charge_lines']:>8,}")
    print(f"  shipments         {manifest['shipments']:>8,}")
    print(f"  shipment groups   {manifest['shipment_groups']:>8,}")
    print(f"  invoiced USD      {manifest['total_invoiced_usd']:>8,.2f}")
    print(f"  -related- share   {manifest['mess']['related_sentinel_share']:>8.1%}")
    print(f"  blank equipment   {manifest['mess']['blank_equipment_share']:>8.1%}")
    print(f"  distinct codes    {manifest['mess']['distinct_charge_codes']:>8,}")
    print(f"  in-scope groups   {manifest['in_scope']['shipment_groups']:>8,}")
    print(f"  containers today  {manifest['in_scope']['containers_today']:>8,}")
    print(f"  in-scope CBM      {manifest['in_scope']['cbm']:>8,.1f}")
    print(f"  reference pack    {counts['reference_pack_rows']:>8,} rows")
    if manifest["bundling"]["codes"]:
        for code, info in manifest["bundling"]["codes"].items():
            print(f"  bundle {code}       {info['rows']:>8,} rows, "
                  f"${info['usd']:,.0f}, hides {len(info['covers'])} codes")

    return SC.registry_entry(
        w,
        charge_lines=manifest["charge_lines"],
        shipments=manifest["shipments"],
        containers_today=manifest["in_scope"]["containers_today"],
        invoiced_usd=manifest["total_invoiced_usd"],
        distinct_charge_codes=manifest["mess"]["distinct_charge_codes"],
        bundled_codes=sorted(manifest["bundling"]["codes"]),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenario", choices=sorted(SC.BY_ID),
                    help="generate one scenario instead of all of them")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    worlds = [SC.get(args.scenario)] if args.scenario else SC.WORLDS
    entries = [generate(w) for w in worlds]

    # The registry is only rewritten on a full run. A partial run leaving a registry
    # that names one scenario would silently hide the other two from the app.
    if args.scenario:
        print(f"\nregistry not rewritten (single scenario); "
              f"run without --scenario to refresh data/scenarios.json")
        return

    registry = {"default": SC.DEFAULT_ID, "scenarios": entries}
    with open(DATA / "scenarios.json", "w", encoding="utf-8") as fh:
        json.dump(registry, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"\nwrote data/scenarios.json  ({len(entries)} scenarios, "
          f"default {SC.DEFAULT_ID})")


if __name__ == "__main__":
    main()
