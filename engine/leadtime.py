"""What consolidation does to delivery dates, measured one shipment at a time.

A consolidation plan can be perfectly costed and still be unsellable, because the
question every operations person asks first is "what does this do to my lead time?".
Answering it honestly requires two disciplines.

**Use vessels that actually sailed.** A modelled container is assigned to the
earliest recorded departure on its lane on or after the day it is ready, and it
inherits that sailing's recorded arrival. So the transit time is one the client's
cargo genuinely experienced on that lane, not a carrier's published figure. The last
mile from port to door is copied from the shipment's own history unchanged, because
the plan does not touch it.

**Compare each shipment with itself.** The result is a paired per-shipment delta:
this shipment was delivered on this date, and under the plan it would be delivered
on that one. Comparing the two states as distributions -- median lead time before
against median after -- would let a shipment that got worse be cancelled out by a
different shipment that got better, and would support a per-shipment claim the data
cannot make. Every figure here is a difference computed for one shipment and then
summarised.

One consequence is stated rather than hidden: some shipments arrive *earlier* under
the plan, because they ride out on a boxmate's earlier sailing instead of waiting for
their own later booking. That is a genuine recorded departure, so it is not invented,
but it does credit consolidation with curing a booking delay that consolidation did
not cause. The count is published so the mean can be read with that in mind.
"""

import numpy as np
import pandas as pd

import config as C


def sailing_calendar(ship):
    """Departures that actually happened, by lane, with the transit each one ran.

    Built from the history, so every date the model later uses is one the client's
    own cargo travelled on.
    """
    e = ship[ship["in_scope"] & ship["act_depart"].notna() & ship["act_arriv"].notna()]
    calendar = {}
    for (cfs, pod), g in e.groupby(["cfs", "pod"]):
        sailings = (g[["act_depart", "act_arriv", "grp_key"]]
                    .drop_duplicates("act_depart")
                    .sort_values("act_depart"))
        sailings = sailings[sailings["act_arriv"] >= sailings["act_depart"]]
        calendar[(cfs, pod)] = sailings.reset_index(drop=True)
    return calendar


def assign_sailings(containers, calendar, pal, cfg, actual=None,
                    passthrough_containers=frozenset(), allocation=None):
    """Put each modelled container on the first real vessel it could catch.

    Ready date is the last pallet in the box becoming available, plus the one day a
    box needs before it can sail -- the only invented figure in the whole timing
    model. Where no recorded departure exists on or after that date, the container
    falls back to the lane's last observed transit rather than being dropped, and is
    flagged so the count is visible.

    A container the plan does not change is not modelled at all: it keeps the sailing its
    cargo actually caught. This includes both rejected lanes and single-shipment boxes
    inside an adopted lane that consolidation happens to leave exactly as shipped.
    Running either through the assignment would report a timing effect on cargo the plan
    never touched.
    """
    day_zero = pal["cfs_ready"].min()
    actual = actual or {}
    passthrough_containers = set(passthrough_containers or ())
    alloc = pd.DataFrame(allocation)
    groups_by_container = (
        alloc.groupby("container")["grp"].agg(lambda v: sorted(set(v))).to_dict()
        if len(alloc) else {})
    rows = []
    for con in containers:
        untouched = (con["container"] in passthrough_containers
                     or not con.get("consolidated", True))
        if untouched:
            groups = groups_by_container.get(con["container"], [])
            grp = con.get("as_shipped_grp") or (groups[0] if len(groups) == 1 else None)
            was = actual.get(grp, {})
            rows.append({
                "container": con["container"],
                "cfs": con["cfs"], "pod": con["pod"],
                "last_pallet_ready": day_zero + pd.Timedelta(
                    days=int(con["last_ready_day"])),
                "modelled_sail": was.get("act_depart", pd.NaT),
                "modelled_arrive": was.get("act_arriv", pd.NaT),
                "sailing_from": "ships as it does today — container unchanged",
                "sailing_is_recorded": True,
                "consolidated": False,
            })
            continue
        ready = day_zero + pd.Timedelta(days=int(con["last_ready_day"]))
        earliest = ready + pd.Timedelta(days=cfg["CFS_TO_VESSEL_DAYS"])
        lane = calendar.get((con["cfs"], con["pod"]))

        sail = arrive = pd.NaT
        source = "no_sailing_found"
        if lane is not None and len(lane):
            candidates = lane[lane["act_depart"] >= earliest]
            if len(candidates):
                pick = candidates.iloc[0]
                sail, arrive = pick["act_depart"], pick["act_arriv"]
                source = str(pick["grp_key"])
            else:
                # Past the last recorded departure on this lane. Use the lane's
                # final observed transit rather than inventing one.
                last = lane.iloc[-1]
                transit = (last["act_arriv"] - last["act_depart"]).days
                sail = earliest
                arrive = earliest + pd.Timedelta(days=transit)
                source = f"transit of {last['grp_key']} applied beyond last sailing"

        rows.append({
            "container": con["container"],
            "cfs": con["cfs"], "pod": con["pod"],
            "last_pallet_ready": ready,
            "modelled_sail": sail,
            "modelled_arrive": arrive,
            "sailing_from": source,
            "sailing_is_recorded": source not in ("no_sailing_found",)
                                   and "applied beyond" not in source,
            "consolidated": True,
        })
    return pd.DataFrame(rows)


