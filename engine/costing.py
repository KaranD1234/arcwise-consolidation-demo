"""Cost the plan, and cost today, so the two can be compared honestly.

Every dollar in the modelled total is one ledger row tagged to a container, a
physical leg, a rate and that rate's provenance. Nothing is allocated by a
percentage or a spread; if a charge cannot be traced to a leg it does not exist.

Two rules here do most of the work of keeping the saving believable.

**Cargo we did not change is costed at what it actually cost.** Where a container
holds one group's pallets and that group already filled whole containers,
consolidation has done nothing to it. Re-pricing it through the rate model would
let rate noise leak into the comparison and show a saving on cargo nobody touched.
Those containers keep their actual invoice cost and contribute exactly zero.

**The warehouse step is charged, not assumed away.** Consolidation buys fewer
containers by adding a receiving, handling, drayage and storage step that does not
exist today. Those costs are real, they are the reason origin cost rises while the
total falls, and a model that omitted them would produce a saving the client would
never see.

**A leg is charged on the unit it is actually bought in.** Almost every leg here is
bought per container, and one is not: collection is a truck to a factory, charged per
shipment, and consolidation does not reduce the number of factories. Charging it per
container instead -- which is the natural thing to do, since everything around it is
per container -- credits the plan with a saving on a leg it never touches.
"""

import pandas as pd

import config as C
import rates as R


def _pool_of(code):
    return C.CHARGE_CODE_POOLS.get(code, "Destination Other")


def find_passthrough_groups(ship, allocation, containers):
    """Cargo consolidation left alone, from either of the two ways that happens.

    **A lane the plan declined.** The packer gates every pool on whether consolidating
    it saves a container, and hands back the ones that do not exactly as they ship today
    -- see ``pack.simulate``. Nothing about that cargo is modelled, so nothing about it
    is re-priced.

    **A group the plan happened not to change.** Inside a lane it did consolidate, a
    group qualifies only if none of its containers is shared with another group *and* it
    needed no fewer containers than it books today. Either condition failing means the
    plan changed something, and the change has to be priced.
    """
    alloc = pd.DataFrame(allocation)
    if alloc.empty:
        return set(), set()

    declined = {c["container"] for c in containers if not c.get("consolidated", True)}
    groups_per_container = alloc.groupby("container")["grp"].nunique()
    shared = set(groups_per_container[groups_per_container > 1].index)

    hist = ship.set_index("grp_key")["containers_today"].to_dict()
    passthrough_groups = {g for g, d in alloc.groupby("grp")
                          if set(d["container"].unique()) & declined}
    passthrough_containers = set(declined)
    for grp, g in alloc.groupby("grp"):
        boxes = set(g["container"].unique())
        if boxes & shared or boxes & declined:
            continue
        if len(boxes) != int(hist.get(grp, 0)):
            continue
        passthrough_groups.add(grp)
        passthrough_containers |= boxes
    return passthrough_groups, passthrough_containers


# --------------------------------------------------------------------------------------
# The inbound leg: how cargo gets from the supplier to the consolidation warehouse.
#
# This is the one leg where consolidation gives the client a genuine choice, and it is
# worth being explicit about why. Today every shipment is collected on its own and
# delivered into a port CFS on its own, however small it is, because there is nowhere
# else for it to go. Under the plan the same cargo can instead be swept up by region and
# brought in as full trailer loads.
#
# Two costs move together when it is, and the second is the one that gets forgotten:
#
#   the haul          bought per trailer load instead of per container collected. Each
#                     service is costed the way it is actually sold: the forwarder's
#                     collection tariff per container, the haulier's tender per trailer.
#   the receiving     every load that arrives has to be unloaded, checked and put away,
#                     and the warehouse charges per load. This is the effect clients
#                     underestimate, and it is a warehouse saving rather than a trucking
#                     one -- so it is reported as its own line whichever way the verdict
#                     goes.
#
# The load counts on both sides come from the same bin-packer, run twice: once with each
# shipment on its own, which is today, and once pooling a region's same-day cargo, which is
# what the plan makes possible. Nothing waits for a trailer to fill in either run.
# --------------------------------------------------------------------------------------

