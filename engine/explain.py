"""Plain-language explanations, rendered from the actual result.

Nothing here is canned. Every sentence is built from the numbers the run produced,
so an explanation cannot drift out of step with the figure it sits under, and it
cannot be wrong about a dataset it has never seen. The point is that a client can
click any number on the dashboard and get the arithmetic behind it in a sentence,
rather than being asked to trust it.
"""

import pandas as pd

import config as C


def saving(summary):
    """Why the total moved, pool by pool, including the cost consolidation adds."""
    today, future = summary["today"], summary["future"]
    if abs(summary["saving_usd"]) < 1:
        return (
            "The final plan makes no change to this file. Every destination-site lane "
            "either failed to reduce the physical box requirement or fell below the "
            "commercial adoption rule, so each was restored to today's containers and "
            "invoiced cost before the totals were calculated.\n\n"
            "The lane table still shows why each candidate was rejected; none of those "
            "candidate movements is included in the dashboard saving, container count or "
            "delivery impact.")
    moves = sorted(
        ((p, future[p] - today[p]) for p in C.COST_POOLS if abs(future[p] - today[p]) > 1),
        key=lambda t: t[1])
    down = [f"{p} falls ${abs(d):,.0f}" for p, d in moves if d < 0]
    up = [f"{p} rises ${d:,.0f}" for p, d in moves if d > 0]
    # The warehouse explanation belongs to the warehouse pool and to no other. Attaching
    # it to whatever happened to rise had it explaining a rise in destination delivery as
    # the cost of building containers at origin, which is a different thing entirely.
    new_work = any(p == "Origin CFS" for p, d in moves if d > 0)
    inbound = summary.get("inbound") or {}

    saved, boxes = summary["containers_saved"], summary["containers_future"]
    return (
        f"${summary['saving_usd']:,.0f} a year, {summary['saving_pct']:.1%} of the "
        f"${today['Total']:,.0f} this cargo costs today.\n\n"
        + (f"It comes from moving {saved} fewer containers — "
           f"{summary['containers_today']} down to {boxes} — by filling them to "
           f"{summary['mean_fill_cbm']} CBM instead of {summary['today_fill_cbm']}. "
           if saved > 0 else
           f"It does not come from moving fewer containers: the count goes from "
           f"{summary['containers_today']} to {boxes}. It comes from filling them to "
           f"{summary['mean_fill_cbm']} CBM instead of {summary['today_fill_cbm']}, "
           "and from cargo that rides LCL today booking a box of its own. ")
        + f"Cost per CBM shipped "
        + ("falls" if summary["cost_per_cbm_future"] < summary["cost_per_cbm_today"]
           else "rises")
        + f" from ${summary['cost_per_cbm_today']:,.2f} to "
          f"${summary['cost_per_cbm_future']:,.2f}.\n\n"
        + ("What falls: " + "; ".join(down) + ".\n\n" if down else "")
        + ("What rises: " + "; ".join(up) + "."
           + (" The origin CFS line is new: building containers at a warehouse is work "
              "nobody does today — receiving each inbound load, handling, drayage and "
              "storage are bills that do not exist now, and the saving is what is left "
              "after paying them."
              if new_work else "")
           + (f" Collection does not move with the container count and is not supposed "
              f"to: the same suppliers ship the same volume, so the same "
              f"{inbound['loads_today']:,} loads run whether or not the cargo is "
              "consolidated."
              if inbound.get("loads_today") and inbound.get("path") != "ftl" else "")
           + "\n\n" if up else "")
        + (f"{summary['passthrough_containers']} of the {boxes} containers are cargo "
           "the plan does not touch. They carry their own invoiced cost and contribute "
           "nothing to the saving"
           + (f", and {summary['declined_containers']} of those are on the "
              f"{summary['declined_lanes']} lanes the plan declined outright because "
              "consolidating them could not save a container."
              if summary.get("declined_lanes") else
              " — each one is a shipment that already filled its own boxes.")
           if summary["passthrough_containers"] else
           f"All {boxes} containers are built by the plan; none is carried across "
           "untouched."))


