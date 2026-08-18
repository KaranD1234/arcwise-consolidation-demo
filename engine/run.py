"""Run the whole model, reporting progress as it goes.

``run_streaming`` is a generator. It yields a ``Step`` after each stage completes,
carrying what that stage did and the findings it produced, and finally yields the
result. The interface consumes those events to narrate the build; a script can
ignore them and call ``run`` instead.

On the pacing: the engine's real work on a file this size finishes in about a
second. Each step is held to a floor of ``STEP_MIN_SECONDS`` so the build reads at
human speed rather than flashing past. That floor is presentational and changes no
number -- it is a deliberate choice about how the work is shown, not a claim about
how long it takes. Set ``step_min_seconds=0`` for tests and scripts.
"""

import time
from dataclasses import dataclass, field

import pandas as pd

import config as C
import costing
import ingest
import leadtime
import pack
import pallets
import rates
import reconcile
import resolve as resolve_mod
import sourcing


class MissingRates(Exception):
    """Raised when any leg the plan needs has no price. The model does not run.

    Excluding an unpriced leg and reporting the rest sounds like the modest option and is
    the dangerous one. The legs drop out of *today's* cost as well as tomorrow's, and not
    symmetrically: on one of our own datasets, a partial upload -- the consolidation quote
    without the freight card -- reported a saving of $1.67m against a true $434k, because
    most of what the client pays today had quietly left the comparison. Missing data made
    the answer look better, and only a control stood between that number and a client.

    So there is one rule, and it covers the consolidation service and every other leg
    alike: complete pricing, or no answer. What is missing is named, and the references
    step already asks for exactly those files.
    """

    def __init__(self, labels, service_only=False):
        self.labels = list(labels)
        self.service_only = service_only
        super().__init__(
            ("The consolidation service is not priced: " if service_only
             else "These legs have no price: ")
            + ", ".join(self.labels)
            + (". Upload your forwarder's consolidation quote, or enter the figures on "
               "the settings step." if service_only else
               ". Upload the rate cards that cover them on the references step."))


# The name this was introduced under, kept so callers outside the engine keep working.
MissingServiceQuote = MissingRates


def _service_states(pricing, card_index):
    """What actually priced each service figure, rather than what the caller asked for.

    An uploaded quote prices a rate whether or not the caller said anything about it, so
    reporting the caller's request had the workbook and the results screen describing
    four rates that came off the client's own quote as our benchmark.
    """
    pricing = pricing or {}
    codes = rates.service_codes()
    out = {}
    for key in C.SERVICE_RATE_KEYS:
        asked = pricing.get(key, C.SERVICE_PRICING_DEFAULT)
        on_quote = card_index.get(("CONSOLIDATION", "", "", codes.get(key, "")))
        out[key] = ("edited" if asked == "edited"
                    else "quoted" if on_quote else asked)
    return out


@dataclass
class Step:
    key: str
    title: str                      # the stage, as a heading
    detail: str                     # what it did, in one line
    applied: list = field(default_factory=list)   # constants this stage used
    findings: list = field(default_factory=list)  # what it noticed
    elapsed: float = 0.0


def _pace(started, floor):
    remaining = floor - (time.monotonic() - started)
    if remaining > 0:
        time.sleep(remaining)


def _applied(cfg, *keys):
    """Constants a stage used, phrased so the interface can read them out.

    Read from ``cfg`` rather than from CONFIG's defaults, because a reviewer may have
    changed any of them and the build has to narrate what it actually applied.
    """
    out = []
    for key in keys:
        meta = C.CONFIG[key]
        value = cfg[key]
        if str(meta["unit"]).startswith("of the"):
            shown = f"{value:.0%}"
        elif isinstance(value, float):
            shown = f"{value:,.2f}".rstrip("0").rstrip(".")
        elif isinstance(value, int):
            shown = f"{value:,}"
        else:
            shown = str(value)
        # A unit the label already says is a word doing nothing, and it produced
        # "Days from last pallet ready to sailing — 1 days" on the build ticker.
        unit = str(meta["unit"])
        if unit and unit.lower() in meta["label"].lower():
            unit = ""
        out.append({"label": meta["label"],
                    "value": f"{shown} {unit}".strip(),
                    "source": meta["source"]})
    return out


def _applied_pairs(cfg):
    """The paired caps and their dispatch targets, with the arithmetic spelled out."""
    return [{"label": C.CONFIG[p["pct"]]["label"],
             "value": C.describe_pair(cfg, p),
             "source": C.CONFIG[p["pct"]]["source"]}
            for p in C.LIMIT_PAIRS]


