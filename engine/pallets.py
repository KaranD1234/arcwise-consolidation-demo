"""Turn shipment groups into the smallest unit that can move independently.

A shipment group is a billing construct; a pallet is a physical thing. Containers
are built out of pallets, and a group may split between containers only at a whole
pallet, never mid-pallet. So the packer works on pallets, and everything downstream
attributes cost back up from them.

Volume and weight per pallet are computed for each group separately. Using one
global average across the file would move volume between groups that never shared
a container -- a group of dense castings would lend space to a group of light
mouldings and both would be costed wrong.
"""

import pandas as pd


def explode_pallets(ship):
    """One row per modelled pallet, at that group's own volume and weight.

    ``cfs_ready`` is the day the pallet is available at the consolidation
    warehouse, taken as its cargo-ready date. This is the model's most consequential
    timing assumption and it is deliberately the conservative one: cargo sits from
    the day it is ready until its box sails, so it accrues the maximum storage the
    plan could incur. Assuming instead that suppliers deliver just before the vessel
    -- which is what a mature operation would negotiate -- lowers storage cost and
    raises the saving. Modelling the favourable case and presenting it as the
    outcome is how a business case stops being believed.
    """
    rows = []
    for r in ship[ship["in_scope"]].to_dict("records"):
        pallets = int(r["pallets"])
        if pallets <= 0 or not pd.notna(r["cbm"]) or r["cbm"] <= 0:
            continue
        if pd.isna(r["cargo_ready"]):
            continue
        cbm_each = r["cbm"] / pallets
        gwt_each = r["gwt"] / pallets
        for k in range(pallets):
            rows.append({
                "pallet_id": f"{r['grp_key']}#{k + 1:04d}",
                "grp": r["grp_key"],
                "seq": k + 1,
                "cbm": cbm_each,
                "gwt": gwt_each,
                "cfs_ready": r["cargo_ready"],
                "cfs": r["cfs"],
                "pod": r["pod"],
                "site": r["site"],
                "site_country": r["site_country"],
                "shipper": r["shipper"],
                "term": r["term"],
                "pickup_region": r["pickup_region"],
            })
    pal = pd.DataFrame(rows)
    if pal.empty:
        return pal
    # Days from the first ready date in the file. The packer replays the history one
    # event day at a time, so it needs an integer day index, not a timestamp.
    pal["ready_day"] = (pal["cfs_ready"] - pal["cfs_ready"].min()).dt.days
    return pal