def container(container_row, allocation, sailings):
    """Why one container looks the way it does, including why it waited."""
    n = container_row["container"]
    mine = pd.DataFrame(allocation)
    mine = mine[mine["container"].eq(n)]
    sail = sailings[sailings["container"].eq(n)]

    reason = {
        "target_reached": "It reached the dispatch target and left.",
        "no_qualifying_arrival": ("It sailed short of target because no further cargo for this "
                                  "warehouse was due inside the waiting allowance. Holding it "
                                  "longer would have bought nothing."),
        "max_dwell_reached": ("It hit the maximum dwell and had to sail, full or not. The cap "
                              "is a service commitment, not an optimisation."),
        "end_of_history": ("It was still filling when the data ends, so it sails as it stands. "
                           "A live run would carry this cargo into the next period."),
    }.get(container_row["dispatch_reason"], "")

    lines = [
        f"{container_row['container_ref']} — {container_row['pallets']} pallets, "
        f"{container_row['cbm']:.1f} CBM ({container_row['fill_cbm_pct']:.0f}% of the volume "
        f"cap), {container_row['gwt']:,.0f} kg.",
        f"Built at {container_row['cfs']} from {container_row['groups']} shipment "
        f"{'group' if container_row['groups'] == 1 else 'groups'}, discharging at "
        f"{container_row['pod']} for {container_row['sites']}.",
    ]
    if container_row["dwell_days"] > 0:
        oldest = mine.loc[mine["wait_days"].idxmax()]
        lines.append(
            f"It waited {container_row['dwell_days']} days. The first pallet in it was ready "
            f"on {pd.Timestamp(oldest['cfs_ready']).date()} and the last arrived "
            f"{container_row['last_ready_day'] - container_row['first_ready_day']} days later, "
            "and a container cannot leave until all of its cargo is in it.")
    else:
        lines.append("Its cargo was all ready on the same day, so it waited for nothing.")
    if reason:
        lines.append(reason)
    if len(sail):
        s = sail.iloc[0]
        if pd.notna(s["modelled_sail"]):
            lines.append(
                f"It sails {pd.Timestamp(s['modelled_sail']).date()} and lands "
                f"{pd.Timestamp(s['modelled_arrive']).date()} — a departure this lane "
                "actually ran, carrying the transit it actually took.")
    return "\n\n".join(lines)


def lane(lane_row):
    """The verdict on one lane, and the arithmetic behind it."""
    v = lane_row["verdict"]
    head = {
        "Consolidate": "Worth doing.",
        "Marginal": "Worth doing only as part of the whole.",
        "Leave alone": "Leave this lane as it is.",
    }[v]
    return (
        f"{head}\n\n{lane_row['cfs']} to {lane_row['site']} via {lane_row['pod']}: "
        f"{int(lane_row['containers_today'])} containers today, "
        f"{int(lane_row['containers_future'])} modelled, "
        f"${lane_row['saving_usd']:,.0f} difference.\n\n{lane_row['why']}")


def derived_rate(rate_row):
    """How a rate with no card behind it was reconstructed."""
    if rate_row["source"] != "DERIVED_FROM_INVOICES":
        return (f"{rate_row['item']}: ${rate_row['rate_usd']:,.2f}. "
                f"{rate_row['derivation']}")
    return (
        f"{rate_row['item']}: ${rate_row['rate_usd']:,.2f} per container.\n\n"
        f"{rate_row['derivation']}\n\n"
        f"Across the {int(rate_row['population_groups'])} shipment groups that carried this "
        f"charge, the rate they actually paid ranged from ${rate_row['observed_min']:,.2f} to "
        f"${rate_row['observed_max']:,.2f}, with a median of "
        f"${rate_row['observed_median']:,.2f}. The figure used is the total divided by the "
        "containers, which is the weighted rate rather than the middle of the range.")


