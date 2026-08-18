"""Build outbound containers by replaying the history one day at a time.

This is not a bin-packing exercise. A solver given the whole year at once would
combine cargo that was never in the warehouse at the same time and report a saving
nobody can execute. So the model steps through the calendar: on each day, cargo
that has become ready is offered to the open containers for its pool, containers
that have reached the dispatch target leave, and what is left either waits for
cargo already known to be coming or sails as it is.

Three decisions in here carry most of the result, and all three are deliberate.

**A candidate pool is built only if it saves a container.** Running cargo through a
warehouse buys handling, drayage and storage, so each pool is first checked against what
the client books today. A pool needing as many boxes -- or more -- is declined outright.
The surviving candidate is then costed in ``run.py`` at origin–port–destination-site
grain and must clear the explicit annual-dollar or percentage saving rule. Any site lane
that fails is fed back here through ``declined_site_lanes`` and restored to today's boxes
and invoiced cost. The two gates together mean the final plan is both physically and
commercially adopted; a verdict can never disagree with the containers being reported.

**Pallets are offered oldest first, never largest first.** Size-ordered loading
packs any single container tighter, which is why it is the obvious choice and the
wrong one. The packer sits inside a simulation with a dispatch trigger, so the
order pallets are offered in decides *which container fills first*, and therefore
what leaves and what carries over. Keeping cargo of the same age together clears
containers at the target instead of stranding half-full residuals waiting for cargo
that never arrives.

**A residual waits only on cargo already known to be coming.** The hold test is
physical, not economic: hold only if cargo destined for the same pool lands inside
the oldest pallet's remaining dwell allowance. Because the lookahead can never
exceed the remaining allowance, the dwell cap cannot be breached by construction
rather than by a check after the fact.
"""

from collections import defaultdict


def pool_key_of(pallet, pool_key):
    """What may share a container.

    ``cfs_pod_site`` puts exactly one delivery site in every container: nothing is
    ever split between two warehouses, so no container needs stripping at
    destination. ``cfs_pod`` lets sites in the same country share a box, which
    fills containers better but buys a deconsolidation step at the far end.
    Countries never mix under either key -- cross-border delivery is a different
    rate and usually a different customs treatment.
    """
    if pool_key == "cfs_pod_site":
        return (pallet["cfs"], pallet["pod"], pallet["site"])
    return (pallet["cfs"], pallet["pod"], pallet["site_country"])


def pack_arrival_order(items, cfg):
    """First fit in arrival order: oldest pallet first, never reordered by size.

    Each pallet goes into the first open container where volume, pallet count and
    weight all still hold; a new container opens only when none of them fits. The
    tie-break within a single ready day is fixed -- larger volume first, then group,
    then pallet sequence -- so the same input always produces the same containers.
    """
    if not items:
        return []
    bins = []
    ordered = sorted(items, key=lambda p: (p["ready_day"], -p["cbm"], p["grp"], p["seq"]))
    for pallet in ordered:
        for b in bins:
            if (b["cbm"] + pallet["cbm"] <= cfg["OUT_CBM_MAX"]
                    and len(b["pallets"]) + 1 <= cfg["OUT_PALLET_MAX"]
                    and b["gwt"] + pallet["gwt"] <= cfg["OUT_WEIGHT_MAX_KG"]):
                b["pallets"].append(pallet)
                b["cbm"] += pallet["cbm"]
                b["gwt"] += pallet["gwt"]
                break
        else:
            bins.append({"pallets": [pallet], "cbm": pallet["cbm"], "gwt": pallet["gwt"]})
    return bins


def reaches_target(b, cfg):
    """Whether a container is full enough to dispatch.

    Either target releases it. A box at 52 CBM on 30 pallets is as ready to go as
    one at 44 CBM on 38 -- both are as full as the cargo available allows.
    """
    return (b["cbm"] >= cfg["OUT_CBM_TARGET"]
            or len(b["pallets"]) >= cfg["OUT_PALLET_TARGET"])


