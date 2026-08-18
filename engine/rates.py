"""Establish a price for every leg the model needs, and say where each price came from.

This is the part of the engine the whole business case rests on. A consolidation
saving is a comparison between what the client pays now and what they would pay
under a plan, so if the prices in the plan are invented the saving is fiction. The
rule here is that no rate is ever invented, and every rate says which of exactly
three things it is:

    CLIENT_RATE_CARD        the client's own card prices this lane. Used as given.
    DERIVED_FROM_INVOICES   the card does not cover it, so the rate is
                            reverse-engineered from the client's own charge lines:
                            what they actually paid, divided by what they actually
                            moved. Published with its formula, its population and
                            the observed spread around it.
    CLIENT_ASSUMPTION       consolidation introduces a step that has never happened,
                            so no invoice anywhere can price it. Declared on the
                            assumptions card, and every dollar it touches is
                            counted so the client knows how much of the answer
                            rests on it.

Precedence is card, then derived, then assumption. A client's contracted rate always
beats our reconstruction of it.

The most important detail in this file is narrow: the destination delivery rate is
built from charge code 1638 and nothing else. Several other codes sit in the same
cost pool and look like delivery charges -- code 1411's description is literally
"Destination DAP charges" -- but they price different work. Letting any of them in
would inflate every modelled delivery and the error would be invisible.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config as C
import resolve
import sourcing

CARD = "CLIENT_RATE_CARD"
DERIVED = "DERIVED_FROM_INVOICES"
QUOTED = "QUOTED_NOT_YET_BOUGHT"
ASSUMED = "CLIENT_ASSUMPTION"

# Every source a rate may legitimately have. Anything outside this set is a bug, and
# reconcile.py fails the run rather than costing it.
VALID_SOURCES = frozenset({CARD, DERIVED, QUOTED, ASSUMED})


@dataclass
class RateTable:
    rows: pd.DataFrame
    index: dict = field(default_factory=dict)     # (category, key) -> rate row dict
    stats: dict = field(default_factory=dict)
    gaps: list = field(default_factory=list)

    # Keys are tuples for lane rates and bare strings for flat ones, so they are
    # stringified on both sides of the lookup rather than relying on the caller to
    # remember which is which.
    def get(self, category, key):
        return self.index.get((category, str(key)))

    def rate_of(self, category, key, default=0.0):
        row = self.get(category, key)
        return float(row["rate_usd"]) if row else default

    def source_of(self, category, key, default=""):
        row = self.get(category, key)
        return row["source"] if row else default


def _row(rate_id, category, key, item, rate_usd, source, confidence, derivation,
         code="", basis="Per Container", node_from="", node_to="", **audit):
    row = {
        "rate_id": rate_id, "category": category, "key": str(key), "item": item,
        "rate_usd": round(float(rate_usd), 2), "basis": basis,
        "node_from": node_from, "node_to": node_to, "charge_code": code,
        "source": source, "confidence": confidence, "derivation": derivation,
        "component": "",
        "population_invoices": 0, "population_groups": 0, "population_containers": 0,
        "observed_min": np.nan, "observed_median": np.nan, "observed_max": np.nan,
        "invoice_total_usd": np.nan,
    }
    row.update(audit)
    return row


# --------------------------------------------------------------------------------------
# The client's card
# --------------------------------------------------------------------------------------
def _place(value):
    """``Corby, UK``, ``Corby`` and ``corby`` all index the same place.

    A rate card names sites the way the client's commercial team writes them and the
    operations file names them the way the warehouse does, and the two are never the
    same string. Matching them character for character means a lane the client has
    carded reads as unpriced, which stops the run -- correctly, on a rate that is
    sitting in the file.
    """
    return resolve.city_of(value)


class CardIndex(dict):
    """The card, keyed exactly, with a fallback on the place names normalised.

    A subclass rather than a second dict because everything downstream iterates the
    exact keys -- the references board counts them -- and only lookups should be
    forgiving.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aliases = {}

    def get(self, key, default=None):
        hit = super().get(key)
        if hit is not None:
            return hit
        if not isinstance(key, tuple) or len(key) != 4:
            return default
        category, node_from, node_to, code = key
        wanted = (category, _place(node_from), _place(node_to), code)
        hit = self.aliases.get(wanted)
        if hit is not None:
            return hit
        # Last resort, and the one that earns its keep on real files: the same charge on
        # the same lane, with a town spelled differently at each end. A commercial team
        # writes "Lübeck" and the operations export writes "Luebeck", and refusing to see
        # those as one lane leaves a rate the client has carded sitting unused while the
        # engine reconstructs it from invoices.
        for candidate, entry in self.aliases.items():
            if candidate[0] != category or candidate[3] != code:
                continue
            if all(resolve.city_similarity(a, b) >= C.RESOLVE["AUTO_MATCH_RATIO"]
                   for a, b in ((candidate[1], wanted[1]), (candidate[2], wanted[2]))):
                return entry
        return default

    def __contains__(self, key):
        return super().__contains__(key) or self.get(key) is not None


