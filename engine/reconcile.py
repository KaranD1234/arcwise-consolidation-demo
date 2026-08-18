"""Controls that have to pass before any number here is shown to anyone.

These are not unit tests. They are the checks that make the output defensible in a
room where somebody is trying to find the hole in it, and each one exists because
failing it silently would produce a plausible answer that is wrong.

The most important is ``rate model reproduces the baseline``. Applied to the
containers the client actually moved, the engine's rate table must land on the
client's actual invoiced cost. If it does not, the modelled saving is measuring the
gap between our rates and their rates rather than the effect of consolidation, and
the whole result is worthless however well it reconciles elsewhere. A saving
produced by quietly cheaper rates is the failure mode this catches.

Any control failing is a hard stop. A demo that shows a number a control rejected is
worse than a demo that shows nothing.
"""

from dataclasses import dataclass

import pandas as pd

import config as C
import costing as costing_mod
import rates as R


@dataclass
class Control:
    """One check the model must satisfy before a number leaves the screen.

    ``kind`` separates two very different failures, because they call for different
    things from whoever is reading:

    ``integrity``  our arithmetic is wrong. Nothing here depends on the client's data
                   being good, so a failure is our bug and the figures must not be used.
    ``fit``        the model does not reproduce *this file* closely enough. That is a
                   statement about the data, not about the code, and it is answerable —
                   usually by a rate card that covers whatever is drifting.

    A failing control shows its ``remedy``. A red banner naming a check and stopping
    there tells a reader that something broke without telling them what to do about it,
    which is the worst of both: alarming and useless.
    """
    name: str
    passed: bool
    detail: str
    tolerance: str = ""
    kind: str = "integrity"
    remedy: str = ""

    @property
    def status(self):
        return "PASS" if self.passed else "FAIL"


def _close(a, b, tol):
    return abs(float(a) - float(b)) <= tol


def charge_code_control(lines):
    """A result cannot be usable while any invoiced code lacks a classification."""
    unknown = lines[lines["code_unrecognised"]]
    return Control(
        "Every charge code is classified in the register",
        len(unknown) == 0,
        (f"{int(unknown['code'].nunique())} codes not in the register, on "
         f"{len(unknown)} lines worth ${float(unknown['line_usd'].sum()):,.2f}. Their "
         "dollars remain in the reconciliation, but the result is blocked until each "
         "code has a cost-pool assignment."
         if len(unknown) else "Every charge code was recognised and classified."),
        "zero unclassified codes")