def _consolidate_pool(items, cfg):
    """Replay one pool's calendar and return the containers it would build.

    Containers are dispatched for one of four reasons, and the reason is kept. It
    is the honest answer to "why did this box leave half empty?", and the mix of
    reasons is the best single read on whether a lane is worth consolidating at all.
    """
    dwell_max = cfg["MAX_DWELL_DAYS"]
    by_day = defaultdict(list)
    for p in items:
        by_day[p["ready_day"]].append(p)
    days = sorted(by_day)

    out, held = [], []
    for i, day in enumerate(days):
        held += by_day[day]
        last_day = i == len(days) - 1

        waiting = []
        for b in pack_arrival_order(held, cfg):
            if reaches_target(b, cfg):
                out.append(_built(b, day, "target_reached"))
            else:
                waiting.append(b)

        still_held = []
        for b in waiting:
            oldest = min(p["ready_day"] for p in b["pallets"])
            remaining = dwell_max - (day - oldest)

            if remaining <= 0:
                out.append(_built(b, day, "max_dwell_reached"))
                continue
            if last_day:
                out.append(_built(b, day, "end_of_history"))
                continue
            # Only cargo that lands inside the oldest pallet's remaining allowance
            # counts. Looking past it is what would break the cap. The lookahead is
            # capped at the allowance for the same reason.
            incoming = any(d <= day + min(remaining, dwell_max) for d in days[i + 1:])
            if incoming:
                still_held += b["pallets"]
            else:
                out.append(_built(b, day, "no_qualifying_arrival"))
        held = still_held
    return out


def _built(b, day, reason):
    return (dict(b, consolidated=True, counts_as_boxes=1, as_shipped_grp=None),
            day, reason)


def as_shipped(items, boxes_today):
    """The same cargo in the boxes it already travels in, for a pool the plan declines.

    Reproducing the invoice, not packing anything: each shipment keeps exactly the
    container count its own equipment lines record, so a declined lane shows zero
    containers saved rather than a number the packer happened to reach. Pallets are
    spread across those boxes largest-first into the emptiest box, which decides how
    the container list *reads* and no money at all -- a declined pool is costed at its
    own invoices, pro-rated per pallet, so any two spreads cost the same to the cent.

    Cargo that ships LCL today books none of the client's containers, and it still
    books none here: it rides in a co-loader's box, so it is carried at its invoiced
    cost against a container count of zero. Counting it as a box in the plan while it
    counts as nothing today is exactly the asymmetry that made a declined lane look
    like it had grown.
    """
    out = []
    by_grp = defaultdict(list)
    for p in items:
        by_grp[p["grp"]].append(p)

    for grp in sorted(by_grp):
        pallets = by_grp[grp]
        day = max(p["ready_day"] for p in pallets)
        n = min(int(boxes_today.get(grp, 0)), len(pallets))
        if n <= 0:
            out.append((_as_shipped_box(pallets, grp, counts=0), day, "ships_lcl_today"))
            continue
        bins = [[] for _ in range(n)]
        for p in sorted(pallets, key=lambda p: (-p["cbm"], p["seq"])):
            smallest = min(bins, key=lambda b: (sum(x["cbm"] for x in b), len(b)))
            smallest.append(p)
        for b in bins:
            out.append((_as_shipped_box(b, grp, counts=1), day, "not_consolidated"))
    return out


def _as_shipped_box(pallets, grp, counts):
    return {"pallets": list(pallets),
            "cbm": sum(p["cbm"] for p in pallets),
            "gwt": sum(p["gwt"] for p in pallets),
            "consolidated": False, "counts_as_boxes": counts, "as_shipped_grp": grp}