def index_rate_card(card):
    """Index an uploaded rate card by what it prices.

    Nothing is assumed about completeness. A card that covers six lanes of eight is
    the normal case, and the two it misses are the interesting ones.
    """
    if card is None or not len(card):
        return CardIndex()
    needed = {"Rate", "Currency", "Ch_Code", "Node_From", "Node_To", "Category"}
    missing = needed - set(card.columns)
    if missing:
        raise ValueError(f"rate card is missing columns: {sorted(missing)}")

    def text(value):
        """A card cell as a string, with an empty cell meaning empty.

        ``str()`` on a missing cell yields the literal "nan", and a key built from that
        matches nothing. It is a silent failure in the worst place: a rate the client
        supplied is quietly ignored and the engine derives or assumes one instead, while
        every screen still reports the card as covering the leg. Blank is the normal
        state for any rate that is not lane-specific -- the whole service quote, and
        every miscellaneous charge -- so this is most of a card, not an edge case.
        """
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        return str(value).strip()

    out = CardIndex()
    for r in card.to_dict("records"):
        fx = C.REPORTING_FX_TO_USD.get(text(r.get("Currency", "USD")) or "USD", 1.0)
        usd = pd.to_numeric(pd.Series([r["Rate"]]), errors="coerce").iloc[0]
        if pd.isna(usd):
            continue
        entry = {
            "rate_usd": float(usd) * fx,
            "rate_id": text(r.get("Rate_ID", "")),
            "item": text(r.get("Item", "")),
            "basis": text(r.get("Rate_Basis", "")) or "Per Container",
        }
        key = (text(r["Category"]), text(r["Node_From"]),
               text(r["Node_To"]), text(r["Ch_Code"]))
        out[key] = entry
        out.aliases.setdefault(
            (key[0], _place(key[1]), _place(key[2]), key[3]), entry)
    return out


def card_coverage(card_index, needs):
    """How much of what the model needs the client's card actually prices."""
    priced = sum(1 for n in needs if n in card_index)
    return {"needed": len(needs), "priced_by_card": priced,
            "to_derive": len(needs) - priced}


