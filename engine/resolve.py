"""Resolve the joins that need judgement, and escalate the ones that need a human.

This is the layer a client cannot hand over as a file, because it does not exist
until someone makes the decisions in it. The charge-line export says
``Fowler Welch - Kent``; the rate card prices a warehouse. Something has to decide
those are the same place, or that they are not, and record why.

The engine resolves what it can defend and escalates what it cannot:

    auto-resolved   the delivery string names a site the client's own list already
                    carries, or is a near-identical spelling of one. Evidence and
                    a confidence are recorded, and the run proceeds.
    escalated       genuinely ambiguous. Five rules produce these, each with a
                    proposal, the evidence behind it and what volume rides on the
                    answer:

        not_a_place                 the address field holds a placeholder
        ambiguous_region            a county or region, not somewhere you deliver
        operator_multi_city         one operator at two locations -- one site or two?
        unlisted_site_material      a site absent from the client's own list that
                                    carries real volume
        supplier_office_not_origin  the shipper is recorded at an office in another
                                    country, so no pickup region can be priced

Nothing is guessed silently. Both outputs are written in the shape of a mapping
file, so a resolved run can be handed back as an upload and the queue is empty the
second time. First run is work; every run after it is free.
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import pandas as pd

import config as C


@dataclass
class QueueItem:
    """One decision the engine will not take on its own.

    ``key`` is what a reviewer reads -- the raw string being resolved. ``uid`` is what
    identifies the decision, and the two are not the same thing: one supplier name can
    appear against two different origins, and those are two separate decisions with
    two separate answers. Routing answers by the readable label instead of the
    identity silently applies one reviewer's decision to a mapping they never saw.
    """
    kind: str            # "site" or "supplier"
    rule: str
    key: str             # the raw value being resolved, as shown to the reviewer
    question: str
    proposal: str        # the engine's recommendation; always the first option
    options: list
    confidence: str      # HIGH / MEDIUM / LOW -- confidence in the proposal
    evidence: str
    volume_note: str = ""
    uid: str = ""        # unique per decision; see above
    scope: dict = field(default_factory=dict)   # the columns the answer applies to
    # Set where the string reads like a county or province. It qualifies the answer
    # rather than adding an option: naming a place a site is one decision however the
    # engine feels about the name, and the doubt is the engine's to record, not another
    # question for the reviewer to answer.
    area_named: bool = False
    # What each option *is*, so that reading an answer never means parsing its wording.
    #
    # ``values`` maps the option a reviewer sees to the value the model applies, and
    # ``kinds`` to what sort of answer it is ("site", "new_site", "merge", "separate",
    # "region", "exclude"). Both exist because the options used to be sentences that
    # apply_answers took apart again by stripping known prefixes -- so the wording could
    # not be improved without breaking the resolution, and every rule drifted into its
    # own grammar: an instruction here, a bare place name there, a raw region code on
    # the third. The screen and the model now agree by construction.
    values: dict = field(default_factory=dict)
    kinds: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.uid:
            self.uid = f"{self.kind}:{self.rule}:{self.key}"


@dataclass
class Resolution:
    sites: pd.DataFrame          # Delivery_Raw -> site, in mapping-file shape
    suppliers: pd.DataFrame      # Shipper/CFS -> pickup region, in mapping-file shape
    queue: list = field(default_factory=list)
    auto_resolved: int = 0
    stats: dict = field(default_factory=dict)


# --------------------------------------------------------------------------------------
# How an answer reads
#
# Every question on the review step asks one thing, and every option answers that one
# thing in the same grammar, so that two options can never be two spellings of the same
# answer and no option is an instruction to the software. A site question is answered
# with a destination; a supplier question with a place the goods are collected from.
# --------------------------------------------------------------------------------------
EXCLUDE = "Leave this cargo out of the model"


def _deliver_to(site):
    return f"Deliver to {site}"


def _collected_from(region):
    """A region key, as a place. ``BINH_DUONG`` is ours; 'Binh Duong' is theirs."""
    return f"Collected from {_region_name(region)}"


def _region_name(region):
    text = str(region).replace("_", " ")
    # Short all-caps keys are acronyms a shipper would recognise (HCMC), and title-casing
    # them produces something nobody says out loud.
    return text if len(text) <= 5 and text.isupper() else text.title()


# --------------------------------------------------------------------------------------
# Text handling
# --------------------------------------------------------------------------------------
def split_operator_location(raw):
    """Split ``Broekman Logistics BV c/o - Venlo`` into operator and location.

    The convention across these exports is that the location follows the final
    dash. Everything before it is the operator, whose name drifts freely.
    """
    text = str(raw).strip()
    if " - " in text:
        operator, location = text.rsplit(" - ", 1)
    else:
        operator, location = text, ""
    return operator.strip(), location.strip()


def family(operator):
    """The operator's first word -- enough to spot the same company twice.

    ``Rhenus Logistics`` and ``Rhenus Warehousing Solutions`` share nothing a
    string comparison would notice, but they are one company, and whether their
    two locations are one site or two changes what may share a container.
    """
    words = re.findall(r"[A-Za-z]+", str(operator))
    return words[0].lower() if words else ""


def normalise(token):
    return re.sub(r"[^a-z ]", "", str(token).lower()).strip()


def ratio(a, b):
    return SequenceMatcher(None, normalise(a), normalise(b)).ratio()


def city_of(site_name):
    """``Venlo, NL`` -> ``venlo``."""
    return normalise(str(site_name).split(",")[0])


def city_similarity(token, city):
    """How alike two city strings are, allowing for a longer official form.

    A whole-string comparison is not enough on its own. Local usage shortens place
    names and official records do not: ``Riba-roja de Turia`` and ``Ribarroja`` are one
    town, and comparing them end to end scores 62% -- comfortably below the auto-match
    threshold, so the same warehouse resolves twice and the second copy has no rate.

    So the leading word is scored as well and the better of the two wins. That catches
    the official-long-form case without loosening the threshold, which matters: dropping
    the threshold far enough to match these two would also start merging genuinely
    different towns that happen to share a prefix.
    """
    best = ratio(token, city)
    lead_token, lead_city = token.split(" ")[0], city.split(" ")[0]
    if lead_token and lead_city:
        best = max(best, ratio(lead_token, lead_city))
    return best


# --------------------------------------------------------------------------------------
# Sites
# --------------------------------------------------------------------------------------
def sites_from_data(all_raw, context, volume):
    """The client's warehouse list, read out of their own delivery addresses.

    Asking a client for a list of their own warehouses was always a strange request:
    every one of those warehouses is already named, hundreds of times, in the file they
    have just handed over. A town that appears in the delivery address of forty
    shipments, discharging at the port that serves it, is a delivery point on the
    client's own evidence -- and confirming its spelling against a list adds nothing the
    file did not already say.

    Two kinds of string are deliberately *not* listed here, because listing them would
    answer a question only the client can answer:

    * a placeholder -- "City", "TBC", "N/A" -- which names nowhere at all;
    * a region -- "Shropshire", "Limburg", "Aragon" -- which may cover several delivery
      points, in which case a rate built for it is an area average rather than a site
      rate.

    Both still escalate, which is why removing the site list shortens the review rather
    than lengthening it: what is left on the queue is the handful of records the data
    genuinely cannot settle.

    Two details the file cannot settle either, and which are handled here rather than
    assumed away:

    * **Spelling.** "Riba-roja de Turia" and "Ribarroja" are one warehouse. Listing each
      spelling separately would make each one match itself perfectly and split a site in
      two, so near-identical spellings are merged and the busiest is kept as the name.
    * **Country.** The delivery address gives a town and nothing else; the only country
      in the file is the discharge port's. That is right for every site served by a port
      in its own country and wrong for one across a border, so a self-identified site is
      named by its town alone and no country is claimed for it. Supply a site list and
      the country comes from there.
    """
    seen = {}
    for raw_value in all_raw:
        _, location = split_operator_location(raw_value)
        token = normalise(location)
        if (not token or token in C.RESOLVE["PLACEHOLDER_TOKENS"]
                or token in C.RESOLVE["REGION_HINTS"]):
            continue
        vol = volume.get(raw_value, {})
        entry = seen.setdefault(token, {
            "site_id": _site_id(location.strip()), "site": location.strip(),
            "country": context.get(raw_value, {}).get("country", ""),
            "city": token, "from_data": True, "groups": 0, "pallets": 0,
        })
        entry["groups"] += int(vol.get("groups", 0))
        entry["pallets"] += int(vol.get("pallets", 0))

    # Busiest first, so the spelling most of the cargo travels under is the one that
    # names the site and the rarer variant folds into it.
    merged = []
    for entry in sorted(seen.values(), key=lambda e: (-e["pallets"], e["city"])):
        twin = next((m for m in merged
                     if city_similarity(entry["city"], m["city"])
                     >= C.RESOLVE["AUTO_MATCH_RATIO"]), None)
        if twin:
            twin["groups"] += entry["groups"]
            twin["pallets"] += entry["pallets"]
            continue
        merged.append(entry)
    return sorted(merged, key=lambda s: s["site_id"])


def resolve_sites(ship, site_list=None):
    """Map every raw delivery string to a physical site.

    The warehouses are always read out of the delivery addresses first -- see
    ``sites_from_data`` -- and ``site_list``, where the client has one, is laid over the
    top: their naming and their country win for the sites it covers, and the sites it
    misses are still known.

    It is layered rather than substituted because a real list is partial. Treating a list
    as the whole truth meant a client who named two of their twelve warehouses got a
    *longer* review than one who named none, which is the wrong way round: giving us
    something must never be worse than giving us nothing.
    """
    supplied = []
    if site_list is not None and len(site_list):
        for r in site_list.to_dict("records"):
            supplied.append({
                "site_id": str(r["Site_ID"]).strip(),
                "site": str(r["Site_Name"]).strip(),
                "country": str(r["Site_Country"]).strip(),
                "city": city_of(r["Site_Name"]),
            })
    have_list = bool(supplied)

    scope = ship[ship["in_scope"]]
    total_pallets = max(1, int(scope["pallets"].sum()))
    volume = (scope.groupby("delivery_raw")
              .agg(pallets=("pallets", "sum"), groups=("grp_key", "nunique"))
              .to_dict("index"))
    # The port and country a delivery string actually ships through, taken from the
    # data rather than assumed from the site's name.
    context = {}
    for raw_value, g in scope.groupby("delivery_raw"):
        context[raw_value] = {
            "pod": g["pod"].mode().iloc[0] if len(g["pod"].mode()) else "",
            "country": g["pod_country"].mode().iloc[0] if len(g["pod_country"].mode()) else "",
        }

    all_raw = sorted(ship["delivery_raw"].dropna().unique())
    listed = {s["city"]: s for s in sites_from_data(all_raw, context, volume)}
    for entry in supplied:
        # The client's own naming beats ours, including where they spell the town
        # differently -- so the one we read out of the file is replaced, not doubled.
        twin = next((c for c in listed
                     if city_similarity(entry["city"], c)
                     >= C.RESOLVE["AUTO_MATCH_RATIO"]), None)
        if twin is not None:
            listed.pop(twin)
        listed[entry["city"]] = entry
    listed = sorted(listed.values(), key=lambda x: x["site_id"])

    # What each operator's other records look like, worked out before any of them is
    # resolved.
    #
    # Whether a loosely-written record is a site of its own or a sloppy rendering of one
    # we can already place depends on the operator's *other* locations -- and resolving
    # in a single pass makes that depend on alphabetical order. "Plaza Servicios
    # Logisticos - Aragon" sorts ahead of "Plaza Zaragoza Servicios Logisticos -
    # Zaragoza", so a single pass reaches the region-shaped record first, sees no
    # sibling, and coins a delivery point called Aragon that no rate card prices.
    #
    # So the operator index is built first and is order-independent.
    family_locations = {}
    for raw_value in all_raw:
        operator, location = split_operator_location(raw_value)
        token = normalise(location)
        pinned = None
        if token and token not in C.RESOLVE["PLACEHOLDER_TOKENS"]:
            exact = [s for s in listed if s["city"] == token]
            if exact:
                pinned = exact[0]
            else:
                near = sorted(((city_similarity(token, s["city"]), s) for s in listed),
                              key=lambda t: (-t[0], t[1]["site_id"]))
                if near and near[0][0] >= C.RESOLVE["AUTO_MATCH_RATIO"]:
                    pinned = near[0][1]
        family_locations.setdefault(family(operator), []).append({
            "raw": raw_value, "location": location, "token": token, "pinned": pinned,
            "regional": token in C.RESOLVE["REGION_HINTS"],
            "pallets": volume.get(raw_value, {"pallets": 0})["pallets"],
        })

    def sibling_site(operator, raw_value, ctx):
        """The best site another record from this operator already points at, if any.

        A sibling the client's own list names outranks one only seen in the data, and a
        specific town outranks a region -- so a region-shaped record merges into its
        operator's real warehouse rather than the reverse.
        """
        others = [s for s in family_locations.get(family(operator), [])
                  if s["raw"] != raw_value and s["token"]
                  and s["token"] not in C.RESOLVE["PLACEHOLDER_TOKENS"]]
        if not others:
            return None
        ranked = sorted(others, key=lambda s: (s["pinned"] is None, s["regional"],
                                               -s["pallets"], s["raw"]))
        best = ranked[0]
        if best["pinned"]:
            p = best["pinned"]
            # The listed site's own ID, not one derived from its name. Two rows naming
            # the same warehouse under different IDs would split its cargo into two
            # pools, and nothing downstream would notice.
            return (p["site_id"], p["site"], p["country"],
                    "your own delivery records" if p.get("from_data")
                    else "your site list")
        if best["regional"]:
            return None
        label = best["location"].strip()
        return (_site_id(label), label, ctx["country"],
                "the rest of this operator's records")

    rows, queue = [], []
    for raw_value in all_raw:
        operator, location = split_operator_location(raw_value)
        token = normalise(location)
        vol = volume.get(raw_value, {"pallets": 0, "groups": 0})
        share = vol["pallets"] / total_pallets
        ctx = context.get(raw_value, {"pod": "", "country": ""})
        vol_note = (f"{vol['pallets']:,} pallets across {vol['groups']} shipment groups "
                    f"({share:.1%} of in-scope volume)")

        # --- the address is not an address ------------------------------------
        if token in C.RESOLVE["PLACEHOLDER_TOKENS"] or token == "":
            siblings = [r for r in rows if family(r["_operator"]) == family(operator)]
            sites = ([siblings[0]["Site_Name"]] if siblings else []) + sorted(
                {r["Site_Name"] for r in rows}
                - ({siblings[0]["Site_Name"]} if siblings else set()))
            options = [_deliver_to(s) for s in sites] + [EXCLUDE]
            values = {_deliver_to(s): s for s in sites}
            kinds = {o: "site" for o in values}
            kinds[EXCLUDE] = "exclude"
            queue.append(QueueItem(
                kind="site", rule="not_a_place", key=raw_value,
                question=f"'{location or '(blank)'}' is not a place. Where does this cargo go?",
                proposal=options[0],
                options=options, values=values, kinds=kinds,
                confidence="LOW",
                evidence=(f"The address field holds '{location or '(blank)'}'. "
                          + (f"Every other {operator.split()[0]} record delivers to "
                             f"{siblings[0]['Site_Name']}, which is the basis for the proposal."
                             if siblings else
                             "No other record from this operator gives a location either.")),
                volume_note=vol_note))
            # The proposal is written into the mapping as well, at LOW confidence,
            # so a run that accepts the engine's recommendations still costs this
            # cargo instead of dropping it. Answering the queue overrides it.
            if siblings:
                s = siblings[0]
                rows.append(_site_row(raw_value, operator, s["Site_ID"], s["Site_Name"],
                                      s["Site_Country"], "LOW",
                                      f"Address field held '{location or '(blank)'}'. "
                                      f"Proposed {s['Site_Name']} pending review."))
            continue

        # --- the client's own list names it ------------------------------------
        exact = [s for s in listed if s["city"] == token]
        if exact:
            s = exact[0]
            rows.append(_site_row(
                raw_value, operator, s["site_id"], s["site"], s["country"], "HIGH",
                "Named on your site list." if not s.get("from_data") else
                f"Identified from your own file — {s['groups']} shipment groups "
                "deliver here."))
            continue

        near = sorted(((city_similarity(token, s["city"]), s) for s in listed),
                      key=lambda t: (-t[0], t[1]["site_id"]))
        if near and near[0][0] >= C.RESOLVE["AUTO_MATCH_RATIO"]:
            score, s = near[0]
            rows.append(_site_row(raw_value, operator, s["site_id"], s["site"], s["country"],
                                  "HIGH", f"Spelling variant of {s['site']} ({score:.0%} match)."))
            continue

        # --- the engine could not pin this location ----------------------------
        #
        # Everything that reaches here failed to resolve, and the reason does not
        # matter to whether it escalates: a place the client never listed, a county
        # covering several delivery points, a town in a country we know nothing
        # about. Asking "is this a region?" first -- and passing anything
        # unrecognised through as a town -- is how a location gets silently
        # mis-resolved. So the test is whether it could be pinned, and the
        # region hint below only sharpens the question once it is already being
        # asked.
        # No country claimed. See sites_from_data: the file's only country is the
        # discharge port's, and a site the list does not name is exactly the one we have
        # no country for.
        site_label = location.strip()
        looks_regional = token in C.RESOLVE["REGION_HINTS"]
        # One option, not two. "Treat as a single site" and "Add as a new site" used to
        # sit side by side and resolved to exactly the same mapping: deciding a string
        # names one delivery point *is* adding a site, so offering it twice asked the
        # reviewer to pick between two spellings of one answer. Where the string reads
        # like an area the engine records the caveat itself, below.
        as_new = f"Deliver to a new site: {site_label}"

        # Escalate if it carries real volume, or if it reads like a region whatever its
        # volume. A region-level record is worth confirming even on thin volume, because
        # the consequence is a delivery rate that is an area average rather than a site
        # rate -- and that is wrong by the same proportion however little cargo it moves.
        #
        # Asked once per site, not once per spelling. Two variants of the same place
        # resolve to the same label, so confirming it twice is a chore with no answer
        # attached to it.
        already_asked = any(q.kind == "site" and q.proposal.endswith(site_label)
                            for q in queue)
        # Where the same operator has another record pointing at a real place, that is
        # worth leading with. "Plaza Servicios Logisticos - Aragon" alongside "Plaza
        # Zaragoza Servicios Logisticos - Zaragoza" is almost certainly the same
        # warehouse written loosely, and coining a region-shaped site instead invents a
        # delivery point no rate card prices. The reviewer can still say no -- both
        # readings stay on the list.
        sibling = sibling_site(operator, raw_value, ctx)

        if (share >= C.RESOLVE["UNLISTED_SITE_PALLET_SHARE"] or looks_regional) \
                and not already_asked:
            # Every option is a destination, phrased the same way, and exactly one of
            # them can be true. A pinned sibling leads where there is one, because it is
            # the only option backed by evidence: an existing delivery point this string
            # probably names.
            known = ([sibling[1]] if sibling else []) + [
                s["site"] for s in listed
                if s["country"] == ctx["country"] and (not sibling or s["site"] != sibling[1])]
            options = ([_deliver_to(sibling[1])] if sibling else []) + [as_new] + [
                _deliver_to(s) for s in known[1:] if sibling] + [
                _deliver_to(s) for s in known if not sibling] + [EXCLUDE]
            values = {_deliver_to(s): s for s in known}
            values[as_new] = site_label
            kinds = {o: "site" for o in values}
            kinds[as_new] = "new_site"
            kinds[EXCLUDE] = "exclude"
            hint = ("" if not looks_regional else
                    f" '{location.strip()}' also reads like a county or province rather "
                    "than a town, so it may cover more than one delivery point — in which "
                    "case the delivery rate here is an area average, not a site rate.")
            sibling_note = ("" if not sibling else
                            f" The same operator also delivers to {sibling[1]}, "
                            f"according to {sibling[3]}, which is why it leads.")
            queue.append(QueueItem(
                kind="site", rule="location_not_pinned", key=raw_value,
                question=(f"We cannot pin '{location.strip()}' to a site. "
                          "Where does this cargo go?"),
                proposal=options[0], options=options, values=values, kinds=kinds,
                confidence="MEDIUM",
                evidence=(f"{vol['pallets']:,} pallets discharge at {ctx['pod']} and "
                          "deliver here, but nothing "
                          + ("on your site list" if have_list else "else in your file")
                          + f" matches '{location.strip()}', and no spelling variant "
                          "comes close. Whether this is a distinct warehouse decides "
                          "what cargo may share a container with it."
                          + hint + sibling_note),
                volume_note=vol_note, area_named=looks_regional))
            # The proposal is written into the mapping too, so a run that accepts the
            # engine's recommendations costs this cargo the way the screen says it will.
            if sibling:
                site_id, name, country, basis = sibling
                rows.append(_site_row(raw_value, operator, site_id, name,
                                      country, "MEDIUM",
                                      f"Could not be pinned; proposed {name} because the "
                                      f"same operator delivers there according to {basis}. "
                                      "Sent for review."))
            else:
                rows.append(_site_row(raw_value, operator, _site_id(site_label), site_label,
                                      ctx["country"], "MEDIUM",
                                      "Could not be pinned to a known site; identified "
                                      "from the data and sent for review."
                                      + (" Reads like a region." if looks_regional else "")))
        else:
            rows.append(_site_row(raw_value, operator, _site_id(site_label), site_label, ctx["country"],
                                  "MEDIUM",
                                  f"Could not be pinned to a known site; identified from "
                                  f"the data ({share:.1%} of volume, below the review "
                                  "threshold)."
                                  + (" Reads like a region." if looks_regional else "")))

    # --- one operator, two locations -------------------------------------------
    # Checked after the fact, because it is a property of the resolved set rather
    # than of any single string.
    by_family = {}
    for r in rows:
        by_family.setdefault(family(r["_operator"]), set()).add(r["Site_Name"])
    for fam, names in sorted(by_family.items()):
        if len(names) < 2 or not fam:
            continue
        ordered = sorted(names)
        # Two answers to one question -- is this one warehouse or several? -- and the
        # options say which, rather than naming the operation the model would perform.
        separate = "Different places — keep them separate"
        one_place = f"One place — deliver all of it to {ordered[0]}"
        queue.append(QueueItem(
            kind="site", rule="operator_multi_city", key=fam,
            question=(f"'{fam.title()}' appears at {len(ordered)} locations. Is that one "
                      "warehouse or several?"),
            proposal=separate,
            options=[separate, one_place],
            values={one_place: ordered[0]},
            kinds={separate: "separate", one_place: "merge"},
            confidence="HIGH",
            evidence=("The same operator runs " + " and ".join(ordered) +
                      ". Separate sites is almost always right for a 3PL with several "
                      "warehouses, but merging them in error would let cargo for one "
                      "warehouse ride in a container bound for the other."),
            volume_note=", ".join(
                f"{n}: {sum(v['pallets'] for k, v in volume.items() if any(r['Site_Name'] == n and r['Delivery_Raw'] == k for r in rows)):,} pallets"
                for n in ordered)))

    site_df = pd.DataFrame(rows).drop(columns=["_operator"]) if rows else pd.DataFrame(
        columns=["Delivery_Raw", "Site_ID", "Site_Name", "Site_Country", "Confidence", "Note"])
    return site_df, queue


def _site_row(raw_value, operator, site_id, site, country, confidence, note):
    return {"Delivery_Raw": raw_value, "Site_ID": site_id, "Site_Name": site,
            "Site_Country": country, "Confidence": confidence, "Note": note,
            "_operator": operator}


def _site_id(label):
    """``Venlo, NL`` -> ``NL_VENLO``; a bare ``Venlo`` -> ``VENLO``.

    A site named without a country is one the file never gave a country for, and
    prefixing it with the first two letters of its own name -- VE_VENLO -- would dress a
    gap up as a code.
    """
    city = re.sub(r"[^A-Za-z]", "", label.split(",")[0]).upper()
    if "," not in label:
        return city
    cc = re.sub(r"[^A-Za-z]", "", label.split(",")[-1]).upper()[:2]
    return f"{cc}_{city}"


_COUNTRY_CODES = {
    "Netherlands": "NL", "Germany": "DE", "United Kingdom": "UK", "Spain": "ES",
    "Italy": "IT", "Poland": "PL", "France": "FR", "Belgium": "BE",
}


def _country_code(country):
    return _COUNTRY_CODES.get(str(country).strip(), str(country).strip()[:2].upper())


# --------------------------------------------------------------------------------------
# Suppliers
# --------------------------------------------------------------------------------------
def resolve_suppliers(ship):
    """Map each supplier to the origin pickup region its charges price against.

    Only EXW cargo needs this: on FOB terms the supplier delivers to the port at
    their own cost, so there is no origin collection for us to price. The city in
    the shipper string is matched against the regions the rate structure knows. An
    office in another country cannot be matched, and is escalated rather than
    guessed -- putting an invented region into a costed model would break the
    provenance claim the whole model rests on.
    """
    scope = ship[ship["in_scope"] & ship["term"].eq("EXW")]
    total_pallets = max(1, int(scope["pallets"].sum()))

    city_to_region = {}
    for region in sorted(C.PICKUP_REGION_CITIES):
        for city in C.PICKUP_REGION_CITIES[region]:
            city_to_region[city] = region

    pairs = (scope.groupby(["shipper", "origin"])
             .agg(pallets=("pallets", "sum"), groups=("grp_key", "nunique"))
             .reset_index().sort_values(["shipper", "origin"]))

    def match_region(office):
        token = normalise(office)
        region = city_to_region.get(token)
        if region is not None:
            return region
        near = sorted(((ratio(token, city), city) for city in sorted(city_to_region)),
                      key=lambda t: (-t[0], t[1]))
        if near and near[0][0] >= C.RESOLVE["AUTO_MATCH_RATIO"]:
            return city_to_region[near[0][1]]
        return None

    # Resolved first, unresolvable second.
    #
    # Two passes rather than one, because the proposal for a supplier we cannot place
    # depends on where the rest of that warehouse's cargo is collected -- and in a
    # single pass that depends on alphabetical order. A procurement office whose name
    # happens to sort first would get a recommendation drawn from nothing, which is how
    # a German importer buying out of Qingdao ends up being offered a Vietnamese
    # collection region.
    rows, queue = [], []
    unplaced = []
    for r in pairs.to_dict("records"):
        _, office = split_operator_location(r["shipper"])
        cfs = str(r["origin"]).split(",")[0].strip()
        region = match_region(office)
        if region is None:
            unplaced.append((r, office, cfs))
            continue
        rows.append({
            "Shipper": r["shipper"], "CFS": cfs, "Pickup_City": office.title(),
            "Rate_Region": region, "Evidence_Type": "SHIPMENT_DATA",
            "Evidence": f"The shipper record places this supplier at {office}, "
                        f"which sits in the {region} pickup region.",
            "Confidence": "HIGH"})

    # Only regions this client actually collects from are worth offering. The engine's
    # gazetteer spans every origin it knows; a reviewer asked to place a supplier does
    # not want a list of continents they do not buy from, and a recommendation drawn
    # from that list is worse than no recommendation at all.
    regions_in_file = sorted({x["Rate_Region"] for x in rows})

    for r, office, cfs in unplaced:
        origin_country = str(r["origin"]).split(",")[-1].strip()
        share = r["pallets"] / total_pallets

        # The office is somewhere the origin rate structure does not reach. Propose
        # the region most of this warehouse's other cargo is collected from, and say
        # plainly that it is a proposal.
        counts = {}
        for x in rows:
            if x["CFS"] == cfs:
                counts[x["Rate_Region"]] = counts.get(x["Rate_Region"], 0) + 1
        candidates = regions_in_file or sorted(C.PICKUP_REGION_CITIES)
        proposal = (max(sorted(counts), key=lambda k: (counts[k], k))
                    if counts else candidates[0])
        # Where nothing else loads at this warehouse there is no basis for a proposal,
        # only a first entry in a list. Saying "this is the region most of your cargo
        # comes from" when no such cargo exists is a false claim on screen, and the
        # reviewer needs to know they are choosing from scratch.
        basis = (f"{proposal} is the region most other {cfs} cargo is collected from, "
                 "which is a starting point and not evidence."
                 if counts else
                 f"Nothing else in the file loads at {cfs}, so there is no basis for a "
                 f"recommendation — {proposal} is only the first region on the list, and "
                 "this one needs answering from your own knowledge.")
        queue.append(QueueItem(
            kind="supplier", rule="supplier_office_not_origin", key=r["shipper"],
            # One supplier can load at two different warehouses, and each is its own
            # decision -- the collection region for their Shanghai cargo says nothing
            # about their Yantian cargo.
            uid=f"supplier:{r['shipper']}:{cfs}",
            scope={"Shipper": r["shipper"], "CFS": cfs},
            question=f"This supplier is recorded at {office}, not in {origin_country}. "
                     f"Which region are the goods collected from for {cfs}?",
            # Shown as places, not as the identifiers the model uses. BINH_DUONG is our
            # key for a region; a reviewer reading it off a client-facing screen is
            # reading our database, and the mapping back is carried on the item so the
            # wording can be anything without the resolution depending on it.
            proposal=_collected_from(proposal),
            # Built from the proposal *and* the candidates: the proposal is not always one
            # of them, and a label with no value behind it resolves to the label itself --
            # which lands a display string in the mapping where a region key belongs, and
            # every origin rate for that supplier then fails to look up.
            options=[_collected_from(x) for x in
                     [proposal] + [c for c in candidates if c != proposal]],
            values={_collected_from(x): x for x in [proposal] + list(candidates)},
            kinds={_collected_from(x): "region" for x in [proposal] + list(candidates)},
            confidence="LOW",
            evidence=(f"'{office}' is a procurement office, not a factory: the cargo loads at "
                      f"{r['origin']}. No origin rate can be selected until the collection "
                      f"region is known. {basis}"),
            volume_note=(f"{int(r['pallets']):,} pallets across {int(r['groups'])} shipment "
                         f"groups ({share:.1%} of EXW volume)")))
        rows.append({
            "Shipper": r["shipper"], "CFS": cfs, "Pickup_City": office.title(),
            "Rate_Region": proposal, "Evidence_Type": "PROPOSED_PENDING_REVIEW",
            "Evidence": f"Office recorded at {office}, outside {origin_country}. "
                        f"Proposed {proposal} pending confirmation.",
            "Confidence": "LOW"})

    supplier_df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["Shipper", "CFS", "Pickup_City", "Rate_Region",
                 "Evidence_Type", "Evidence", "Confidence"])
    return supplier_df, queue


# --------------------------------------------------------------------------------------
def resolve(ship, site_list=None, site_mapping=None, supplier_mapping=None):
    """Resolve sites and suppliers, or accept mappings resolved on an earlier run.

    Handing back the two mapping files this produces skips the queue entirely, which
    is the honest version of "it gets faster": the judgement is recorded once and
    then reused, not re-litigated every run.
    """
    if site_mapping is not None and supplier_mapping is not None:
        sites, suppliers = site_mapping.copy(), supplier_mapping.copy()
        queue = []
        reused = True
    else:
        sites, site_queue = resolve_sites(ship, site_list)
        suppliers, supplier_queue = resolve_suppliers(ship)
        queue = site_queue + supplier_queue
        reused = False

    by_rule = {}
    for item in queue:
        by_rule[item.rule] = by_rule.get(item.rule, 0) + 1

    total_mappings = len(sites) + len(suppliers)
    stats = {
        "mappings_total": total_mappings,
        "escalated": len(queue),
        "auto_resolved": total_mappings - len(queue) if not reused else total_mappings,
        "by_rule": dict(sorted(by_rule.items())),
        "sites_resolved": int(sites["Site_ID"].nunique()) if len(sites) else 0,
        "delivery_strings": int(len(sites)),
        "suppliers_resolved": int(len(suppliers)),
        "low_confidence_mappings": int(
            (sites["Confidence"].eq("LOW").sum() if len(sites) else 0)
            + (suppliers["Confidence"].eq("LOW").sum() if len(suppliers) else 0)),
        "reused_prior_mappings": reused,
    }
    return Resolution(sites=sites, suppliers=suppliers, queue=queue,
                      auto_resolved=stats["auto_resolved"], stats=stats)


def apply_answers(resolution, answers):
    """Fold the reviewer's decisions back into the mappings.

    Every queue item already carries its proposal in the mapping, so accepting the
    engine's recommendations changes nothing and overriding one changes exactly the
    rows it touches. Whatever a reviewer decides, the mapping records who decided
    it -- ``REVIEWER_CONFIRMED`` for an accepted proposal, ``REVIEWER_OVERRIDE``
    for a changed one -- so the audit shows a human made the call, not the engine.

    ``answers`` maps a queue item's ``uid`` to the option chosen from its options.
    Items left unanswered keep their proposal.
    """
    sites = resolution.sites.copy()
    suppliers = resolution.suppliers.copy()
    dropped = []

    for item in resolution.queue:
        choice = answers.get(item.uid)
        if choice is None:
            continue
        confirmed = choice == item.proposal
        # The value the model applies, and what kind of answer this is. Read from the
        # item rather than parsed out of the option's wording, so the screen can say
        # anything and the resolution still knows exactly what was chosen.
        value = item.values.get(choice, choice)
        kind = item.kinds.get(choice, "")

        if item.rule == "supplier_office_not_origin":
            # Matched on the decision's own scope, not on the supplier name. The same
            # supplier can hold a separate mapping per warehouse, and a name-only match
            # would apply this answer to a warehouse the reviewer was never asked about.
            mask = pd.Series(True, index=suppliers.index)
            for column, wanted in item.scope.items():
                mask &= suppliers[column].eq(wanted)
            suppliers.loc[mask, "Rate_Region"] = value
            suppliers.loc[mask, "Confidence"] = "MEDIUM" if confirmed else "HIGH"
            suppliers.loc[mask, "Evidence_Type"] = (
                "REVIEWER_CONFIRMED" if confirmed else "REVIEWER_OVERRIDE")
            suppliers.loc[mask, "Evidence"] = (
                f"Reviewer set the collection region to {value} for a supplier recorded at "
                f"{item.key.rsplit(' - ', 1)[-1]}, loading at "
                f"{item.scope.get('CFS', 'this warehouse')}.")
            continue

        if item.rule == "operator_multi_city":
            if kind == "merge":
                target = value
                fam_rows = sites["Delivery_Raw"].map(
                    lambda v: family(split_operator_location(v)[0]) == item.key)
                keep = sites.loc[sites["Site_Name"].eq(target)].head(1)
                if len(keep):
                    sites.loc[fam_rows, "Site_ID"] = keep.iloc[0]["Site_ID"]
                    sites.loc[fam_rows, "Site_Name"] = target
                    sites.loc[fam_rows, "Site_Country"] = keep.iloc[0]["Site_Country"]
                    sites.loc[fam_rows, "Confidence"] = "HIGH"
                    sites.loc[fam_rows, "Note"] = (
                        f"Reviewer merged all {item.key.title()} locations into {target}.")
            continue

        # --- the remaining rules all resolve a single delivery string ----------
        mask = sites["Delivery_Raw"].eq(item.key)
        if kind == "exclude" or choice == EXCLUDE:
            dropped.append(item.key)
            sites = sites[~mask]
            continue
        # What the reviewer meant, and what the engine still has to say about it.
        #
        # The answer is one decision -- this string names this delivery point -- so it is
        # one option on screen. Where the string reads like a county rather than a town,
        # the doubt does not become a second option; it is recorded against the mapping,
        # because it is the engine's reservation about the name and not a question the
        # reviewer can settle by clicking a differently worded version of the same
        # answer. That distinction cost a question nobody could answer meaningfully.
        target = value
        confidence = "HIGH"
        meaning = ("is a delivery site in its own right" if kind == "new_site"
                   else "is the delivery site for this cargo")
        if getattr(item, "area_named", False) and kind == "new_site":
            confidence = "MEDIUM"
            meaning = (
                "is the delivery point for this cargo, though it reads as a county or "
                "province rather than a town — if it covers more than one warehouse, the "
                "delivery rate here is an area average rather than a site rate")
        existing = sites.loc[sites["Site_Name"].eq(target)].head(1)
        sites.loc[mask, "Site_Name"] = target
        sites.loc[mask, "Site_ID"] = (
            existing.iloc[0]["Site_ID"] if len(existing) else _site_id(target))
        if len(existing):
            sites.loc[mask, "Site_Country"] = existing.iloc[0]["Site_Country"]
        sites.loc[mask, "Confidence"] = confidence
        sites.loc[mask, "Note"] = f"Reviewer confirmed {target} {meaning}."

    stats = dict(resolution.stats)
    stats["answered"] = len([1 for i in resolution.queue if i.uid in answers])
    stats["excluded_by_reviewer"] = len(dropped)
    stats["low_confidence_mappings"] = int(
        (sites["Confidence"].eq("LOW").sum() if len(sites) else 0)
        + (suppliers["Confidence"].eq("LOW").sum() if len(suppliers) else 0))
    return Resolution(sites=sites, suppliers=suppliers, queue=resolution.queue,
                      auto_resolved=resolution.auto_resolved, stats=stats)


def apply_resolution(ship, resolution):
    """Attach the resolved site and pickup region to every shipment group."""
    ship = ship.copy()
    site_lut = resolution.sites.drop_duplicates("Delivery_Raw").set_index("Delivery_Raw")
    ship["site_id"] = ship["delivery_raw"].map(site_lut["Site_ID"])
    ship["site"] = ship["delivery_raw"].map(site_lut["Site_Name"])
    ship["site_country"] = ship["delivery_raw"].map(site_lut["Site_Country"])
    ship["site_confidence"] = ship["delivery_raw"].map(site_lut["Confidence"])

    # The consolidation warehouse follows the loading port.
    ship["cfs"] = ship["origin"].str.split(",").str[0].str.strip()

    # Pickup region is a property of the supplier AT a warehouse, not of the supplier.
    # A supplier shipping through two warehouses holds two mappings, and collapsing
    # them to one would apply one warehouse's collection region to the other's cargo.
    sup = resolution.suppliers.drop_duplicates(["Shipper", "CFS"])
    ship = ship.merge(
        sup[["Shipper", "CFS", "Rate_Region", "Confidence"]].rename(columns={
            "Shipper": "shipper", "CFS": "cfs",
            "Rate_Region": "pickup_region", "Confidence": "pickup_confidence"}),
        on=["shipper", "cfs"], how="left")

    # A group with no resolved site cannot be pooled, so it cannot be modelled.
    unresolved = ship["in_scope"] & ship["site_id"].isna()
    ship.loc[unresolved, "in_scope"] = False
    return ship