def _pickup_shares(ship, alloc, passthrough_containers):
    """Per container, the share of each EXW shipment's inbound loads it carries.

    Two things are going on and both matter.

    The *count* is the shipment's own inbound load figure -- the containers its cargo
    fills today, which is the number of times a truck has to run from that factory. It is
    read off the shipment, never off the plan, because the plan does not change how much
    cargo the supplier has ready.

    The *allocation* follows the pallets. A shipment's cargo can end up in two modelled
    containers and its collection was bought once, so each container carries the fraction
    of the shipment it holds and the fractions sum back to exactly the shipment's own load
    count however the packer split it.
    """
    idx = ship.set_index("grp_key")
    group_pallets = idx["pallets"].to_dict()
    group_loads = idx["containers_today"].to_dict()
    out, loads = {}, 0.0
    exw = alloc[alloc["term"].eq("EXW") & ~alloc["container"].isin(passthrough_containers)]
    for (con, grp, region), g in exw.groupby(["container", "grp", "pickup_region"]):
        total = int(group_pallets.get(grp, 0)) or len(g)
        units = float(group_loads.get(grp, 0) or 0) * len(g) / total
        out.setdefault(con, {}).setdefault(region, 0.0)
        out[con][region] += units
        loads += units
    return out, loads


def _truck_shares(trucks):
    """Per container, the share of each trailer load it carries. Sums to one per truck."""
    out = {}
    for t in trucks:
        for con, share in t["containers"].items():
            out.setdefault(con, {}).setdefault(t["pickup_region"], 0.0)
            out[con][t["pickup_region"]] += share
    return out


def choose_inbound(ship, allocation, trucks, solo, rate_table, cfg,
                   passthrough_containers, card_index=None):
    """Price the inbound leg both ways, take the cheaper, and keep the arithmetic.

    Returns everything the ledger needs to post it and everything the screen needs to
    explain it, including the case where the client has given us no trailer rate at all:
    then the groupage path is costed, and the rate an FTL tender would have to beat is
    stated per load so the ask is a number rather than a suggestion.
    """
    alloc = pd.DataFrame(allocation)
    receiving = rate_table.get("SERVICE", "cfs_inbound")
    rate_receiving = float(receiving["rate_usd"]) if receiving else 0.0
    if alloc.empty:
        return {"priced": False, "path": "groupage", "loads_today": 0, "trucks": 0}

    shares, containers_collected = _pickup_shares(ship, alloc, passthrough_containers)
    delivery_shares = _truck_shares(solo)
    loads_today = len(solo)

    def collection_rate(region):
        rate = rate_table.get("ORIGIN_COMPONENT", (region, C.PICKUP_CODE))
        return float(rate["rate_usd"]) if rate else 0.0

    groupage_haul = sum(collection_rate(region) * units
                        for regions in shares.values()
                        for region, units in regions.items())
    groupage_receiving = loads_today * rate_receiving

    truck_units = _truck_shares(trucks)
    n_trucks = len(trucks)
    ftl_rows = {}
    for key in sorted(card_index or {}):
        if key[0] == "FTL" and key[3] == "INBOUND_FTL":
            ftl_rows[_place_key(key[1])] = card_index[key]

    out = {
        "priced": True,
        "loads_today": loads_today,
        "containers_collected": round(containers_collected, 1),
        "trucks": n_trucks,
        "loads_saved": loads_today - n_trucks,
        "receiving_rate": round(rate_receiving, 2),
        "receiving_source": receiving["source"] if receiving else "",
        "groupage_haul": round(groupage_haul, 2),
        "groupage_receiving": round(groupage_receiving, 2),
        "groupage_total": round(groupage_haul + groupage_receiving, 2),
        "groupage_per_load": round(groupage_haul / containers_collected, 2)
        if containers_collected else 0.0,
        "solo_pallets_mean": round(
            sum(t["pallets"] for t in solo) / loads_today, 1) if loads_today else 0.0,
        "solo_fill_pct": round(
            sum(t["fill_pallet_pct"] for t in solo) / loads_today, 1) if loads_today else 0.0,
        "trailer_pallets_mean": round(
            sum(t["pallets"] for t in trucks) / n_trucks, 1) if n_trucks else 0.0,
        "trailer_fill_pct": round(
            sum(t["fill_pallet_pct"] for t in trucks) / n_trucks, 1) if n_trucks else 0.0,
        "trailer_cap_pallets": cfg["TRAILER_PALLET_MAX"],
        "pickup_shares": shares,
        "delivery_shares": delivery_shares,
        "truck_shares": truck_units,
        "supplied": bool(ftl_rows),
        "path": "groupage",
    }

    if not n_trucks:
        return out
    if not ftl_rows:
        # No rate to test, so the ask is quantified instead. What a trailer rate has to
        # beat is the whole groupage bill less the receiving the trailers would still
        # incur -- because those receiving charges are bought either way, just fewer of
        # them, and folding them into the target would flatter the tender.
        target = (out["groupage_total"] - n_trucks * rate_receiving) / n_trucks
        out["headroom_per_load"] = round(target, 2)
        out["headroom_total"] = round(out["groupage_total"], 2)
        return out

    def ftl_rate(region):
        hit = ftl_rows.get(_place_key(region)) or ftl_rows.get("")
        return float(hit["rate_usd"]) if hit else None

    missing = sorted({t["pickup_region"] for t in trucks if ftl_rate(t["pickup_region"]) is None})
    if missing:
        # A partial tender prices some regions and not others. Comparing it against the
        # whole groupage bill would credit it with the regions it does not cover, so it is
        # reported as partial and the groupage path stands.
        out["partial_regions"] = missing
        return out

    ftl_haul = sum(ftl_rate(t["pickup_region"]) for t in trucks)
    ftl_receiving = n_trucks * rate_receiving
    ftl_total = ftl_haul + ftl_receiving
    taken = ftl_total < out["groupage_total"]
    out.update({
        "ftl_haul": round(ftl_haul, 2),
        "ftl_receiving": round(ftl_receiving, 2),
        "ftl_total": round(ftl_total, 2),
        "ftl_per_load": round(ftl_haul / n_trucks, 2),
        "ftl_rates": {r: ftl_rate(r) for r in sorted({t["pickup_region"] for t in trucks})},
        "delta_total": round(ftl_total - out["groupage_total"], 2),
        "delta_haul": round(ftl_haul - groupage_haul, 2),
        "delta_receiving": round(ftl_receiving - groupage_receiving, 2),
        "path": "ftl" if taken else "groupage",
        "taken": bool(taken),
    })
    return out