# --------------------------------------------------------------------------------------
# Derivation from the client's own invoices
# --------------------------------------------------------------------------------------
def _per_container_population(lines, ship, code, group_filter=None, fleet_wide=False):
    """Charges of one code, and the containers they were charged against.

    Returns per shipment group: the code's total, the group's rebuilt container
    count, and the implied per-container rate. That last column is what produces
    the observed spread -- a single derived figure with no spread behind it is
    indistinguishable from a number somebody typed.

    ``fleet_wide`` decides the denominator, and getting it wrong is the easiest way
    to build a badly wrong model.

      False -- divide by the containers of the groups that actually carried the
               charge. Right for a charge every container incurs exactly once:
               ocean freight, destination delivery, the origin component set.
      True  -- divide by every container in the population, including those that
               never carried the charge. Right for the miscellaneous charges that
               land on only some invoices. A documentation fee billed on a quarter
               of shipments has a real per-container cost of a quarter of its face
               value, and charging the face value to every modelled container would
               invent cost that no invoice supports.
    """
    base = ship[ship["in_scope"] & ship["is_fcl"] & ship["containers_today"].gt(0)]
    if group_filter is not None:
        base = base[group_filter(base)]
    if base.empty:
        return base.assign(code_usd=0.0, code_invoices=0, per_container=0.0), 0

    coded = lines[lines["code"].eq(code)]
    totals = coded.groupby("grp_key")["line_usd"].sum()
    invoices = coded.groupby("grp_key")["Sales Invoice #"].nunique()

    pop = base.copy()
    pop["code_usd"] = pop["grp_key"].map(totals).fillna(0.0)
    pop["code_invoices"] = pop["grp_key"].map(invoices).fillna(0).astype(int)
    pop["charged"] = pop["code_usd"] > 0
    if not pop["charged"].any():
        return pop.iloc[0:0].assign(per_container=0.0), 0
    if not fleet_wide:
        pop = pop[pop["charged"]]
    pop["per_container"] = pop["code_usd"] / pop["containers_today"]
    return pop, int(pop["code_invoices"].sum())


def _derived_row(rate_id, category, key, item, pop, code, node_from, node_to, note="",
                 fleet_wide=False, basis="Per Container"):
    units = int(pop["containers_today"].sum())
    total = float(pop["code_usd"].sum())
    rate = total / units
    charged = pop[pop["charged"]] if "charged" in pop.columns else pop

    if fleet_wide:
        incidence = len(charged) / len(pop) if len(pop) else 0.0
        how = (f"${total:,.2f} of charge code {code}, divided by all {units} containers "
               f"in the period. The charge appears on {len(charged)} of {len(pop)} shipment "
               f"groups ({incidence:.0%}), so the per-container figure carries that incidence "
               "rather than the face value of a single charge.")
    else:
        how = (f"${total:,.2f} of charge code {code} across {len(pop)} shipment groups, "
               f"divided by the {units} containers those groups moved. "
               "No other charge code enters this rate.")

    # The spread is always measured across invoices that carried the charge. A
    # spread that included un-charged shipments would report a minimum of zero for
    # every code and say nothing.
    return _row(
        rate_id, category, key, item, rate, DERIVED, "MEDIUM",
        derivation=how + (f" {note}" if note else ""),
        code=code, node_from=node_from, node_to=node_to, basis=basis,
        population_invoices=int(pop["code_invoices"].sum()),
        population_groups=int(len(charged)),
        population_containers=units,
        observed_min=round(float(charged["per_container"].min()), 2),
        observed_median=round(float(charged["per_container"].median()), 2),
        observed_max=round(float(charged["per_container"].max()), 2),
        invoice_total_usd=round(total, 2))


def derive_ocean(lines, ship, cfs, pod):
    """Ocean freight per container for one origin-to-port lane, from code 1301."""
    pop, _ = _per_container_population(
        lines, ship, "1301",
        lambda d: d["cfs"].eq(cfs) & d["pod"].eq(pod))
    if pop.empty:
        return None
    return _derived_row(
        f"OCEAN-{_tag(cfs)}-{_tag(pod)}", "OCEAN", (cfs, pod),
        f"Ocean freight {cfs} to {pod}", pop, "1301", cfs, pod)


def derive_destination(lines, ship, pod, site):
    """Destination delivery per container for one port-to-warehouse lane.

    Code 1638 only. The population is restricted to bookings of 40ft and 40'HC
    equipment, because a rate per container is only meaningful across containers of
    comparable size -- a lane whose population mixed 20ft boxes in would produce a
    per-container figure that prices neither.
    """
    def only_40(d):
        eq20 = pd.to_numeric(d["20"], errors="coerce").fillna(0)
        eq45 = pd.to_numeric(d["45"], errors="coerce").fillna(0)
        eq40 = pd.to_numeric(d["40"], errors="coerce").fillna(0)
        eq40hq = pd.to_numeric(d["40HQ"], errors="coerce").fillna(0)
        return (d["pod"].eq(pod) & d["site"].eq(site)
                & eq20.eq(0) & eq45.eq(0) & (eq40 + eq40hq).gt(0))

    pop, _ = _per_container_population(lines, ship, C.DAP_RATE_CODE, only_40)
    if pop.empty:
        return None
    excluded = ", ".join(sorted(C.DAP_RATE_EXCLUDED_CODES))
    return _derived_row(
        f"DEST-{_tag(pod)}-{_tag(site)}", "DEST_DELIVERY", (pod, site),
        f"Port {pod} to warehouse {site}", pop, C.DAP_RATE_CODE, pod, site,
        note=(f"Codes {excluded} are never included: they sit in the same cost pool and "
              "read like delivery charges, but they price different work."))