def shipment_deltas(ship, allocation, sailings):
    """Per shipment group: delivered when today, delivered when under the plan.

    A group split across containers is not complete until its last container lands,
    so the latest arrival governs. The port-to-door leg is carried over from the
    shipment's own history, because the plan changes nothing about it.
    """
    alloc = pd.DataFrame(allocation)
    if alloc.empty:
        return pd.DataFrame()

    sailing_index = sailings.set_index("container")
    arrive = sailing_index["modelled_arrive"]
    moved = sailing_index["consolidated"]
    alloc = alloc.assign(modelled_arrive=alloc["container"].map(arrive))
    alloc = alloc.assign(moved=alloc["container"].map(moved).fillna(False).astype(bool))
    per_group = alloc.groupby("grp").agg(
        modelled_arrive=("modelled_arrive", "max"),
        containers=("container", "nunique"),
        moved=("moved", "max"),
        max_wait_days=("wait_days", "max"))

    e = ship[ship["in_scope"]].set_index("grp_key")
    out = e.join(per_group, how="inner")
    out["last_mile_days"] = (out["act_deliv"] - out["act_arriv"]).dt.days
    out["modelled_deliver"] = out["modelled_arrive"] + pd.to_timedelta(
        out["last_mile_days"].fillna(0), unit="D")
    out["delta_days"] = (out["modelled_deliver"] - out["act_deliv"]).dt.days
    out["lead_time_today"] = (out["act_deliv"] - out["cargo_ready"]).dt.days
    out["lead_time_modelled"] = (out["modelled_deliver"] - out["cargo_ready"]).dt.days
    out["measurable"] = (out["date_quality"].eq("OK")
                         & out["delta_days"].notna()
                         & out["modelled_arrive"].notna())
    # Whether the plan moved this shipment at all. Cargo on a declined lane has a delta of
    # zero because nothing happened to it, and counting those zeros as "unchanged" would
    # let a plan that declined nine lanes in ten advertise a 90% unchanged rate it did
    # nothing to earn. Every figure below is on cargo the plan actually moves.
    out["moved"] = out["moved"].fillna(False).astype(bool)
    return out.reset_index().rename(columns={"index": "grp_key"})