def _place_key(value):
    return str(value or "").strip().upper()


def baseline(ship):
    """What the client actually paid, by cost pool, on in-scope cargo.

    Taken from the invoices and nothing else. This is the figure the saving is
    measured against, so it is never modelled -- if the baseline moved with our rate
    assumptions the comparison would be meaningless.
    """
    e = ship[ship["in_scope"]]
    by_pool = {p: round(float(e[p].sum()), 2) for p in C.COST_POOLS}
    by_pool["Total"] = round(sum(by_pool.values()), 2)
    return by_pool


def cost_containers(containers, allocation, ship, rate_table, cfg,
                    passthrough_containers=frozenset(), inbound=None):
    """Cost each modelled container, emitting a ledger row for every charge."""
    alloc = pd.DataFrame(allocation)
    ship_idx = ship.set_index("grp_key")

    # Actual cost per pallet, for the containers we are not re-pricing.
    actual_per_pallet = {}
    for grp, row in ship_idx.iterrows():
        if int(row["pallets"]) > 0:
            actual_per_pallet[grp] = {
                p: float(row[p]) / int(row["pallets"]) for p in C.COST_POOLS}

    ledger, con_rows = [], []
    for con in containers:
        n = con["container"]
        mine = alloc[alloc["container"].eq(n)]
        pallets = len(mine)
        pools = {p: 0.0 for p in C.COST_POOLS}

        def charge(pool, rate_id, item, source, unit, qty, usd, note):
            """Post one charge to both the pool total and the ledger.

            Rounding happens here and only here, so a container's cost is by
            construction the sum of its own ledger rows. Rounding the two
            separately lets 19,000 half-cents drift apart, and then the control
            that proves every dollar is traceable fails for no real reason.
            """
            amount = round(float(usd), 2)
            if abs(amount) < 0.005:
                return
            pools[pool] += amount
            ledger.append(_ledger(n, pool, rate_id, item, source, unit, qty, amount, note))

        if n in passthrough_containers:
            # Unchanged cargo. Carry its own invoiced cost across, pro-rated by the
            # pallets riding in this box, and add nothing.
            # Posted once per pool for the whole box rather than once per pallet, so
            # the ledger stays readable at a container's own grain.
            for pool in C.COST_POOLS:
                amount = sum(actual_per_pallet.get(r["grp"], {}).get(pool, 0.0)
                             for r in mine.to_dict("records"))
                charge(pool, "ACTUAL-INVOICE", "Actual invoiced cost", "ACTUAL_INVOICE",
                       "per pallet, this container's share", pallets, amount,
                       "Container unchanged by consolidation; carried at its own invoiced cost.")
            con_rows.append(_con_row(con, pools, passthrough=True))
            continue

        # --- ocean ------------------------------------------------------------
        ocean = rate_table.get("OCEAN", (con["cfs"], con["pod"]))
        if ocean:
            charge("Freight", ocean["rate_id"], ocean["item"], ocean["source"],
                   "per container", 1, ocean["rate_usd"], ocean["derivation"])

        # --- origin components, EXW pallets only -------------------------------
        # FOB cargo reaches the port at the supplier's cost, so a container that is
        # part FOB pays only the EXW share of the origin component set.
        #
        # Collection is not in this loop. It is bought per shipment, not per container,
        # and it is posted below off the inbound plan.
        for region, g in mine[mine["term"].eq("EXW")].groupby("pickup_region"):
            share = len(g) / pallets if pallets else 0.0
            for code in C.CONTAINER_COMPONENT_CODES:
                rate = rate_table.get("ORIGIN_COMPONENT", (region, code))
                if not rate:
                    continue
                charge(_pool_of(code), rate["rate_id"], rate["item"], rate["source"],
                       "per container x EXW pallet share", round(share, 4),
                       rate["rate_usd"] * share,
                       f"{rate['derivation']} Charged on {len(g)} of {pallets} pallets.")

        # --- getting the cargo here in the first place --------------------------
        # Either one collection per shipment, or a share of the trailer loads the plan
        # sweeps up by region -- whichever the inbound plan found cheaper. Both carry the
        # warehouse's receiving charge on the same count, because every load that arrives
        # has to be unloaded whoever hauled it.
        plan_inbound = inbound or {}
        receiving = rate_table.get("SERVICE", "cfs_inbound")
        if plan_inbound.get("path") == "ftl":
            ftl_rates = plan_inbound["ftl_rates"]
            for region, units in sorted(
                    plan_inbound["truck_shares"].get(n, {}).items()):
                charge("Origin Pickup", "NEW-INBOUND-FTL",
                       f"Inbound trailer load from {region}", R.CARD,
                       "per trailer load, this container's share", round(units, 4),
                       ftl_rates[region] * units,
                       f"Your trailer tender at ${ftl_rates[region]:,.2f} a load. "
                       f"{plan_inbound['trucks']} trailer loads carry what "
                       f"{plan_inbound['loads_today']} separate collections carry today.")
                if receiving:
                    charge("Origin CFS", receiving["rate_id"], receiving["item"],
                           receiving["source"], "per inbound delivery received",
                           round(units, 4), receiving["rate_usd"] * units,
                           receiving["derivation"])
        else:
            for region, units in sorted(
                    plan_inbound.get("pickup_shares", {}).get(n, {}).items()):
                rate = rate_table.get("ORIGIN_COMPONENT", (region, C.PICKUP_CODE))
                if rate:
                    charge("Origin Pickup", rate["rate_id"], rate["item"], rate["source"],
                           "per container collected, this container's share",
                           round(units, 4), rate["rate_usd"] * units,
                           rate["derivation"] + " Charged on the cargo's own inbound load "
                           "count, not on the containers the plan builds — collecting from "
                           "a factory is the same job either way.")
            # Once for the loads that actually turn up here, and deliberately not inside
            # the loop above: a container holding cargo from two pickup regions is still
            # one set of arrivals, and posting the receiving per region charged it twice.
            if receiving:
                for region, units in sorted(
                        plan_inbound.get("delivery_shares", {}).get(n, {}).items()):
                    charge("Origin CFS", receiving["rate_id"], receiving["item"],
                           receiving["source"], "per inbound delivery received",
                           round(units, 4), receiving["rate_usd"] * units,
                           receiving["derivation"])

        # --- the new warehouse step -------------------------------------------
        # Sources come off the rate table, not from a constant here. Whether the
        # warehouse step is priced from the client's quote or from our benchmark is a
        # decision made once, and the ledger has to carry whichever it was.
        handling = rate_table.get("SERVICE", "cfs_handling")
        if handling:
            charge("Origin CFS", handling["rate_id"], handling["item"],
                   handling["source"], "per container built", 1,
                   handling["rate_usd"], handling["derivation"])
        drayage = rate_table.get("SERVICE", "cfs_drayage")
        if drayage:
            charge("Origin CFS", drayage["rate_id"], drayage["item"],
                   drayage["source"], "per container built", 1,
                   drayage["rate_usd"], drayage["derivation"])

        storage = rate_table.get("SERVICE", "cfs_storage")
        if storage:
            free = cfg["CFS_STORAGE_FREE_DAYS"]
            cbm_days = sum(max(0, int(r["wait_days"]) - free) * float(r["cbm"])
                           for r in mine.to_dict("records"))
            charge("Origin CFS", storage["rate_id"], storage["item"],
                   storage["source"], "CBM-days beyond the free period",
                   round(cbm_days, 2), cbm_days * storage["rate_usd"],
                   storage["derivation"])

        # --- the strip, where a box carries cargo for more than one warehouse ---
        # Zero under one-site-per-container. It exists so that letting sites share a
        # container cannot look free: the fuller box has to pay for being broken
        # apart again and delivered separately at the far end.
        extra_sites = max(0, mine["site"].nunique() - 1)
        strip = rate_table.get("SERVICE", "deconsol")
        if extra_sites and strip:
            charge("Destination CFS", strip["rate_id"], strip["item"],
                   strip["source"], "per extra site on the container", extra_sites,
                   extra_sites * strip["rate_usd"], strip["derivation"])

        # --- destination delivery ----------------------------------------------
        for site, g in mine.groupby("site"):
            rate = rate_table.get("DEST_DELIVERY", (con["pod"], site))
            if not rate:
                continue
            share = len(g) / pallets if pallets else 0.0
            # One site per container under the operating pool key, so the share is
            # 1.0 and the container pays one delivery. Where sites are allowed to
            # mix, each site's share of the box pays its own lane rate.
            single_site = len(mine["site"].unique()) == 1
            charge("Destination Drop-off", rate["rate_id"], rate["item"], rate["source"],
                   "per container on lane", 1 if single_site else round(share, 4),
                   rate["rate_usd"] * (1.0 if single_site else share), rate["derivation"])

        # --- everything else the history charges per container ------------------
        for rate in rate_table.rows[rate_table.rows["category"].eq("OTHER")].to_dict("records"):
            charge(_pool_of(rate["charge_code"]), rate["rate_id"], rate["item"],
                   rate["source"], "per container", 1, rate["rate_usd"], rate["derivation"])

        con_rows.append(_con_row(con, pools, passthrough=False))

    return pd.DataFrame(con_rows), pd.DataFrame(ledger)