def derive_origin_component(lines, ship, region, code):
    """One itemised origin component for one pickup region.

    Only EXW cargo carries these. On FOB terms the supplier delivers to the port at
    their own cost, so the component does not exist on those invoices and must not
    be charged to them in the model either.

    Every one of them is a per-container rate, collection included -- see
    ``C.PICKUP_CODE`` for why collection is nonetheless not *charged* per container.
    """
    pop, _ = _per_container_population(
        lines, ship, code,
        lambda d: d["pickup_region"].eq(region) & d["term"].eq("EXW"))
    if pop.empty:
        return None
    label = f"{code} ({region})"
    basis = ("Per inbound load collected" if code == C.PICKUP_CODE else "Per container")
    return _derived_row(
        f"ORIG-{region}-{code}", "ORIGIN_COMPONENT", (region, code),
        f"Origin component {label}", pop, code, region, f"{region} port", basis=basis)


def incidence(lines, ship, code):
    """How often a charge code actually appears, across containerised in-scope cargo.

    Returns (groups charged, groups in the population, containers in the population).
    """
    pop = ship[ship["in_scope"] & ship["is_fcl"] & ship["containers_today"].gt(0)]
    if pop.empty:
        return 0, 0, 0
    charged = set(lines.loc[lines["code"].eq(code), "grp_key"])
    return (int(pop["grp_key"].isin(charged).sum()), int(len(pop)),
            int(pop["containers_today"].sum()))


def card_occasional_row(rate_id, code, item, card_rate, basis, lines, ship):
    """A carded rate for a charge that is billed on some shipments and not others.

    A rate card states what a charge costs **when it is charged**. For a lane rate that
    is the same as its cost per container, because every container on the lane incurs it
    exactly once. For an occasional charge -- documentation, an outlay fee, a terminal
    handling line that appears on two invoices in five -- it is not: the expected cost
    per container is the face value times how often the charge actually lands.

    Taking the face value and applying it to every modelled container is the single
    easiest way to build a badly wrong model, and it is nearly undetectable. It inflated
    this model by 5.4% on codes worth $755 of face value between them, the run completed,
    and only the calibration control noticed.

    So the client's contracted rate is used for the price and the client's own invoices
    for the frequency. Both halves are theirs.
    """
    charged, total, containers = incidence(lines, ship, code)
    if not total:
        return None
    share = charged / total
    rate = card_rate * share
    return _row(
        rate_id, "OTHER", code, item, rate, CARD, "HIGH",
        derivation=(f"Your rate card prices charge code {code} at ${card_rate:,.2f}. It is "
                    f"billed on {charged} of {total} containerised shipment groups "
                    f"({share:.0%}), so the cost per modelled container is "
                    f"${card_rate:,.2f} x {share:.0%} = ${rate:,.2f}. Applying the full "
                    "face value to every container would charge cost no invoice supports."),
        code=code, basis=basis,
        population_groups=charged, population_containers=containers)


def derive_misc(lines, ship, code):
    """A miscellaneous charge that does not vary by lane.

    Costed across the whole container fleet rather than across the invoices that
    happened to carry it. These codes -- documentation, outlay, surcharges, terminal
    handling -- are billed on some shipments and not others, so their real cost per
    container is the total divided by every container, not the face value of one
    charge applied to all of them.
    """
    pop, _ = _per_container_population(lines, ship, code, fleet_wide=True)
    if pop.empty:
        return None
    return _derived_row(
        f"MISC-{code}", "OTHER", code, f"Charge code {code}", pop, code, "", "",
        fleet_wide=True)