def run_controls(ingested, ship, pal, containers, allocation, con_costed, ledger,
                 rate_table, resolution, summary, lanes, cfg):
    """Every control, in the order a reader would want to check them."""
    controls = []
    lines = ingested.lines

    # --- 1. no dollars lost between the raw file and the pools ----------------
    raw_total = float(lines["line_usd"].sum())
    pooled_total = float(ship[C.COST_POOLS].sum().sum())
    controls.append(Control(
        "Every invoiced dollar reaches a cost pool",
        _close(raw_total, pooled_total, 0.05),
        f"${raw_total:,.2f} of charge lines against ${pooled_total:,.2f} across the "
        f"{len(C.COST_POOLS)} pools. A charge that fell out here would be a charge the "
        "client pays and the model never sees.",
        "within $0.05"))

    # --- 2. the invoices agree with their own charges -------------------------
    declared = ingested.stats["declared_invoice_total_usd"]
    controls.append(Control(
        "Charge lines sum to the invoice totals the file declares",
        _close(raw_total, declared, 1.0),
        f"${raw_total:,.2f} of charges against ${declared:,.2f} declared on the invoices. "
        "This is what proves the '-related-' marker was read correctly rather than "
        "filled down.",
        "within $1.00"))

    # --- 3. cargo is conserved through the packer ----------------------------
    alloc = pd.DataFrame(allocation)
    controls.append(Control(
        "Every pallet is in exactly one container",
        len(alloc) == len(pal) and int(alloc["pallet_id"].nunique()) == len(pal),
        f"{len(pal):,} pallets exploded, {len(alloc):,} allocated, "
        f"{int(alloc['pallet_id'].nunique()):,} distinct. Cargo cannot be duplicated into "
        "a saving or dropped out of a cost.",
        "exact"))

    cbm_in = float(pal["cbm"].sum())
    cbm_out = float(alloc["cbm"].sum())
    controls.append(Control(
        "Volume is conserved through the packer",
        _close(cbm_in, cbm_out, 0.5),
        f"{cbm_in:,.1f} CBM in, {cbm_out:,.1f} CBM out.",
        "within 0.5 CBM"))

    # --- 4. no container breaches a physical limit ---------------------------
    #
    # Checked on the boxes the model builds, and only those. A lane the plan declined
    # keeps the boxes the client already books -- 20ft, 40ft and 45ft among them, on their
    # own equipment lines -- and holding somebody else's 45ft box to our 40'HC cap would
    # fail a control on cargo the model never touched.
    con_all = pd.DataFrame(containers)
    changed_ids = set(con_costed.loc[~con_costed["passthrough"], "container"])
    con = con_all[con_all["container"].isin(changed_ids)]
    over = con[(con["cbm"] > cfg["OUT_CBM_MAX"] + 1e-6)
               | (con["pallets"] > cfg["OUT_PALLET_MAX"])
               | (con["gwt"] > cfg["OUT_WEIGHT_MAX_KG"] + 1e-6)]
    controls.append(Control(
        "No container the model builds exceeds volume, pallet or weight limits",
        len(over) == 0,
        f"{len(con):,} of {len(con_all):,} containers are built by the model and are "
        f"checked against {cfg['OUT_CBM_MAX']} CBM, {cfg['OUT_PALLET_MAX']} pallets and "
        f"{cfg['OUT_WEIGHT_MAX_KG']:,.0f} kg. {len(over)} breaches. The remaining "
        f"{len(con_all) - len(con):,} ship as they ship today, in the client's own "
        "equipment.",
        "zero breaches"))

    # --- 5. the dwell cap holds ----------------------------------------------
    breaches = int((con["dwell_days"] > cfg["MAX_DWELL_DAYS"]).sum()) if len(con) else 0
    controls.append(Control(
        "No cargo waits longer than the dwell cap",
        breaches == 0,
        (f"Longest container dwell is {int(con['dwell_days'].max())} days against a "
         f"{cfg['MAX_DWELL_DAYS']}-day cap. {breaches} breaches." if len(con)
         else "No container is built at the warehouse on this file, so nothing waits."),
        "zero breaches"))

    # --- 6. every in-scope group is modelled ---------------------------------
    in_scope_groups = set(ship.loc[ship["in_scope"], "grp_key"])
    allocated = set(alloc["grp"])
    missing = in_scope_groups - allocated
    controls.append(Control(
        "Every in-scope shipment group appears in the plan",
        len(missing) == 0,
        f"{len(in_scope_groups):,} in-scope groups, {len(allocated):,} allocated, "
        f"{len(missing)} unaccounted for. An in-scope group left out would understate "
        "the cost of the plan.",
        "zero missing"))

    # --- 7. the ledger is the modelled total ---------------------------------
    ledger_total = float(ledger["usd"].sum())
    controls.append(Control(
        "The ledger sums to the modelled cost",
        _close(ledger_total, summary["future"]["Total"], 0.50),
        f"{len(ledger):,} ledger rows totalling ${ledger_total:,.2f} against a modelled "
        f"${summary['future']['Total']:,.2f}. Every dollar in the answer is one row "
        "tagged to a container and a rate.",
        "within $0.50"))

    # --- 8. the lane decision table is the adopted plan ----------------------
    # These checks sit in the runtime controls, not only the rehearsal suite. A UI table
    # that collapsed mixed sites or printed rejected candidate savings would otherwise be
    # able to disagree with a perfectly reconciled headline.
    expected_lanes = int(
        ship.loc[ship["in_scope"]].groupby(["cfs", "pod", "site"]).ngroups)
    lane_keys = lanes[["cfs", "pod", "site"]]
    controls.append(Control(
        "Every final-delivery lane appears exactly once",
        len(lanes) == expected_lanes and not lane_keys.duplicated().any(),
        f"{expected_lanes} origin–port–site lanes in the data and {len(lanes)} unique "
        "rows in the result. Sites remain separate even when they share a container.",
        "exact"))
    controls.append(Control(
        "Lane rows reconcile to the final box count and saving",
        _close(lanes["containers_future"].sum(), summary["containers_future"], 0.05)
        and _close(lanes["saving_usd"].sum(), summary["saving_usd"], 1.0),
        f"{lanes['containers_future'].sum():,.2f} allocated box-equivalents against "
        f"{summary['containers_future']:,} physical boxes; ${lanes['saving_usd'].sum():,.2f} "
        f"lane saving against ${summary['saving_usd']:,.2f} total.",
        "within 0.05 boxes and $1"))
    adopted = lanes[lanes["verdict"].eq("Consolidate")]
    rejected = lanes[lanes["verdict"].eq("Leave alone")]
    controls.append(Control(
        "Every adopted lane clears the commercial rule",
        all(costing_mod.lane_clears_rule(row, cfg) for _, row in adopted.iterrows()),
        f"{len(adopted)} adopted lanes tested against more than "
        f"${cfg['LANE_MIN_SAVING_USD']:,.0f} a year or "
        f"{cfg['LANE_MIN_SAVING_PCT']:.0%} of current lane cost.",
        "every adopted lane"))
    controls.append(Control(
        "Every rejected lane is unchanged in the final plan",
        bool((rejected["containers_saved"].abs() < 0.01).all()
             and (rejected["saving_usd"].abs() < 0.01).all()),
        f"{len(rejected)} rejected lanes; "
        f"{int((rejected['containers_saved'].abs() >= 0.01).sum())} change box count and "
        f"{int((rejected['saving_usd'].abs() >= 0.01).sum())} change cost.",
        "zero change"))

    # --- 9. no rate was invented --------------------------------------------
    sources = set(rate_table.rows["source"].unique())
    controls.append(Control(
        "No rate is invented",
        sources <= R.VALID_SOURCES and rate_table.stats["gaps"] == 0,
        f"{rate_table.stats['from_card']} rates from your card, "
        f"{rate_table.stats['derived']} derived from your invoices, "
        f"{rate_table.stats['quoted']} from your forwarder's quote, "
        f"{rate_table.stats['assumed']} on our benchmark, "
        f"{rate_table.stats['gaps']} legs unpriced.",
        "no other source, no gaps"))

    derived = rate_table.rows[rate_table.rows["source"].eq(R.DERIVED)]
    unbacked = derived[derived["population_invoices"].le(0)]
    controls.append(Control(
        "Every derived rate traces to at least one invoice",
        len(unbacked) == 0,
        f"{len(derived)} derived rates built from "
        f"{int(derived['population_invoices'].sum()):,} invoices. {len(unbacked)} rates "
        "with no invoice behind them.",
        "zero unbacked"))

    # --- 10. THE calibration control -----------------------------------------
    modelled_baseline = _price_history(ship, rate_table)
    actual_baseline = float(ship.loc[ship["in_scope"] & ship["is_fcl"], "invoiced_usd"].sum())
    gap = (modelled_baseline - actual_baseline) / actual_baseline if actual_baseline else 0.0
    controls.append(Control(
        "The rate model reproduces what you actually paid",
        abs(gap) <= 0.03,
        f"Priced against the {int(ship.loc[ship['in_scope'] & ship['is_fcl'], 'containers_today'].sum()):,} "
        f"containers you actually moved, the rate table gives "
        f"${modelled_baseline:,.0f} against ${actual_baseline:,.0f} invoiced — "
        + ("0.00%" if abs(gap) < 5e-5 else f"{gap:+.2%}")
        + ". This is the control that matters: it shows the saving comes from "
        "moving fewer containers, not from cheaper rates.",
        "within 3%",
        kind="fit",
        remedy="The rate table does not yet reproduce this file to 3%. That is a "
               "statement about the data rather than the arithmetic: usually a charge "
               "the rate card does not cover, or a code arriving bundled. Until it "
               "closes, the difference between the two states is measuring our "
               "reconstruction of your rates as much as the effect of consolidating."))

    # --- 11. every judgement is recorded -------------------------------------
    sites, sups = resolution.sites, resolution.suppliers
    no_evidence = 0
    if len(sites):
        no_evidence += int(sites["Note"].fillna("").str.strip().eq("").sum())
    if len(sups):
        no_evidence += int(sups["Evidence"].fillna("").str.strip().eq("").sum())
    controls.append(Control(
        "Every resolved mapping records its evidence",
        no_evidence == 0,
        f"{len(sites)} delivery strings and {len(sups)} suppliers resolved, "
        f"{no_evidence} without a recorded reason.",
        "zero unexplained"))

    # --- 12. every charge code is classified ----------------------------------
    # Keeping unknown dollars is better than dropping them, but it is not enough to make
    # a result usable: without a pool the future side cannot know which operation and
    # unit to price. Seeded demos contain none; a real upload with one fails this control
    # and the results page marks the figures unusable until the register is extended.
    controls.append(charge_code_control(lines))

    return controls