def _con_row(con, pools, passthrough):
    row = dict(con)
    row.pop("sites_list", None)
    # ``consolidated`` means the final plan actually changes this box, not merely that
    # its lane was eligible for consolidation. A single-shipment box inside an adopted
    # lane can still pass through unchanged and is neither re-priced nor sent to the CFS.
    row["consolidated"] = bool(con.get("consolidated", True) and not passthrough)
    for pool in C.COST_POOLS:
        row[pool] = round(pools[pool], 2)
    row["total_usd"] = round(sum(pools.values()), 2)
    row["passthrough"] = passthrough
    row["how_built"] = (
        "Ships LCL in a co-loader's box, as it does today"
        if not con.get("counts_as_boxes", 1) else
        "Left alone — this lane cannot save a container, so it ships as it does today"
        if not con.get("consolidated", True) else
        "Unchanged — this cargo ships as it does today" if passthrough else
        "Built at the warehouse from several shipments" if con["built_at_cfs"] else
        "Built at the warehouse from one shipment")
    return row


def _ledger(container, pool, rate_id, item, source, unit, qty, usd, note):
    return {"container": container, "pool": pool, "rate_id": rate_id, "item": item,
            "rate_source": source, "unit": unit, "quantity": qty,
            "usd": round(float(usd), 2), "basis": note}