def _tag(value):
    head = str(value).split(",")[0].strip()
    return "".join(ch for ch in head if ch.isalnum()).upper()[:8] or "NA"


# --------------------------------------------------------------------------------------
# What consolidation adds, which no invoice can price
# --------------------------------------------------------------------------------------
SERVICE_RATE_IDS = {
    # config key -> (rate id, lookup used by costing, basis, code on a quote file,
    #                component on the sourcing board)
    "CFS_INBOUND_PER_DELIVERY": ("NEW-CFS-INBOUND", "cfs_inbound",
                                 "Per inbound delivery received", "CFS_INBOUND",
                                 "warehouse_inbound"),
    "CFS_HANDLING_PER_CONTAINER": ("NEW-CFS-HANDLING", "cfs_handling",
                                   "Per container built", "CFS_HANDLING",
                                   "warehouse_handling"),
    "CFS_DRAYAGE_PER_CONTAINER": ("NEW-CFS-DRAYAGE", "cfs_drayage",
                                  "Per container built", "CFS_DRAYAGE",
                                  "warehouse_to_port"),
    "CFS_STORAGE_PER_CBM_DAY": ("NEW-CFS-STORAGE", "cfs_storage",
                                "Per CBM per day beyond the free period", "CFS_STORAGE",
                                "warehouse_storage"),
    "DECONSOL_PER_EXTRA_SITE": ("NEW-DECONSOL", "deconsol",
                                "Per extra site on a container", "DECONSOL",
                                "destination_terminal"),
}

# The service figures that are not rates but still price something. The free period
# decides how many CBM-days of storage ever bill, so it is half of that cost line and
# has to come from the client like the other half does. It gets no rate row -- costing
# reads it off ``cfg`` -- so it is folded into the config instead, and counted as a gap
# when nobody has supplied it.
SERVICE_PARAMETER_IDS = {
    "CFS_STORAGE_FREE_DAYS": ("CFS_FREE_DAYS", "warehouse_storage"),
}


def service_codes():
    """Every consolidation-service figure, mapped to the code a quote prices it under.

    One map, because rates and parameters are two mechanisms for the same question --
    *has the client priced this?* -- and answering it from only one of them had the
    settings step treating a figure the quote covered as missing.
    """
    codes = {key: spec[3] for key, spec in SERVICE_RATE_IDS.items()}
    codes.update({key: spec[0] for key, spec in SERVICE_PARAMETER_IDS.items()})
    return codes


def service_parameters(cfg, pricing=None, card_index=None):
    """Fold quoted service parameters into the config, and report what is missing.

    Returns ``(cfg, gaps, priced)`` -- the config to run with, the parameters nobody has
    priced, and the keys that arrived on the quote, so the caller can record them as the
    client's own figures rather than ours.
    """
    pricing = pricing or {}
    card_index = card_index or {}
    cfg, gaps, priced = dict(cfg), [], []
    for key, (ch_code, component) in SERVICE_PARAMETER_IDS.items():
        hit = card_index.get(("CONSOLIDATION", "", "", ch_code))
        if pricing.get(key) == "edited":
            continue                      # they typed it; cfg already carries it
        if hit:
            cfg[key] = type(C.CONFIG[key]["value"])(hit["rate_usd"])
            priced.append(key)
            continue
        if pricing.get(key) == "quoted":
            continue                      # declared as theirs without a file
        gaps.append({"category": "SERVICE", "key": key, "code": ch_code,
                     "node_from": "", "node_to": "", "component": component,
                     "reason": ("no consolidation quote covers this, and no figure was "
                                "entered for it")})
    return cfg, gaps, priced


