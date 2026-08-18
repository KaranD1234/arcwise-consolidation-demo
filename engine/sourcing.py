"""Decide how each cost component gets its price, and be able to say why.

This is the layer that answers the question a prospect actually asks. Not "did you
take my rate card?" but **"where did the price for *this leg* come from, and what
happens when you can't work it out?"** The answer differs per leg and it differs per
client, so it has to be computed rather than asserted.

Every entry in ``C.COST_COMPONENTS`` lists the sources that could price it, best first.
This module walks that list against what is actually available -- the uploaded cards and
the client's own charge lines -- and returns one verdict per component:

    card          a rate card prices this leg. Best case: a contracted rate is what
                  they will be billed.
    derived       no card, but the invoices carry enough of the right charge code to
                  rebuild the rate. Their money, their volumes.
    analogue      the invoices carry the right *kind* of charge on the wrong leg.
                  Directionally sound, labelled as such, and never HIGH confidence.
    thin          a population exists but is too small to be a rate. Three invoices
                  can produce a confident-looking number that means nothing.
    quoted        the forwarder quoted it, because the step has never happened.
    benchmark     our figure, standing in until they have a quote.
    unpriced      nothing available. The interface asks for a rate card rather than
                  quietly reaching for a number.

The interesting state is the one the data creates rather than the one it fills:

    blocked       the charge code that would price this leg exists, but it arrives
                  BUNDLED with other legs. The dollars are all present and reconcile to
                  the cent; they simply cannot be attributed. This is the commonest real
                  reason a leg cannot be derived, and reporting it as a bare absence
                  wastes the one thing we do know -- exactly which codes are hiding it.

And one state that is not about the past at all:

    opportunity   an ALTERNATIVE way of buying this leg that the client has given us no
                  rate for. Consolidation creates warehouse-to-quay runs they do not
                  make today, which is enough volume to tender and exactly the kind of
                  rate nobody has on file for work they have never bought. So the engine
                  quantifies what such a rate would have to beat and asks for it -- and
                  when it arrives, tests it and is perfectly willing to report that the
                  drayage was cheaper.
"""

from dataclasses import dataclass, field

import config as C

CARD = "card"
DERIVED = "derived"
ANALOGUE = "analogue"
THIN = "thin"
QUOTED = "quoted"
BENCHMARK = "benchmark"
UNPRICED = "unpriced"

# States in which the component has a price the model may use. Everything else means
# the run must either ask for a rate or refuse to cost the leg.
#
# BENCHMARK is deliberately absent. The legs it applied to are the consolidation service
# itself -- handling, drayage, storage, the strip -- which is the *new* cost the whole
# case turns on. Pricing that from our own figures put around 60% of the saving on
# numbers the client had never seen, and, because the new cost only exists on one side of
# the comparison, leaving it out is worse than useless: it makes consolidation look
# better the less the client has told us. The quote is required.
PRICED_STATES = frozenset({CARD, DERIVED, ANALOGUE, QUOTED})

# States that carry a health warning onto every dollar they touch.
QUALIFIED_STATES = frozenset({ANALOGUE})


@dataclass
class ComponentSourcing:
    """How one leg of the journey got its price."""
    key: str
    label: str
    leg: str
    sub: str
    state: str = UNPRICED
    chosen: dict = field(default_factory=dict)
    available: list = field(default_factory=list)   # every source that would have held
    rejected: list = field(default_factory=list)    # and why each earlier one did not
    caveat: str = ""
    population: dict = field(default_factory=dict)
    card_rows: int = 0
    blocked_by: list = field(default_factory=list)  # bundles hiding the codes we need
    alternative: dict = field(default_factory=dict)

    @property
    def priced(self):
        return self.state in PRICED_STATES

    @property
    def needs_rate(self):
        """True where the interface should put an upload slot on this card."""
        return self.state == UNPRICED

    @property
    def qualified(self):
        return self.state in QUALIFIED_STATES

    def derive_allowed(self):
        """Whether rates.py may reconstruct this component's rates from invoices.

        False where the component resolved to a card or a quote AND nothing in the data
        could have derived it anyway -- and, importantly, False where the codes are
        bundled. A blocked derivation must not silently fall through to a per-container
        average of a bundle that contains three other legs.
        """
        return self.state in (DERIVED, ANALOGUE) or any(
            s["kind"] in ("derive", "analogue") for s in self.available)