def simulate(pal, cfg, boxes_today=None, declined_site_lanes=frozenset()):
    """Replay every ready-date in the file and return the containers the plan moves.

    Each pool is independent, because cargo for different warehouses can never share a
    box. Within a pool the day's held cargo is repacked together with the day's
    arrivals -- repacking rather than appending matters, because a new pallet may
    complete a box that was previously waiting.

    ``boxes_today`` maps a shipment group to the containers its own equipment lines
    record. Given it, every pool has to clear the gate in the module docstring: build
    fewer boxes than the lane already moves, or be handed back untouched. Omit it and
    the packer consolidates everything, which is what the tuning scripts want and is
    never what the model runs.

    ``declined_site_lanes`` is the commercial gate applied after a candidate has been
    costed. It stays at origin–port–site grain even when the remaining sites may share a
    country pool: rejected cargo is restored to the boxes it uses today, while the sites
    that cleared the rule are repacked together.
    """
    if pal.empty:
        return []

    pools = defaultdict(list)
    for rec in pal.to_dict("records"):
        pools[pool_key_of(rec, cfg["POOL_KEY"])].append(rec)

    containers = []
    for key in sorted(pools, key=lambda k: [str(x) for x in k]):
        items = pools[key]
        blocked = [p for p in items
                   if (p["cfs"], p["pod"], p["site"]) in declined_site_lanes]
        active = [p for p in items
                  if (p["cfs"], p["pod"], p["site"]) not in declined_site_lanes]

        if blocked:
            containers += [(key, b, day, reason)
                           for b, day, reason in as_shipped(blocked, boxes_today)]
        if not active:
            continue

        built = _consolidate_pool(active, cfg)
        if boxes_today is not None:
            today = sum(int(boxes_today.get(g, 0)) for g in {p["grp"] for p in active})
            if sum(b[0]["counts_as_boxes"] for b in built) >= today:
                built = as_shipped(active, boxes_today)
        containers += [(key, b, day, reason) for b, day, reason in built]

    return containers


def assemble(containers, cfg):
    """Number the containers and summarise each one.

    Ordered by warehouse, then port, then site, then the day it sailed, so the
    numbering is stable across runs and reads in the order the work happens.
    """
    ordered = sorted(
        containers,
        key=lambda t: ([str(x) for x in t[0]], t[2],
                       -t[1]["cbm"], t[1]["pallets"][0]["pallet_id"]))

    rows, allocation = [], []
    for n, (key, b, day, reason) in enumerate(ordered, start=1):
        cfs, pod, site_or_country = key
        pallets = b["pallets"]
        groups = sorted({p["grp"] for p in pallets})
        ready_days = [p["ready_day"] for p in pallets]
        consolidated = bool(b.get("consolidated", True))
        rows.append({
            "container": n,
            "container_ref": f"{_abbr(cfs)}-{_abbr(pod)}-{n:04d}",
            "cfs": cfs,
            "pod": pod,
            "pool_third": site_or_country,
            # Site names contain a comma ("Corby, UK"), so the list is carried as a
            # list. Joining it for display and splitting it back would silently cut
            # every site in half.
            "sites_list": sorted({p["site"] for p in pallets}),
            "sites": " + ".join(sorted({p["site"] for p in pallets})),
            "site_countries": " + ".join(sorted({p["site_country"] for p in pallets})),
            "pallets": len(pallets),
            "cbm": round(b["cbm"], 3),
            "gwt": round(b["gwt"], 2),
            "fill_cbm_pct": round(100.0 * b["cbm"] / cfg["OUT_CBM_MAX"], 1),
            "fill_pallet_pct": round(100.0 * len(pallets) / cfg["OUT_PALLET_MAX"], 1),
            "groups": len(groups),
            "dispatch_reason": reason,
            "dispatch_day": day,
            "first_ready_day": min(ready_days),
            "last_ready_day": max(ready_days),
            # A declined box is not held anywhere: it never enters the warehouse, so it
            # accrues no dwell and no storage. Reporting the packer's dwell for cargo the
            # plan does not touch would put storage days on a box that never waited.
            "dwell_days": (day - min(ready_days)) if consolidated else 0,
            "built_at_cfs": consolidated and len(groups) > 1,
            # Whether the plan touched this cargo at all. Everything downstream reads
            # this: what gets re-priced, what gets a lead-time delta, what counts as a
            # container of the client's.
            "consolidated": consolidated,
            "counts_as_boxes": int(b.get("counts_as_boxes", 1)),
            "as_shipped_grp": b.get("as_shipped_grp"),
        })
        for p in pallets:
            allocation.append({
                "container": n, "pallet_id": p["pallet_id"], "grp": p["grp"],
                "cbm": p["cbm"], "gwt": p["gwt"], "site": p["site"],
                "term": p["term"], "shipper": p["shipper"],
                "pickup_region": p["pickup_region"],
                "cfs": p["cfs"],
                "consolidated": consolidated,
                "ready_day": p["ready_day"], "cfs_ready": p["cfs_ready"],
                "wait_days": (day - p["ready_day"]) if consolidated else 0,
            })
    return rows, allocation