def service_rows(cfg, pricing=None, card_index=None, plan=None):
    """The consolidation-service rates, and where each one's price came from.

    These price a step the client does not perform today, so no invoice evidences
    them. That does not make them invented. A forwarder quotes this service, and a
    quoted rate for work not yet bought is evidence of a different kind -- which is why
    each rate carries its own pricing source rather than the whole group being written
    off as an assumption.

    Where the client has actually uploaded that quote, **its number is used**. Reading
    the figure out of our own config while calling it "your forwarder's quote" would be
    the one claim in the whole model that the file cannot support, and it is the easiest
    to get wrong because nothing downstream would notice.

    ``pricing`` maps a config key to one of three states. "quoted" means the figure is the
    client's own commercial number. "edited" means they typed it on the settings step,
    which is also their number and which overrides everything, including a quote they
    uploaded earlier. "benchmark" means nobody has priced it, and that is not a price:
    the rate is not emitted at all and a gap is returned in its place.

    Returns ``(rows, gaps)``.
    """
    pricing = pricing or {}
    card_index = card_index or {}
    plan = plan or {}
    rows, gaps = [], []
    for key, (rate_id, lookup, basis, ch_code, component) in sorted(
            SERVICE_RATE_IDS.items()):
        meta = C.CONFIG[key]
        state = pricing.get(key, C.SERVICE_PRICING_DEFAULT)
        quoted = state in ("quoted", "edited")
        hit = card_index.get(("CONSOLIDATION", "", "", ch_code))

        cs = plan.get(component)
        audit = {}
        analogue = (cs is not None and cs.state == sourcing.ANALOGUE
                    and cs.population.get("rate_usd"))

        if state == "edited":
            # Tested first, and it beats every other source including an uploaded quote.
            # A figure typed on the settings step has to be the figure the model costs:
            # showing one number and costing the card's is the same failure as ignoring
            # an uploaded rate, and nothing downstream would notice either.
            rate, source, confidence = cfg[key], QUOTED, "HIGH"
            derivation = (
                f"{meta['source']} You entered this figure on the settings step."
                + (f" Your uploaded quote said ${hit['rate_usd']:,.2f}." if hit else ""))
        elif hit:
            # An uploaded quote prices this leg, so it is priced -- no separate say-so
            # required. The client cannot both hand us the quote and mean for us to
            # ignore it, and the only way to use a different number is to type one,
            # which is the branch above.
            rate, source, confidence = hit["rate_usd"], QUOTED, "HIGH"
            derivation = (f"{meta['source']} Taken from the consolidation quote you "
                          f"uploaded — {hit['item'] or ch_code}.")
        elif analogue:
            # The board says this leg is derived by analogy from the client's own
            # invoices, so the model has to actually use that figure. Advertising a
            # derivation on screen and quietly costing the benchmark instead is the
            # same failure as ignoring an uploaded rate: the claim and the arithmetic
            # come apart, and only the screen is checked.
            pop = cs.population
            rate, source, confidence = pop["rate_usd"], DERIVED, "LOW"
            derivation = (
                f"{meta['source']} ${pop['usd']:,.2f} of charge code "
                f"{', '.join(pop['codes'])} across {pop['groups']} shipment groups, "
                f"divided by the {pop['containers']} containers those groups moved. "
                f"CAVEAT: {cs.caveat}. {cs.chosen.get('note', '')}").strip()
            # A rate tagged DERIVED has to carry the population behind it, or the control
            # that checks every derivation traces to an invoice has nothing to read.
            audit = {"population_invoices": pop["invoices"],
                     "population_groups": pop["groups"],
                     "population_containers": pop["containers"],
                     "invoice_total_usd": pop["usd"],
                     "charge_code": ", ".join(pop["codes"])}
        elif quoted:
            rate, source, confidence = cfg[key], QUOTED, "HIGH"
            derivation = f"{meta['source']} {meta['quoted_note']}"
        else:
            # Nobody has priced this, so the model will not either. Costing the
            # consolidation service from our own benchmark is the one substitution that
            # cannot be made honestly: it is the new cost the whole comparison turns on,
            # it exists only on the future side, and on our own datasets it accounted for
            # about 60% of the saving. So this is a gap, and the run stops on it.
            gaps.append({"category": "SERVICE", "key": lookup, "code": ch_code,
                         "node_from": "", "node_to": "", "component": component,
                         "reason": ("no consolidation quote covers this, and no figure "
                                    "was entered for it")})
            continue
        if key == "CFS_STORAGE_PER_CBM_DAY":
            derivation += f" First {cfg['CFS_STORAGE_FREE_DAYS']} days free."
        item = meta["label"]

        rows.append(_row(
            rate_id, "SERVICE", lookup, item, rate, source, confidence,
            derivation=derivation, basis=basis, component=component, **audit))
    return rows, gaps