def summarise(ship, con_costed, ledger, rate_table, inbound=None, cfg=None):
    """Roll the two states up and state what rests on an assumption."""
    cfg = cfg or C.values()
    today = baseline(ship)
    future = {p: round(float(con_costed[p].sum()), 2) for p in C.COST_POOLS}
    future["Total"] = round(sum(future.values()), 2)

    def by_source(source):
        return float(ledger.loc[ledger["rate_source"].eq(source), "usd"].sum())

    assumed_usd = by_source(R.ASSUMED)
    derived_usd = by_source(R.DERIVED)
    card_usd = by_source(R.CARD)
    quoted_usd = by_source(R.QUOTED)
    actual_usd = by_source("ACTUAL_INVOICE")

    containers_today = int(ship.loc[ship["in_scope"], "containers_today"].sum())
    # Boxes of the client's own, not rows in the table. Cargo that ships LCL today rides
    # in a co-loader's container and books none of theirs; where the plan declines its
    # lane it still books none, so it appears as a row worth zero containers. Counting
    # rows had a declined lane reporting boxes the client does not pay for.
    containers_future = int(con_costed["counts_as_boxes"].sum())
    boxed = con_costed[con_costed["counts_as_boxes"].gt(0)]
    declined = con_costed[~con_costed["consolidated"]]
    saving = round(today["Total"] - future["Total"], 2)

    # Cargo that ships LCL today books no container of the client's, so it is absent from
    # containers_today and present in the plan's boxes. Reported rather than reconciled
    # away: the two counts are honest, but they are not like for like, and a reader
    # comparing them is entitled to know which cargo moved between the columns.
    in_scope = ship[ship["in_scope"]]
    lcl = in_scope[in_scope["mode"].str.contains("LCL", na=False)]
    today_fill = (float(in_scope["cbm"].sum()) / containers_today
                  if containers_today else 0.0)
    any_consolidated = bool(con_costed["consolidated"].any())
    mean_fill = float(boxed["cbm"].mean()) if len(boxed) else 0.0
    mean_fill_pct = float(boxed["fill_cbm_pct"].mean()) if len(boxed) else 0.0
    mean_pallets = float(boxed["pallets"].mean()) if len(boxed) else 0.0
    # When no lane is adopted, the result is today's operation. Re-spreading historical
    # pallets across their recorded box count is an audit representation, not a new fill
    # outcome, so it must not make an unchanged dashboard claim fill moved.
    if not any_consolidated:
        mean_fill = today_fill
        mean_fill_pct = 100.0 * today_fill / cfg["OUT_CBM_MAX"] if cfg["OUT_CBM_MAX"] else 0.0
        mean_pallets = (float(in_scope["pallets"].sum()) / containers_today
                        if containers_today else 0.0)

    return {
        "today": today,
        "future": future,
        "saving_usd": saving,
        "saving_pct": round(saving / today["Total"], 4) if today["Total"] else 0.0,
        "containers_today": containers_today,
        "containers_future": containers_future,
        "containers_saved": containers_today - containers_future,
        "container_reduction_pct": round(
            1 - containers_future / containers_today, 4) if containers_today else 0.0,
        "passthrough_containers": int(con_costed["passthrough"].sum()),
        "cfs_built_containers": int((~con_costed["passthrough"]).sum()),
        # Lanes the plan declined outright, because consolidating them could not save a
        # container. Reported rather than hidden: it is the single clearest statement of
        # what the model will not do, and on one of our own datasets it is most of the file.
        "declined_containers": int(declined["counts_as_boxes"].sum()),
        "declined_lanes": int(declined.groupby(["cfs", "pod", "pool_third"]).ngroups)
        if len(declined) else 0,
        "declined_cbm": round(float(declined["cbm"].sum()), 1),
        "declined_cbm_share": round(
            float(declined["cbm"].sum()) / float(con_costed["cbm"].sum()), 4)
        if float(con_costed["cbm"].sum()) else 0.0,
        "consolidated_lanes": int(
            con_costed[con_costed["consolidated"]]
            .groupby(["cfs", "pod", "pool_third"]).ngroups)
        if int(con_costed["consolidated"].sum()) else 0,
        "inbound": dict(inbound or {}, pickup_shares=None, truck_shares=None),
        "lcl_groups_today": int(len(lcl)),
        "lcl_cbm_today": round(float(lcl["cbm"].sum()), 1),
        "lcl_cbm_share": round(
            float(lcl["cbm"].sum()) / float(in_scope["cbm"].sum()), 4)
        if float(in_scope["cbm"].sum()) else 0.0,
        # Averaged over the boxes the client actually books under the plan, so it is
        # like for like with today's fill. LCL cargo riding in a co-loader's box is no
        # more one of their containers here than it is today.
        "mean_fill_cbm": round(mean_fill, 1),
        "mean_fill_pct": round(mean_fill_pct, 1),
        "mean_pallets": round(mean_pallets, 1),
        "today_fill_cbm": round(today_fill, 1),
        "cost_per_cbm_today": round(
            today["Total"] / float(ship.loc[ship["in_scope"], "cbm"].sum()), 2)
        if float(ship.loc[ship["in_scope"], "cbm"].sum()) else 0.0,
        "cost_per_cbm_future": round(
            future["Total"] / float(ship.loc[ship["in_scope"], "cbm"].sum()), 2)
        if float(ship.loc[ship["in_scope"], "cbm"].sum()) else 0.0,
        "provenance": {
            "rates_from_card": rate_table.stats["from_card"],
            "rates_derived": rate_table.stats["derived"],
            "rates_quoted": rate_table.stats["quoted"],
            "rates_assumed": rate_table.stats["assumed"],
            "rates_invented": 0,
            "usd_from_card": round(card_usd, 2),
            "usd_derived": round(derived_usd, 2),
            "usd_quoted": round(quoted_usd, 2),
            "usd_assumed": round(assumed_usd, 2),
            "usd_actual_invoice": round(actual_usd, 2),
            # Only genuine assumptions count here. A forwarder's quote is evidence of a
            # different kind from an invoice, not an absence of evidence, so folding it
            # into this figure would overstate what the answer rests on.
            "assumed_share": round(assumed_usd / future["Total"], 4)
            if future["Total"] else 0.0,
            "evidenced_share": round(
                (card_usd + derived_usd + quoted_usd + actual_usd) / future["Total"], 4)
            if future["Total"] else 0.0,
        },
        "ledger_rows": int(len(ledger)),
    }