def lead_time(lt):
    """What the plan does to delivery dates, stated conservatively."""
    if not lt.get("measurable_shipments"):
        return ("No shipment had usable dates for a lead-time comparison. "
                f"{lt.get('excluded_shipments', 0)} groups were excluded for missing a "
                "cargo-ready, departure or delivery date, or for recording a departure "
                "before their own cargo was ready.")

    later, earlier = lt["later"], lt["earlier"]
    today_med, plan_med = lt["lead_time_today_median"], lt["lead_time_modelled_median"]
    return (
        (f"On average {lt['mean_delta_days_conservative']} days later per shipment, and "
         f"{lt['p95_delta_days_conservative']:.0f} days at the 95th percentile.\n\n"
         if lt["mean_delta_days_conservative"] else
         "No shipment is delivered later than it is today.\n\n")
        + f"Of {lt['measurable_shipments']} shipments with usable dates, "
          f"{lt['unaffected']} ({lt['unaffected_pct']:.0%}) are delivered on exactly the "
          "day they do now. "
        + (f"{later} arrive later — a median of {lt['later_median_days']:.0f} days, worst "
           f"case {lt['later_worst_days']} — which is the real price of waiting for a "
           "boxmate. " if later else "None arrives later. ")
        + (f"{earlier} arrive earlier.\n\n" if earlier else "None arrives earlier.\n\n")
        + (f"The headline counts those {earlier} as unchanged, not as a gain: the "
           "earlier vessel was always there to book, so curing that delay is not "
           "consolidation's to claim. Counting them the other way gives "
           f"{lt['mean_delta_days']} days.\n\n" if earlier else "")
        + ("Median door-to-door time is unchanged at "
           f"{today_med:.0f} days. " if today_med == plan_med else
           f"Median door-to-door time moves from {today_med:.0f} to {plan_med:.0f} days. ")
        + "Every date comes from a departure this cargo's lane actually ran; no transit "
          "time is assumed.")


def provenance(summary, rate_table):
    """Where the prices came from, in dollars rather than in counts."""
    p = summary["provenance"]
    # Counted only where there is something to count. Every clause used to be printed
    # whatever the number, so a file with nothing carded opened on "0 of the rates in this
    # model come from the client's own rate card" -- true, and a strange first sentence.
    counts = []
    if p["rates_from_card"]:
        counts.append(f"{p['rates_from_card']} rates come off your own rate card")
    if p["rates_derived"]:
        counts.append(f"{p['rates_derived']} were rebuilt from your own invoices \u2014 "
                      "what you paid, divided by what you moved")
    if p["rates_quoted"]:
        counts.append(f"{p['rates_quoted']} price the consolidation service, off your "
                      "forwarder's quote")
    if p["rates_assumed"]:
        counts.append(f"{p['rates_assumed']} stand on our benchmark")

    money = []
    if p["usd_from_card"]:
        money.append(f"${p['usd_from_card']:,.0f} priced from the card")
    if p["usd_derived"]:
        money.append(f"${p['usd_derived']:,.0f} from rates derived off the invoices")
    if p["usd_quoted"]:
        money.append(f"${p['usd_quoted']:,.0f} from the quote for the new service")
    if p["usd_actual_invoice"]:
        money.append(f"${p['usd_actual_invoice']:,.0f} carried across at invoiced cost "
                     "for cargo the plan does not change")

    parts = [p_ for p_ in ["; ".join(counts) + ". None is invented." if counts else "",
                           "In money: " + ", ".join(money) + "." if money else ""] if p_]

    if p["usd_assumed"] > 0:
        parts.append(
            f"${p['usd_assumed']:,.0f} \u2014 {p['assumed_share']:.1%} of the modelled "
            "total \u2014 rests on our benchmark, and is the one part of this answer you "
            "cannot check against your own records. A quote takes it to zero.")
    else:
        parts.append(
            f"{p['evidenced_share']:.1%} of the modelled cost is evidenced: every dollar "
            "traces to your rate card, your invoices, or a quote for the service being "
            "proposed. Nothing rests on a number we made up.")

    # Only where a quote actually priced something. It is an argument about the evidence
    # in front of the reader, and with no quoted rate in the model there is none to make.
    if p["rates_quoted"]:
        parts.append(
            "A quote is evidence of a different kind from an invoice, not an absence of "
            "it: the service has never been bought, so no invoice can price it, but a "
            "quote is a commercial commitment. Passing our own benchmark off as either "
            "would be indefensible.")
    return "\n\n".join(parts)