# --------------------------------------------------------------------------------------
def build_rates(lines, ship, containers, cfg, rate_card=None, service_pricing=None,
                plan=None):
    """Price every leg the modelled containers need, card first, then derived.

    The set of things needing a price is read off the containers the packer actually
    built, not off the rate card or the history. That ordering matters: it means the
    engine can state exactly what it could not price, instead of quietly costing
    only the lanes it happened to have rates for.

    ``plan`` is the sourcing verdict per component from ``sourcing.plan``. Card-then-
    derive still decides each individual lane -- a card covering six lanes of eight
    leaves two to reconstruct, and that is the normal case -- but the plan governs what
    is *permitted*: whether a derivation is possible at all, whether it is an analogue
    and must be labelled as one, and which codes are ineligible for a miscellaneous
    rate because they arrive bundled.
    """
    card_index = index_rate_card(rate_card)
    plan = plan or {}
    con = pd.DataFrame(containers)
    rows, gaps = [], []
    needs = []

    def take(category, key, code, node_from, node_to, item, derive_fn, component="",
             occasional=False):
        """Card if it prices this, otherwise derive it, otherwise record a gap.

        ``occasional`` marks a charge that is billed on some shipments and not others,
        where a carded face value has to be weighted by how often it actually lands.
        """
        card_key = (category, node_from, node_to, code)
        needs.append(card_key)
        cs = plan.get(component)
        hit = card_index.get(card_key)
        if hit and occasional:
            scaled = card_occasional_row(
                hit["rate_id"] or f"CARD-{code}", code, hit["item"] or item,
                hit["rate_usd"], hit["basis"], lines, ship)
            if scaled is not None:
                scaled["component"] = component
                rows.append(scaled)
                return
        if hit:
            rows.append(_row(
                hit["rate_id"] or f"CARD-{_tag(node_from)}-{_tag(node_to)}-{code}",
                category, key, hit["item"] or item, hit["rate_usd"], CARD, "HIGH",
                derivation="Priced directly from the client's rate card.",
                code=code, basis=hit["basis"], node_from=node_from, node_to=node_to,
                component=component))
            return

        # A derivation the sourcing plan has ruled out must not be attempted. The
        # commonest reason is bundling: the code that would price this leg exists but
        # arrives fused to three others, so a per-container average of it prices nothing
        # and would silently double-count against the components it contains.
        if cs is not None and not cs.derive_allowed():
            gaps.append({"category": category, "key": str(key), "code": code,
                         "node_from": node_from, "node_to": node_to,
                         "component": component,
                         "reason": (cs.rejected[-1]["why"] if cs.rejected
                                    else "no source available for this component")})
            return

        derived = derive_fn()
        if derived is not None:
            derived["component"] = component
            # An analogue prices adjacent work. It travels with its caveat attached and
            # can never read as HIGH confidence, because presenting the right charge on
            # the wrong leg as a clean derivation would be a quiet lie.
            if cs is not None and cs.state == "analogue":
                derived["confidence"] = "LOW"
                derived["derivation"] = (
                    f"{derived['derivation']} CAVEAT: {cs.caveat}. {cs.chosen.get('note', '')}"
                ).strip()
            rows.append(derived)
            return
        gaps.append({"category": category, "key": str(key), "code": code,
                     "node_from": node_from, "node_to": node_to,
                     "component": component,
                     "reason": "no rate-card row and no invoice history to derive from"})

    # --- ocean, one rate per origin-to-port lane the plan uses -----------------
    for cfs, pod in sorted({(r["cfs"], r["pod"]) for r in containers}):
        take("OCEAN", (cfs, pod), "1301", cfs, pod,
             f"Ocean freight {cfs} to {pod}",
             lambda cfs=cfs, pod=pod: derive_ocean(lines, ship, cfs, pod),
             component="ocean_freight")

    # --- destination, one rate per port-to-warehouse lane ----------------------
    site_lanes = set()
    for r in containers:
        for site in r["sites_list"]:
            site_lanes.add((r["pod"], site))
    for pod, site in sorted(site_lanes):
        take("DEST_DELIVERY", (pod, site), C.DAP_RATE_CODE, pod, site,
             f"Port {pod} to warehouse {site}",
             lambda pod=pod, site=site: derive_destination(lines, ship, pod, site),
             component="destination_delivery")

    # --- origin components, per pickup region, EXW only ------------------------
    #
    # The collection charge and the terminal mechanics are two different components on
    # the board even though they share a category here, because a client can perfectly
    # well have a rate for one and not the other.
    regions = sorted(ship.loc[ship["in_scope"] & ship["term"].eq("EXW"),
                              "pickup_region"].dropna().unique())
    for region in regions:
        for code in C.EXW_COMPONENT_CODES:
            take("ORIGIN_COMPONENT", (region, code), code, region, f"{region} port",
                 f"Origin component {code} ({region})",
                 lambda region=region, code=code: derive_origin_component(
                     lines, ship, region, code),
                 component=("origin_collection" if code == "1631"
                            else "origin_terminal"))

    # --- the remaining per-container charges the history carries ---------------
    #
    # Taken from containerised cargo only. Codes that appear solely on LCL or air
    # shipments -- import trucking, for instance -- price last-mile work the plan
    # replaces with container delivery, so there is nothing per-container to
    # derive and nothing the model needs. Including them would report a rate gap
    # for a rate the model never asks for.
    #
    # Bundled codes are excluded, and this exclusion is load-bearing. A bundle's money
    # is already represented by the component rates pricing the legs inside it, so
    # deriving a per-container average of code 1300 and charging it on top of the ocean
    # and delivery rates counts the same dollars twice. The failure mode is nearly
    # invisible: the run completes, the ledger balances, every control except calibration
    # passes, and the modelled cost is simply double what the client pays.
    fcl_groups = ship.loc[ship["in_scope"] & ship["is_fcl"], "grp_key"]
    bundled = sourcing.excluded_from_misc(lines)
    other_codes = sorted({
        code for code in lines.loc[lines["grp_key"].isin(fcl_groups), "code"].unique()
        if code in C.CHARGE_CODE_POOLS
        and code not in C.EXW_COMPONENT_CODES
        and code not in bundled
        and code not in {"1301", "1302", "1101", "1401", C.DAP_RATE_CODE}})
    for code in other_codes:
        take("OTHER", code, code, "", "", f"Charge code {code}",
             lambda code=code: derive_misc(lines, ship, code),
             component="destination_terminal" if code in ("1505", "1511", "1411") else "",
             occasional=True)

    service, service_gaps = service_rows(
        cfg, service_pricing, card_index=card_index, plan=plan)
    rows.extend(service)
    gaps.extend(service_gaps)

    table = pd.DataFrame(rows)
    index = {(r["category"], r["key"]): r for r in rows}

    by_source = table["source"].value_counts().to_dict() if len(table) else {}
    stats = {
        "rates_total": int(len(table)),
        "from_card": int(by_source.get(CARD, 0)),
        "derived": int(by_source.get(DERIVED, 0)),
        "quoted": int(by_source.get(QUOTED, 0)),
        "assumed": int(by_source.get(ASSUMED, 0)),
        "invented": 0,
        "gaps": len(gaps),
        "card_coverage": card_coverage(card_index, needs),
        "derived_invoice_total_usd": round(
            float(table.loc[table["source"].eq(DERIVED), "invoice_total_usd"].sum()), 2)
        if len(table) else 0.0,
    }
    return RateTable(rows=table, index=index, stats=stats, gaps=gaps)