def lane_clears_rule(row, cfg):
    """The deterministic commercial rule that decides whether a site lane is adopted."""
    return (float(row["saving_usd"]) > float(cfg["LANE_MIN_SAVING_USD"])
            or float(row["saving_pct"]) > float(cfg["LANE_MIN_SAVING_PCT"]))


def lane_verdicts(ship, con_costed, allocation, cfg=None, rejected=None):
    """Report and judge every origin–port–destination-site lane in the final plan.

    Sites remain separate even when they share a country-level container pool, because
    their final delivery legs are different. Shared boxes and their cost are attributed
    to sites by the share of CBM each site places in the box. Those shares sum to one for
    every container, so the site rows reconcile to both the final box count and total cost.
    """
    cfg = cfg or C.values()
    rejected = rejected or {}
    e = ship[ship["in_scope"]].copy()
    e["lcl_cbm"] = e["cbm"].where(e["mode"].str.contains("LCL", na=False), 0.0)
    today = (e.groupby(["cfs", "pod", "site"])
             .agg(containers_today=("containers_today", "sum"),
                  pallets=("pallets", "sum"), cbm=("cbm", "sum"),
                  lcl_cbm_today=("lcl_cbm", "sum"),
                  cost_today=("invoiced_usd", "sum"), groups=("grp_key", "nunique")))

    alloc = pd.DataFrame(allocation).rename(columns={"cbm": "site_cbm_piece"})
    parts = (alloc.groupby(["container", "site"], as_index=False)
             .agg(site_cbm=("site_cbm_piece", "sum"),
                  site_pallets=("pallet_id", "count")))
    parts["container_cbm"] = parts.groupby("container")["site_cbm"].transform("sum")
    parts["container_pallets"] = parts.groupby("container")["site_pallets"].transform("sum")
    parts["share"] = (parts["site_cbm"] / parts["container_cbm"].where(
        parts["container_cbm"] > 0))
    no_cbm = parts["share"].isna()
    parts.loc[no_cbm, "share"] = (
        parts.loc[no_cbm, "site_pallets"]
        / parts.loc[no_cbm, "container_pallets"].where(
            parts.loc[no_cbm, "container_pallets"] > 0))

    con = con_costed[["container", "cfs", "pod", "counts_as_boxes", "total_usd",
                      "cbm", "dwell_days", "consolidated", "passthrough"]]
    parts = parts.merge(con, on="container", how="left", validate="many_to_one")
    if parts[["cfs", "pod", "total_usd"]].isna().any().any():
        raise ValueError("site-lane allocation refers to a container that was not costed")
    parts["containers_future"] = parts["counts_as_boxes"] * parts["share"]
    parts["cost_future"] = parts["total_usd"] * parts["share"]
    parts["fill_weight"] = parts["cbm"] * parts["share"]
    parts["dwell_units"] = parts["share"].where(~parts["passthrough"], 0.0)
    parts["dwell_weight"] = parts["dwell_days"] * parts["dwell_units"]

    modelled = (parts.groupby(["cfs", "pod", "site"])
                .agg(containers_future=("containers_future", "sum"),
                     cost_future=("cost_future", "sum"),
                     share_units=("share", "sum"),
                     fill_weight=("fill_weight", "sum"),
                     dwell_units=("dwell_units", "sum"),
                     dwell_weight=("dwell_weight", "sum"),
                     consolidated=("consolidated", "max")))
    modelled["mean_fill_cbm"] = (
        modelled["fill_weight"] / modelled["share_units"].where(
            modelled["share_units"] > 0)).fillna(0.0)
    modelled["mean_dwell"] = (
        modelled["dwell_weight"] / modelled["dwell_units"].where(
            modelled["dwell_units"] > 0)).fillna(0.0)

    lanes = today.join(modelled, how="left").fillna(
        {"containers_future": 0.0, "cost_future": 0.0, "mean_fill_cbm": 0.0,
         "mean_dwell": 0.0, "consolidated": False}).reset_index()
    lanes["consolidated"] = lanes["consolidated"].astype(bool)
    lanes["grain"] = "site"
    # A rejected lane is the final plan as shipped today, not the rejected candidate.
    # Force that identity at the reporting boundary so pallet-level cent rounding can
    # never put a saving, loss or changed box count beside "Leave alone".
    unchanged = ~lanes["consolidated"]
    lanes.loc[unchanged, "containers_future"] = lanes.loc[unchanged, "containers_today"]
    lanes.loc[unchanged, "cost_future"] = lanes.loc[unchanged, "cost_today"]
    lanes.loc[unchanged, "mean_dwell"] = 0.0
    lanes["containers_future"] = lanes["containers_future"].round(4)
    lanes["containers_saved"] = (
        lanes["containers_today"] - lanes["containers_future"]).round(4)
    lanes["container_reduction_pct"] = (
        lanes["containers_saved"] / lanes["containers_today"].where(
            lanes["containers_today"] > 0)).fillna(0.0).round(4)
    lanes["saving_usd"] = (lanes["cost_today"] - lanes["cost_future"]).round(2)
    lanes["saving_pct"] = (
        lanes["saving_usd"] / lanes["cost_today"].where(
            lanes["cost_today"] > 0)).fillna(0.0).round(4)
    lanes["verdict"] = lanes.apply(
        lambda row: "Consolidate"
        if row["consolidated"] and lane_clears_rule(row, cfg) else "Leave alone", axis=1)
    lanes["why"] = lanes.apply(lambda row: _lane_why(row, cfg, rejected), axis=1)
    return lanes.sort_values(["cfs", "pod", "site"]).reset_index(drop=True)


def _lane_why(row, cfg, rejected):
    key = (row["cfs"], row["pod"], row["site"])
    hurdle = (f"${cfg['LANE_MIN_SAVING_USD']:,.0f} a year or "
              f"{cfg['LANE_MIN_SAVING_PCT']:.0%} of lane cost")
    candidate = rejected.get(key)
    if candidate:
        saving = float(candidate["saving_usd"])
        result = (f"would save ${saving:,.0f} ({candidate['saving_pct']:.1%})"
                  if saving >= 0 else
                  f"would add ${abs(saving):,.0f} ({abs(candidate['saving_pct']):.1%})")
        return (f"Left unchanged. The candidate {result}, below the rule of more than "
                f"{hurdle}. Today and modelled therefore show the same boxes and cost.")
    if not row["consolidated"]:
        return ("Left unchanged. Packing this cargo inside the dwell limit did not improve "
                "the lane enough to enter the commercial test, so today and modelled are "
                "identical.")
    return (f"Adopted. Saves ${row['saving_usd']:,.0f} ({row['saving_pct']:.1%}), clearing "
            f"the rule of more than {hurdle}. Modelled boxes are allocated by each site's "
            "CBM share where a container serves more than one site.")