def run_streaming(charge_lines_path, rate_card=None, site_list=None,
                  overrides=None, answers=None, site_mapping=None,
                  supplier_mapping=None, service_pricing=None,
                  step_min_seconds=None):
    """Yield a Step per stage, then the finished result.

    ``answers`` maps a queue item's uid to the reviewer's choice. Passing
    ``site_mapping`` and ``supplier_mapping`` instead skips the review entirely,
    which is what a second run against the same client looks like.

    ``service_pricing`` maps each consolidation-service key to "quoted", "edited" or
    "benchmark". The consolidation service must be priced by the client one way or the
    other: a key left on "benchmark" with nothing on the quote to cover it raises
    ``MissingServiceQuote`` rather than being costed from a figure of ours.
    """
    floor = C.STEP_MIN_SECONDS if step_min_seconds is None else step_min_seconds
    cfg = C.values(overrides)

    # Service figures that are not rates -- the free storage period -- come off the quote
    # too, before anything reads the config.
    card_index_early = rates.index_rate_card(rate_card)
    cfg, parameter_gaps, quoted_parameters = rates.service_parameters(
        cfg, service_pricing, card_index_early)
    service_pricing = dict(service_pricing or {})
    for key in quoted_parameters:
        service_pricing[key] = "quoted"

    # --- read and clean --------------------------------------------------------
    t = time.monotonic()
    ingested = ingest.ingest(charge_lines_path)
    st = ingested.stats
    _pace(t, floor)
    yield Step("ingest", "Reading the charge lines",
               f"{st['charge_lines']:,} charge lines across {st['shipments']:,} shipments "
               f"in {st['shipment_groups']:,} groups, {st['date_range'][0]} to "
               f"{st['date_range'][1]}",
               findings=[f for f in ingested.findings if f.narrate])

    # --- scope -----------------------------------------------------------------
    t = time.monotonic()
    ship = ingested.shipments
    _pace(t, floor)
    yield Step("scope", "Deciding what can be consolidated",
               f"{st['in_scope_groups']:,} of {st['shipment_groups']:,} groups are ocean "
               f"cargo on EXW or FOB terms — {st['containers_today']:,} containers, "
               f"{st['in_scope_pallets']:,} pallets, {st['in_scope_cbm']:,.0f} CBM",
               findings=[f for f in ingested.findings if not f.narrate])

    # --- resolve ---------------------------------------------------------------
    t = time.monotonic()
    resolution = resolve_mod.resolve(ship, site_list=site_list,
                                     site_mapping=site_mapping,
                                     supplier_mapping=supplier_mapping)
    if answers:
        resolution = resolve_mod.apply_answers(resolution, answers)
    ship = resolve_mod.apply_resolution(ship, resolution)
    rs = resolution.stats
    _pace(t, floor)
    yield Step("resolve", "Resolving sites and suppliers",
               (f"{rs['mappings_total']} mappings reused from the last run"
                if rs.get("reused_prior_mappings") else
                f"{rs['auto_resolved']} of {rs['mappings_total']} mappings resolved "
                f"automatically, {rs['escalated']} needed a decision") +
               f" — {rs['delivery_strings']} delivery strings to {rs['sites_resolved']} sites")

    # --- pallets ---------------------------------------------------------------
    t = time.monotonic()
    pal = pallets.explode_pallets(ship)
    _pace(t, floor)
    yield Step("pallets", "Breaking cargo into pallets",
               f"{len(pal):,} pallets, each at its own group's volume and weight — "
               "never a file-wide average")

    # --- pack ------------------------------------------------------------------
    t = time.monotonic()
    boxes_today = {k: int(v) for k, v in
                   ship.loc[ship["in_scope"]]
                   .set_index("grp_key")["containers_today"].items()}
    raw_containers = pack.simulate(pal, cfg, boxes_today=boxes_today)
    containers, allocation = pack.assemble(raw_containers, cfg)
    kept = sum(1 for c in containers if c["consolidated"])
    declined_lanes = len({(c["cfs"], c["pod"], c["pool_third"]) for c in containers
                          if not c["consolidated"]})
    _pace(t, floor)
    yield Step("pack", "Building candidate containers day by day",
               f"{sum(c['counts_as_boxes'] for c in containers):,} candidate containers against "
               f"{st['containers_today']:,} the client moves today — {kept:,} built at the "
               f"warehouse"
               + (f", and {declined_lanes} lane{'s' if declined_lanes != 1 else ''} left "
                  "alone because packing could not reduce the box count"
                  if declined_lanes else ", every lane now goes to the commercial gate"),
               applied=(_applied(cfg, "OUT_CBM_MAX", "OUT_PALLET_MAX",
                                 "OUT_WEIGHT_MAX_KG")
                        + _applied_pairs(cfg)
                        + _applied(cfg, "MAX_DWELL_DAYS", "POOL_KEY")))

    # --- sourcing --------------------------------------------------------------
    #
    # Decided before any rate is built, because it governs what building a rate is even
    # allowed to do: whether a leg can be derived at all, whether the derivation is an
    # analogue, and which codes arrive bundled and so can price nothing.
    t = time.monotonic()
    plan = sourcing.plan(ingested.lines, ship,
                         rates.index_rate_card(rate_card),
                         service_pricing=service_pricing,
                         containers_today=int(st["containers_today"]),
                         pickups_today=int((ship["in_scope"] & ship["term"].eq("EXW")).sum()))
    sourcing_summary = sourcing.summarise(plan)
    _pace(t, floor)
    yield Step("sourcing", "Working out how each leg can be priced",
               f"{sourcing_summary['priced']} of {sourcing_summary['components']} cost "
               f"components have a price"
               + (f"; {len(sourcing_summary['unpriced'])} need a rate card"
                  if sourcing_summary["unpriced"] else ", none needing a rate card")
               + (f"; charge code{'s' if len(sourcing_summary['blocked_by_bundles']) > 1 else ''} "
                  f"{', '.join(sourcing_summary['blocked_by_bundles'])} arrive bundled and "
                  "can price nothing"
                  if sourcing_summary["blocked_by_bundles"] else ""))

    # --- rates -----------------------------------------------------------------
    t = time.monotonic()
    rate_table = rates.build_rates(ingested.lines, ship, containers, cfg,
                                   rate_card=rate_card,
                                   service_pricing=service_pricing,
                                   plan=plan)
    rt = rate_table.stats
    _pace(t, floor)
    yield Step("rates", "Establishing a price for every leg",
               f"{rt['from_card']} rates from the client's card, {rt['derived']} derived from "
               f"their own invoices, {rt['quoted']} from the forwarder's quote for the new "
               f"service, {rt['gaps']} legs unpriced — nothing invented",
               applied=_applied(cfg, *C.SERVICE_RATE_KEYS))

    # Stop here if anything the plan needs has no price. See the exception: excluding an
    # unpriced leg takes it out of today's cost too, which flatters the saving.
    gaps = rate_table.gaps + parameter_gaps
    if gaps:
        service = {g["key"] for g in gaps if g["category"] == "SERVICE"}
        if len(service) == len(gaps):
            raise MissingRates(
                (C.CONFIG[key]["label"] for key, spec in
                 list(rates.SERVICE_RATE_IDS.items())
                 + list(rates.SERVICE_PARAMETER_IDS.items())
                 if spec[1] in service or key in service),
                service_only=True)
        raise MissingRates(sorted({
            C.COMPONENTS_BY_KEY[g["component"]]["label"] if g.get("component")
            else f"{g['category'].replace('_', ' ').lower()} {g['key']}"
            for g in gaps}))

    # --- cost ------------------------------------------------------------------
    t = time.monotonic()
    # Packing fewer boxes is only the physical candidate. Cost it, apply the explicit
    # site-lane commercial rule, restore every failed lane to today's boxes, and cost the
    # smaller plan again. Removing a lane can change shared inbound and mixed-site costs,
    # so repeat until every lane still in the plan clears the rule. The set only grows;
    # this must converge in at most one pass per site lane.
    declined_site_lanes = set()
    rejected_lane_findings = {}
    while True:
        passthrough_groups, passthrough_containers = costing.find_passthrough_groups(
            ship, allocation, containers)
        moved = [r for r in allocation if r["container"] not in passthrough_containers]
        trucks = pack.plan_inbound_trucks(moved, cfg)
        solo = pack.plan_inbound_trucks(moved, cfg, pooled=False)
        inbound = costing.choose_inbound(
            ship, allocation, trucks, solo, rate_table, cfg, passthrough_containers,
            card_index=card_index_early)
        con_costed, ledger = costing.cost_containers(
            containers, allocation, ship, rate_table, cfg, passthrough_containers, inbound)
        candidate_lanes = costing.lane_verdicts(ship, con_costed, allocation, cfg)
        failed = candidate_lanes[
            candidate_lanes["consolidated"]
            & candidate_lanes["verdict"].eq("Leave alone")]
        newly_failed = {
            (row["cfs"], row["pod"], row["site"])
            for _, row in failed.iterrows()
        } - declined_site_lanes
        if not newly_failed:
            break
        for _, row in failed.iterrows():
            key = (row["cfs"], row["pod"], row["site"])
            if key in newly_failed:
                rejected_lane_findings[key] = {
                    "saving_usd": float(row["saving_usd"]),
                    "saving_pct": float(row["saving_pct"]),
                    "containers_saved": float(row["containers_saved"]),
                }
        declined_site_lanes |= newly_failed
        raw_containers = pack.simulate(
            pal, cfg, boxes_today=boxes_today,
            declined_site_lanes=frozenset(declined_site_lanes))
        containers, allocation = pack.assemble(raw_containers, cfg)

    summary = costing.summarise(ship, con_costed, ledger, rate_table, inbound, cfg)
    lanes = costing.lane_verdicts(
        ship, con_costed, allocation, cfg, rejected=rejected_lane_findings)
    # Summary lane counts use the same origin–port–site grain the dashboard shows. A
    # country pool is an operating choice, not permission to collapse different final
    # delivery legs into one reported lane.
    summary["consolidated_lanes"] = int(lanes["verdict"].eq("Consolidate").sum())
    summary["declined_lanes"] = int(lanes["verdict"].eq("Leave alone").sum())
    _pace(t, floor)
    yield Step("cost", "Costing the plan",
               f"{summary['ledger_rows']:,} ledger rows — "
               f"${summary['today']['Total']:,.0f} today against "
               f"${summary['future']['Total']:,.0f} modelled, a "
               f"${summary['saving_usd']:,.0f} difference "
               f"({summary['saving_pct']:.1%}). {len(passthrough_containers)} containers are "
               "cargo the plan does not change and are costed at their own invoices"
               + (f"; {len(declined_site_lanes)} site lane"
                  f"{'s' if len(declined_site_lanes) != 1 else ''} failed the commercial "
                  "rule and were restored to today" if declined_site_lanes else "")
               + (f"; the inbound leg is bought as {inbound['trucks']:,} trailer loads "
                  f"instead of {inbound['loads_today']:,} separate collections"
                  if inbound.get("path") == "ftl" else ""),
               applied=_applied(cfg, "LANE_MIN_SAVING_USD", "LANE_MIN_SAVING_PCT"))

    # --- lead time -------------------------------------------------------------
    t = time.monotonic()
    sailings, deltas, lt = leadtime.build(
        ship, containers, allocation, pal, cfg,
        passthrough_containers=passthrough_containers)
    # The same deltas cut two more ways, because a network mean answers nobody's
    # question: by origin, which is the unit an operations person owns, and by
    # destination lane, which is where a delay is actually managed.
    lt_origins = leadtime.origin_panels(ship, deltas)
    lt_risk = leadtime.lane_risk(deltas)
    _pace(t, floor)
    yield Step("leadtime", "Measuring the service impact",
               f"{lt.get('unaffected', 0)} of {lt.get('measurable_shipments', 0)} shipments "
               f"arrive on the day they do today; average "
               f"{lt.get('mean_delta_days_conservative', 0)} days later per shipment, worst "
               f"{lt.get('later_worst_days', 0)} days",
               applied=_applied(cfg, "CFS_TO_VESSEL_DAYS"))

    # --- controls --------------------------------------------------------------
    t = time.monotonic()
    controls = reconcile.run_controls(ingested, ship, pal, containers, allocation,
                                     con_costed, ledger, rate_table, resolution,
                                     summary, lanes, cfg)
    controls_summary = reconcile.summarise(controls)
    _pace(t, floor)
    yield Step("controls", "Running the controls",
               f"{controls_summary['controls_passed']} of "
               f"{controls_summary['controls_total']} passed"
               + ("" if controls_summary["all_passed"]
                  else " — FAILED: " + ", ".join(controls_summary["failures"])),
               findings=[])

    yield {
        "shipments": ship,
        "lines": ingested.lines,
        "findings": ingested.findings,
        "ingest_stats": st,
        "resolution": resolution,
        "queue": resolution.queue,
        "pallets": pal,
        "containers": containers,
        "allocation": allocation,
        "containers_costed": con_costed,
        "ledger": ledger,
        "rates": rate_table.rows,
        "rate_table": rate_table,
        "summary": summary,
        "lanes": lanes,
        "inbound": inbound,
        "inbound_trucks": trucks,
        "inbound_loads_today": solo,
        "sailings": sailings,
        "deltas": deltas,
        "lead_time": lt,
        "lead_time_origins": lt_origins,
        "lead_time_risk": lt_risk,
        "controls": controls,
        "controls_frame": reconcile.to_frame(controls),
        "controls_summary": controls_summary,
        "config_used": cfg,
        "service_pricing": _service_states(service_pricing, card_index_early),
        "sourcing": plan,
        "sourcing_summary": sourcing_summary,
        "passthrough_groups": passthrough_groups,
    }


def run(charge_lines_path, **kwargs):
    """Run without pacing and return the result. Steps are discarded."""
    kwargs.setdefault("step_min_seconds", 0.0)
    result = None
    for event in run_streaming(charge_lines_path, **kwargs):
        result = event
    return result


def preview_queue(charge_lines_path, rate_card=None, site_list=None):
    """Ingest and resolve only, so the review queue can be shown before the build.

    The interface needs the queue before it runs anything, and this is the cheap
    path to it: read, scope, resolve, stop.
    """
    ingested = ingest.ingest(charge_lines_path)
    resolution = resolve_mod.resolve(ingested.shipments, site_list=site_list)
    return ingested, resolution