def code_population(lines, ship, codes):
    """How much evidence the charge lines hold for a set of codes.

    Counted across in-scope containerised cargo only, because that is the population a
    per-container rate would be built from. Out-of-scope air and road cargo carries its
    own version of some of these codes and none of it prices a container.

    ``rate_usd`` is the per-container figure the population implies, divided by the
    containers of the groups that actually carried the charge -- not by every container in
    the period. That is the right denominator here because the legs this prices happen
    once per container when they happen at all; the fleet-wide denominator belongs to the
    occasional charges, and using it here would understate a real cost.
    """
    fcl = ship[ship["in_scope"] & ship["is_fcl"] & ship["containers_today"].gt(0)]
    keys = set(fcl["grp_key"])
    hit = lines[lines["code"].isin(list(codes)) & lines["grp_key"].isin(keys)]
    if not len(hit):
        return {"groups": 0, "invoices": 0, "usd": 0.0, "lines": 0, "codes": [],
                "containers": 0, "rate_usd": 0.0}
    charged = set(hit["grp_key"])
    containers = int(fcl.loc[fcl["grp_key"].isin(charged), "containers_today"].sum())
    usd = round(float(hit["line_usd"].sum()), 2)
    return {
        "groups": int(hit["grp_key"].nunique()),
        "invoices": int(hit["Sales Invoice #"].nunique()),
        "usd": usd,
        "lines": int(len(hit)),
        "codes": sorted(hit["code"].unique()),
        "containers": containers,
        "rate_usd": round(usd / containers, 2) if containers else 0.0,
    }


def bundles_in(lines):
    """Which bundled codes reached this file, and what each one is hiding.

    Keyed both ways round: by bundle code, and by each code the bundle swallows, so a
    component can ask "is what I need inside a bundle?" without knowing the register.
    """
    present = set(lines["code"].unique())
    bundles, blocks = {}, {}
    for code, spec in sorted(C.BUNDLED_CODES.items()):
        if code not in present:
            continue
        hit = lines[lines["code"].eq(code)]
        info = dict(spec, code=code, lines=int(len(hit)),
                    usd=round(float(hit["line_usd"].sum()), 2))
        bundles[code] = info
        for covered in spec["covers"]:
            blocks.setdefault(covered, []).append(info)
    return bundles, blocks


def card_hits(card_index, category, codes):
    """Rows on the uploaded cards that price this category and code set."""
    wanted = set(str(c) for c in codes)
    return [key for key in sorted(card_index)
            if key[0] == category and key[3] in wanted]


def _describe_card(rows, category):
    n = len(rows)
    return (f"{n} row{'s' if n != 1 else ''} on your "
            f"{category.replace('_', ' ').lower()} card "
            f"{'price' if n != 1 else 'prices'} this leg directly.")


def plan(lines, ship, card_index, service_pricing=None, containers_today=0,
         pickups_today=0):
    """Work out how every component gets priced. Returns {key: ComponentSourcing}.

    Sources are tried in the order the component declares them, and the first that
    holds wins -- but every source that *would* have held is kept, because that list is
    what lets the interface offer an override instead of presenting one answer as the
    only answer.
    """
    service_pricing = service_pricing or {}
    _, blocked_by_code = bundles_in(lines)
    out = {}

    for spec in C.COST_COMPONENTS:
        cs = ComponentSourcing(key=spec["key"], label=spec["label"],
                               leg=spec["leg"], sub=spec["sub"])

        for source in spec["sources"]:
            kind = source["kind"]

            if kind == "card":
                rows = card_hits(card_index, source["category"], source["codes"])
                if not rows:
                    cs.rejected.append({
                        "kind": kind, "why": "no row on any card you have given us "
                        f"prices {source['category'].replace('_', ' ').lower()}"})
                    continue
                entry = {"kind": kind, "state": CARD, "category": source["category"],
                         "codes": source["codes"], "rows": len(rows),
                         "note": _describe_card(rows, source["category"])}
                cs.available.append(entry)
                if not cs.chosen:
                    cs.chosen, cs.state, cs.card_rows = entry, CARD, len(rows)
                continue

            if kind in ("derive", "analogue"):
                # A card can carry an analogue rate too -- code 1602 on an origin
                # services schedule prices the supplier-to-port run whichever file it
                # arrives in. It is still an analogue, so it is evaluated here rather
                # than as a clean card source.
                card_rows = []
                for alt in source.get("cards", []):
                    card_rows += card_hits(card_index, alt["category"], alt["codes"])

                blocking = [b for code in source["codes"]
                            for b in blocked_by_code.get(code, [])]
                if blocking and not card_rows:
                    seen, unique = set(), []
                    for b in blocking:
                        if b["code"] not in seen:
                            seen.add(b["code"])
                            unique.append(b)
                    cs.blocked_by = unique
                    cs.rejected.append({
                        "kind": kind,
                        "why": "; ".join(
                            f"charge code {b['code']} ({b['label']}) bundles "
                            f"{len(b['covers'])} legs onto one line — {b['blocks']}"
                            for b in unique)})
                    continue

                pop = code_population(lines, ship, source["codes"])
                if not pop["groups"] and not card_rows:
                    cs.rejected.append({
                        "kind": kind,
                        "why": f"charge code{'s' if len(source['codes']) > 1 else ''} "
                               f"{', '.join(source['codes'])} "
                               f"{'do' if len(source['codes']) > 1 else 'does'} not "
                               "appear on any containerised shipment in your file"})
                    continue

                thin = pop["groups"] < C.MIN_DERIVE_GROUPS and not card_rows
                state = THIN if thin else (ANALOGUE if kind == "analogue" else DERIVED)
                entry = {"kind": kind, "state": state, "codes": source["codes"],
                         "note": source.get("note", ""),
                         "caveat": source.get("caveat", ""),
                         "population": pop, "card_rows": len(card_rows),
                         "fleet_wide": source.get("fleet_wide", False)}
                if thin:
                    # Reported, not used. A rate built on a handful of invoices looks
                    # exactly as confident as one built on three hundred, which is why
                    # the threshold exists and why falling short has to be visible.
                    entry["note"] = (
                        f"Only {pop['groups']} shipment groups carry "
                        f"{', '.join(source['codes'])} — below the {C.MIN_DERIVE_GROUPS} "
                        "needed to call this a rate rather than an anecdote.")
                    cs.rejected.append({"kind": kind, "why": entry["note"]})
                    continue

                cs.available.append(entry)
                if not cs.chosen:
                    cs.chosen, cs.state = entry, state
                    cs.population, cs.caveat = pop, source.get("caveat", "")
                continue

            if kind == "service":
                # Satisfied only by the client's own figure: the quote they uploaded, or
                # a number they typed on the settings step. With neither, this leg has no
                # price at all and the component stays unpriced, which is the same
                # treatment every other leg gets when the evidence is not there.
                key = source["config_key"]
                quoted = service_pricing.get(
                    key, C.SERVICE_PRICING_DEFAULT) in ("quoted", "edited")
                if not quoted:
                    cs.rejected.append(
                        {"kind": kind, "config_key": key,
                         "why": "you have not given us a price for this yet"})
                    continue
                meta = C.CONFIG[key]
                entry = {"kind": kind, "state": QUOTED, "config_key": key,
                         "note": meta["quoted_note"]}
                cs.available.append(entry)
                if not cs.chosen:
                    cs.chosen, cs.state = entry, entry["state"]
                continue

            raise ValueError(f"unknown source kind {kind!r} on {spec['key']}")

        cs.alternative = _alternative(spec, cs, card_index, containers_today,
                                      pickups_today)
        out[cs.key] = cs

    return out