def summarise(deltas):
    """The paired result, plus the exclusions, plus the caveat that belongs with it."""
    empty = {
        "mean_delta_days_conservative": 0.0,
        "p95_delta_days_conservative": 0.0,
        "measurable_shipments": 0,
        "excluded_shipments": 0,
        "not_consolidated": 0,
        "mean_delta_days": 0.0,
        "median_delta_days": 0.0,
        "p95_delta_days": 0.0,
        "unaffected": 0,
        "unaffected_pct": 0.0,
        "later": 0,
        "later_median_days": 0.0,
        "later_worst_days": 0,
        "earlier": 0,
        "earlier_median_days": 0.0,
        "lead_time_today_median": 0.0,
        "lead_time_modelled_median": 0.0,
        "earlier_caveat": "",
    }
    if deltas.empty:
        return empty

    clean = deltas[deltas["measurable"] & deltas["moved"]]
    if clean.empty:
        return dict(empty,
                    excluded_shipments=int((~deltas["measurable"]).sum()),
                    not_consolidated=int((~deltas["moved"]).sum()))

    d = clean["delta_days"]
    later, earlier, same = d[d > 0], d[d < 0], d[d == 0]

    # The conservative reading, and the one to lead with. Shipments the model
    # delivers earlier are counted as unchanged rather than as a gain, because the
    # earlier vessel was always available and the client chose not to book it --
    # curing that is not something consolidation can claim. This figure can only
    # overstate the delay consolidation causes, never understate it.
    conservative = d.clip(lower=0)

    return {
        "mean_delta_days_conservative": round(float(conservative.mean()), 2),
        "p95_delta_days_conservative": float(conservative.quantile(0.95)),
        "measurable_shipments": int(len(clean)),
        "excluded_shipments": int((~deltas["measurable"]).sum()),
        "not_consolidated": int((~deltas["moved"]).sum()),
        "mean_delta_days": round(float(d.mean()), 2),
        "median_delta_days": float(d.median()),
        "p95_delta_days": float(d.quantile(0.95)),
        "unaffected": int(len(same)),
        "unaffected_pct": round(len(same) / len(clean), 4),
        "later": int(len(later)),
        "later_median_days": float(later.median()) if len(later) else 0.0,
        "later_worst_days": int(later.max()) if len(later) else 0,
        "earlier": int(len(earlier)),
        "earlier_median_days": float(abs(earlier.median())) if len(earlier) else 0.0,
        "lead_time_today_median": float(clean["lead_time_today"].median()),
        "lead_time_modelled_median": float(clean["lead_time_modelled"].median()),
        "earlier_caveat": (
            f"{len(earlier)} shipments are delivered earlier because they ride a boxmate's "
            "earlier sailing instead of waiting for their own later booking. Those departures "
            "are recorded, not invented, but they credit consolidation with curing a booking "
            "delay it did not cause, so the mean should be read with that in mind."),
    }


# --------------------------------------------------------------------------------------
# The origin panel.
#
# One panel per origin, because that is the unit an operations person owns: the question
# is never "what happens to the network" but "what happens to my Shanghai cargo". The
# shape is deliberate -- a distribution of paired deltas, then the same deltas as named
# buckets -- because the distribution shows the tail and the buckets show the size of it,
# and an audience reads the second faster than the first.
#
# One choice worth stating. The obvious denominator is every shipment out of the origin,
# counting the cargo consolidation cannot touch as unchanged. It is true, and it is
# flattering: on these files most of the file is air, road or DDP cargo, so the headline
# would read 85% unchanged without the model doing anything. The panel is built on the
# shipments the model actually moves, and the untouched population is named underneath
# rather than folded into the headline. The percentage quoted is then one the plan earned.
# --------------------------------------------------------------------------------------

# Inclusive integer bounds, ordered as they are read on the chart: best outcome first.
DELTA_BUCKETS = [
    ("8+ days earlier", -10 ** 6, -8),
    ("1–7 days earlier", -7, -1),
    ("No change", 0, 0),
    ("1–7 days later", 1, 7),
    ("8–14 days later", 8, 14),
    ("15+ days later", 15, 10 ** 6),
]

LATE_BUCKETS = [
    ("1–3 days late", 1, 3),
    ("4–7 days late", 4, 7),
    ("8–14 days late", 8, 14),
    ("15+ days late", 15, 10 ** 6),
]

# A lane this thin moves several percentage points per shipment, so its rate is quoted
# with that said out loud rather than read as a property of the lane.
THIN_LANE = 10


def _buckets(delta, spec):
    total = max(1, len(delta))
    return [{"label": label,
             "count": int(((delta >= lo) & (delta <= hi)).sum()),
             "share": round(float(((delta >= lo) & (delta <= hi)).sum()) / total, 4)}
            for label, lo, hi in spec]


def _short(place):
    """"Ho Chi Minh City, Vietnam" -> "Ho Chi Minh City". The country is on the axis."""
    return str(place).split(",")[0].strip()