# --------------------------------------------------------------------------------------
# The inbound leg: getting cargo from the supplier to the consolidation warehouse.
#
# This one *is* a bin-packing problem, and the discipline is deliberately the opposite of
# the container packer's. A trailer is loaded from cargo that is all available at the same
# moment -- one region, one day -- so there is no dispatch trigger to distort and no
# carry-over to strand, and first-fit-decreasing is simply the better pack. The container
# packer cannot use it, because there the loading order decides which box fills first and
# therefore what sails; here it decides nothing but how full the truck is.
#
# The trailer is capped three ways like a container, and for the same reason: a run is
# limited by whichever of floor space, volume and payload it hits first.
# --------------------------------------------------------------------------------------

def plan_inbound_trucks(allocation, cfg, pooled=True):
    """Bin-pack the cargo the plan collects into road loads.

    ``pooled`` is the whole comparison, and it is one line of difference.

      True   one pack per warehouse, pickup region and ready date, so cargo from three
             suppliers in a region that is ready on the same day can share a trailer.
             This is what the plan makes possible: the cargo is going to a warehouse
             that will mix it anyway.
      False  the same pack, but each shipment on its own -- which is what happens today,
             because each shipment is going to a port CFS to be stuffed into its own
             container and cannot travel with anybody else's.

    Nothing waits for a trailer to fill under either setting. Holding a supplier's cargo
    back a few days would pack trucks considerably better and is exactly the assumption
    that makes a plan unexecutable, so the day grain stands and the load count is whatever
    same-day cargo supports. It also keeps the inbound decision genuinely independent of
    the container plan: no pallet reaches the warehouse a day later than it does now, so
    nothing about which box it joins can move.

    Only EXW cargo appears here. FOB cargo reaches the port at the supplier's cost and
    the client never buys its inbound move, so there is nothing to re-buy.
    """
    trucks = []
    if not len(allocation):
        return trucks

    groups = defaultdict(list)
    for r in allocation:
        if r["term"] != "EXW" or not r.get("consolidated", True):
            continue
        key = (r["cfs"], r["pickup_region"], r["ready_day"])
        groups[key if pooled else key + (r["grp"],)].append(r)

    for key in sorted(groups, key=lambda k: (str(k[0]), str(k[1]), k[2], str(k[3:]))):
        cfs, region, day = key[0], key[1], key[2]
        bins = []
        for p in sorted(groups[key], key=lambda p: (-p["cbm"], p["pallet_id"])):
            for b in bins:
                if (b["cbm"] + p["cbm"] <= cfg["TRAILER_CBM_MAX"]
                        and len(b["pallets"]) + 1 <= cfg["TRAILER_PALLET_MAX"]
                        and b["gwt"] + p["gwt"] <= cfg["TRAILER_WEIGHT_MAX_KG"]):
                    b["pallets"].append(p)
                    b["cbm"] += p["cbm"]
                    b["gwt"] += p["gwt"]
                    break
            else:
                bins.append({"pallets": [p], "cbm": p["cbm"], "gwt": p["gwt"]})
        for b in bins:
            trucks.append({
                "truck": len(trucks) + 1,
                "cfs": cfs, "pickup_region": region, "ready_day": day,
                "pallets": len(b["pallets"]),
                "cbm": round(b["cbm"], 3),
                "gwt": round(b["gwt"], 2),
                "fill_pallet_pct": round(
                    100.0 * len(b["pallets"]) / cfg["TRAILER_PALLET_MAX"], 1),
                "fill_cbm_pct": round(100.0 * b["cbm"] / cfg["TRAILER_CBM_MAX"], 1),
                # Which containers this truck's pallets ended up in, and in what
                # proportion. The inbound bill is charged per truck and the ledger is
                # kept per container, so the two are tied together here rather than
                # spread by a percentage later.
                "containers": _share_by_container(b["pallets"]),
                "groups": sorted({p["grp"] for p in b["pallets"]}),
                "pooled": pooled,
            })
    return trucks


def _share_by_container(pallets):
    counts = defaultdict(int)
    for p in pallets:
        counts[p["container"]] += 1
    total = len(pallets)
    return {c: n / total for c, n in sorted(counts.items())}


def _abbr(value):
    """Three-letter tag for a container reference: ``Rotterdam, Netherlands`` -> ROT."""
    head = str(value).split(",")[0].strip()
    letters = "".join(ch for ch in head if ch.isalpha())
    return letters[:3].upper() or "XXX"