def _alternative(spec, cs, card_index, containers_today, pickups_today=0):
    """Evaluate an alternative way of buying this leg, where the component has one.

    An alternative is not a fallback. The chosen source above prices the leg the way the
    client already buys road moves; this prices it a different way, and only displaces
    the chosen source if it comes out cheaper against real volumes.

    Where no card supplies it, the return value is the *ask*: what the alternative would
    have to beat, quantified from the shipments the client collects today rather than from
    the plan, because the plan does not exist yet at the point the board is read. The
    interface says so, and the Results step restates it on the trailers the plan actually
    packs, which is the only count that can settle it.
    """
    alts = spec.get("alternatives", [])
    if not alts or not cs.priced:
        return {}

    alt = alts[0]
    rows = card_hits(card_index, alt["category"], alt["codes"])
    base = {
        "key": alt["key"], "label": alt["label"], "basis": alt["basis"],
        "note": alt["note"], "ask": alt["ask"], "plan_neutral": alt["plan_neutral"],
        "category": alt["category"], "codes": alt["codes"],
        # What it has to beat, and where that number came from. Naming the counterparty
        # matters: a firm quote beating another firm quote is a stronger conclusion than
        # a firm quote beating a LOW-confidence analogue, and the interface must not
        # flatten the two.
        "counterparty_state": cs.state,
        "counterparty_qualified": cs.qualified,
        "containers_today": containers_today,
        "pickups_today": pickups_today,
        "per_pickup_today": (round(cs.population["rate_usd"], 2)
                             if cs.population.get("rate_usd") else 0.0),
    }
    if not rows:
        return dict(base, state="opportunity", supplied=False)
    return dict(base, state="supplied", supplied=True, rows=len(rows))


def summarise(plan_by_key):
    """Board-level counts, for the provenance strip and the controls."""
    by_state = {}
    for cs in plan_by_key.values():
        by_state[cs.state] = by_state.get(cs.state, 0) + 1
    return {
        "components": len(plan_by_key),
        "by_state": dict(sorted(by_state.items())),
        "priced": sum(1 for cs in plan_by_key.values() if cs.priced),
        "unpriced": sorted(cs.key for cs in plan_by_key.values() if not cs.priced),
        "qualified": sorted(cs.key for cs in plan_by_key.values() if cs.qualified),
        "blocked_by_bundles": sorted(
            {b["code"] for cs in plan_by_key.values() for b in cs.blocked_by}),
        "opportunities": sorted(
            cs.key for cs in plan_by_key.values()
            if cs.alternative.get("state") == "opportunity"),
    }


def excluded_from_misc(lines):
    """Charge codes that must never become a miscellaneous per-container rate.

    Bundled codes and the codes they swallow, both.

    The bundle itself is excluded because its money is already represented by the
    component rates that price the legs inside it -- deriving a per-container average of
    code 1300 and charging it on top of the ocean and delivery rates counts the same
    dollars twice. That mistake is worth spelling out because it is nearly invisible:
    the run completes, every control except calibration passes, and the modelled cost is
    simply double what the client pays.

    The covered codes are excluded because in a bundled file they do not appear at all,
    and in a partially-bundled one they would double-count against the bundle.
    """
    bundles, _ = bundles_in(lines)
    out = set(bundles)
    for info in bundles.values():
        out.update(info["covers"])
    return out