def origin_panels(ship, deltas, min_shipments=25):
    """One lead-time panel per origin, on the shipments the plan actually moves.

    ``min_shipments`` is retained for callers that used the earlier signature, but no
    origin is hidden merely because the final commercial gate leaves it just below an
    arbitrary display threshold. A small population is still truthful; hiding the only
    panel on a marginal case is not.
    """
    if deltas is None or not len(deltas):
        return []
    clean = deltas[deltas["measurable"] & deltas["moved"]]
    if not len(clean):
        return []

    panels = []
    for origin, g in clean.groupby("origin"):
        d = g["delta_days"].astype(int)
        worst_row = g.loc[d.idxmax()]
        at_origin = ship[ship["origin"].eq(origin)]
        in_scope = at_origin[at_origin["in_scope"]]
        # The three populations named under the panel rather than folded into it: cargo
        # the plan cannot touch, cargo on a lane it chose not to touch, and cargo it moved
        # whose own dates will not support a comparison.
        at_origin_deltas = deltas[deltas["origin"].eq(origin)]
        left_alone = int((~at_origin_deltas["moved"]).sum())

        panels.append({
            "origin": _short(origin),
            "origin_full": str(origin),
            "shipments": int(len(g)),
            "unchanged": int((d == 0).sum()),
            "earlier": int((d < 0).sum()),
            "later": int((d > 0).sum()),
            "unchanged_pct": round(float((d == 0).sum()) / len(d), 4),
            "earlier_pct": round(float((d < 0).sum()) / len(d), 4),
            "later_pct": round(float((d > 0).sum()) / len(d), 4),
            "mean_delta": round(float(d.mean()), 2),
            "median_delta": float(d.median()),
            "worst_days": int(d.max()),
            "worst_site": str(worst_row.get("site", "")),
            "best_days": int(d.min()),
            "median_today": float(g["lead_time_today"].median()),
            "median_modelled": float(g["lead_time_modelled"].median()),
            "histogram": [{"days": int(k), "count": int(v)}
                          for k, v in d.value_counts().sort_index().items()],
            "buckets": _buckets(d, DELTA_BUCKETS),
            # Named rather than counted in: cargo the plan cannot touch, and cargo it
            # touches but whose own dates will not support a comparison.
            "origin_total": int(len(at_origin)),
            "cannot_move": int(len(at_origin) - len(in_scope)),
            "left_alone": left_alone,
            "unmeasurable": max(0, int(len(in_scope) - len(g) - left_alone)),
        })
    panels.sort(key=lambda p: -p["shipments"])
    return panels


def lane_risk(deltas, thin=THIN_LANE):
    """Where the later arrivals actually sit, lane by lane.

    The mean is the wrong instrument for this question: a plan that adds two days on
    average may be adding nothing on fifteen lanes and a fortnight on two, and only the
    second reading tells anyone what to do about it. So this counts each lane's own
    shipments, and reports the lanes that produce no late shipment at all as loudly as
    the ones that do.
    """
    if deltas is None or not len(deltas):
        return {"lanes": [], "measurable": 0}
    clean = deltas[deltas["measurable"] & deltas["moved"]]
    if not len(clean):
        return {"lanes": [], "measurable": 0}

    lanes = []
    for (origin, site), g in clean.groupby(["origin", "site"]):
        d = g["delta_days"].astype(int)
        late = d[d > 0]
        lanes.append({
            "origin": _short(origin),
            "origin_full": str(origin),
            "site": str(site),
            "shipments": int(len(g)),
            "late": int(len(late)),
            "late_share": round(float(len(late)) / len(g), 4),
            "worst_days": int(d.max()),
            "buckets": _buckets(d, LATE_BUCKETS),
            "thin": bool(len(g) < thin),
        })
    lanes.sort(key=lambda r: (-r["late_share"], -r["shipments"]))

    d_all = clean["delta_days"].astype(int)
    worst = max(lanes, key=lambda r: r["worst_days"])
    # Whether "it's a few bad lanes" is true, rather than assumed. It is the difference
    # between a problem somebody can be given to fix and a property of the network, and
    # on these files it comes out both ways.
    later_total = int((d_all > 0).sum())
    top = sorted(lanes, key=lambda r: -r["late"])[:3]
    top_late = sum(r["late"] for r in top) / max(1, later_total)
    # Against volume, not against nothing. Three lanes holding 61% of the lateness is not
    # concentration if they also carry 60% of the cargo -- that is lateness tracking size,
    # which is a different finding and answered by a different lever.
    top_volume = sum(r["shipments"] for r in top) / max(1, len(clean))
    return {
        "top_lanes_share": round(top_late, 4),
        "top_lanes_volume_share": round(top_volume, 4),
        "concentrated": bool(top_late >= 0.5 and top_late >= 1.25 * top_volume),
        "top_lanes": [f"{r['origin']} → {r['site']}" for r in top if r["late"]],
        "lanes": lanes,
        "measurable": int(len(clean)),
        "later": int((d_all > 0).sum()),
        "later_share": round(float((d_all > 0).sum()) / len(d_all), 4),
        "over_fortnight": int((d_all > 14).sum()),
        "lanes_total": len(lanes),
        "lanes_clean": sum(1 for r in lanes if r["late"] == 0),
        "worst_days": int(d_all.max()),
        "worst_lane": f"{worst['origin']} → {worst['site']}",
        "thin_lanes": [f"{r['origin']} → {r['site']} (n={r['shipments']})"
                       for r in lanes if r["thin"] and r["late"]],
        "thin_threshold": thin,
    }