def _price_history(ship, rate_table):
    """Price the containers the client actually moved, using the engine's rates.

    The warehouse step is deliberately absent: it does not exist in the history, so
    including it would guarantee a mismatch and destroy the only check that tells us
    whether the rate table is calibrated.
    """
    e = ship[ship["in_scope"] & ship["is_fcl"]]
    other = rate_table.rows[rate_table.rows["category"].eq("OTHER")]
    other_per_container = float(other["rate_usd"].sum())

    total = 0.0
    for g in e.to_dict("records"):
        n = int(g["containers_today"])
        if n <= 0:
            continue
        total += n * rate_table.rate_of("OCEAN", (g["cfs"], g["pod"]))
        total += n * rate_table.rate_of("DEST_DELIVERY", (g["pod"], g["site"]))
        if g["term"] == "EXW":
            for code in C.EXW_COMPONENT_CODES:
                total += n * rate_table.rate_of(
                    "ORIGIN_COMPONENT", (g["pickup_region"], code))
        total += n * other_per_container
    return total


def summarise(controls):
    passed = sum(1 for c in controls if c.passed)
    failed = [c for c in controls if not c.passed]
    return {
        "controls_total": len(controls),
        "controls_passed": passed,
        "controls_failed": len(controls) - passed,
        "all_passed": passed == len(controls),
        "failures": [c.name for c in failed],
        # Carried in full so the interface can say what a failure means and what to do
        # about it, instead of printing the name of a check nobody has seen before.
        "failed": [{"name": c.name, "kind": c.kind, "detail": c.detail,
                    "tolerance": c.tolerance, "remedy": c.remedy} for c in failed],
        "integrity_failed": [c.name for c in failed if c.kind == "integrity"],
    }


def to_frame(controls):
    return pd.DataFrame([{
        "Control": c.name, "Result": c.status,
        "Tolerance": c.tolerance, "Detail": c.detail,
    } for c in controls])