def dwell_summary(containers, allocation, cfg, passthrough_containers=frozenset()):
    """How long cargo waits at the warehouse, against the cap that governs it.

    Measured per pallet as well as per container. The container figure says how long
    a box sat; the pallet figure says how long the client's cargo sat, and a
    container that waited two days for its last pallet may hold cargo that waited
    twelve.
    """
    con = pd.DataFrame(containers)
    alloc = pd.DataFrame(allocation)
    if con.empty:
        return {}
    # Boxes built at the warehouse only. Rejected lanes and unchanged single-shipment
    # boxes inside adopted lanes both bypass it, so averaging their zero dwell in would
    # report the warehouse holding cargo for less time than it really does.
    passthrough_containers = set(passthrough_containers or ())
    con = con[~con["container"].isin(passthrough_containers)]
    alloc = alloc[~alloc["container"].isin(passthrough_containers)]
    if con.empty:
        return {}
    waits = alloc["wait_days"]
    return {
        "container_dwell_mean": round(float(con["dwell_days"].mean()), 1),
        "container_dwell_median": float(con["dwell_days"].median()),
        "container_dwell_p95": float(con["dwell_days"].quantile(0.95)),
        "container_dwell_max": int(con["dwell_days"].max()),
        "pallet_wait_mean": round(float(waits.mean()), 1),
        "pallet_wait_median": float(waits.median()),
        "pallet_wait_p95": float(waits.quantile(0.95)),
        "pallet_wait_max": int(waits.max()),
        "dwell_cap": cfg["MAX_DWELL_DAYS"],
        "cap_breaches": int((con["dwell_days"] > cfg["MAX_DWELL_DAYS"]).sum()),
        "dispatch_reasons": con["dispatch_reason"].value_counts().to_dict(),
    }


def build(ship, containers, allocation, pal, cfg,
          passthrough_containers=frozenset()):
    """Sailings, per-shipment deltas and dwell, in one pass."""
    calendar = sailing_calendar(ship)
    actual = (ship.set_index("grp_key")[["act_depart", "act_arriv"]]
              .to_dict("index"))
    sailings = assign_sailings(
        containers, calendar, pal, cfg, actual=actual,
        passthrough_containers=passthrough_containers, allocation=allocation)
    deltas = shipment_deltas(ship, allocation, sailings)
    summary = summarise(deltas)
    summary.update({
        "container_dwell_mean": 0.0, "container_dwell_median": 0.0,
        "container_dwell_p95": 0.0, "container_dwell_max": 0,
        "pallet_wait_mean": 0.0, "pallet_wait_median": 0.0,
        "pallet_wait_p95": 0.0, "pallet_wait_max": 0,
        "dwell_cap": cfg["MAX_DWELL_DAYS"], "cap_breaches": 0,
        "dispatch_reasons": {},
    })
    summary.update(dwell_summary(
        containers, allocation, cfg, passthrough_containers=passthrough_containers))
    summary["containers_on_recorded_sailings"] = int(sailings["sailing_is_recorded"].sum())
    summary["containers_beyond_last_sailing"] = int((~sailings["sailing_is_recorded"]).sum())
    return sailings, deltas, summary
