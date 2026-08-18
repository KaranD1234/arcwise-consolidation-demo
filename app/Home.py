"""Arcwise Consolidation — the demo application.

Six steps: Data, References, Resolve, Settings, Build, Results.

The flow is the argument. A prospect drops in a messy charge-line export, watches the
engine read it, hands over whatever reference data they happen to have, settles the
handful of judgement calls the engine will not make on its own, sets the figures no
invoice can evidence, and watches the model run. Nothing on screen is pre-computed:
the engine genuinely runs against the file, which is why an assumption can be changed
and the answer moves.

Each step does one job, and findings are reported after the work rather than before it.
Step 2 asks for files; what the engine could and could not price out of them is reported
on the build ticker and on Results. An earlier version put that analysis on step 2, where
it read as configuration to study instead of output to react to -- eight cards of prose
in front of a prospect who only wanted to know which files to send.

Run it with ``./run.sh`` from the project root.
"""

import html
import importlib
import io
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import charts                      # noqa: E402
import components as UI            # noqa: E402
import theme as T                  # noqa: E402

import config as C                 # noqa: E402
import explain as explain_mod      # noqa: E402
import ingest as ingest_mod        # noqa: E402
import rates as rates_mod          # noqa: E402
import resolve as resolve_mod      # noqa: E402
import run as engine               # noqa: E402
import sourcing as sourcing_mod    # noqa: E402
import workbook as workbook_mod    # noqa: E402

# Streamlit re-executes this file when source changes, but Python normally keeps modules
# imported by it in memory.  That can leave a live demo with a new Home.py talking to an
# old engine/config.py or old chart logic until the server is restarted.  Reload the
# small local calculation and presentation layer as one unit on each script rerun so a
# live demo can never mix releases.  All cross-engine imports are module imports, so
# reloading these objects updates the references held by their consumers as well.
for _engine_module in (
        C, sourcing_mod, resolve_mod, rates_mod, ingest_mod,
        sys.modules["pallets"], sys.modules["pack"], sys.modules["costing"],
        sys.modules["leadtime"], sys.modules["reconcile"], explain_mod,
        engine, workbook_mod, charts):
    importlib.reload(_engine_module)

DATA = ROOT / "data"


@st.cache_data(show_spinner=False)
def scenarios():
    """The demo datasets, as written by the generator.

    Three invented importers whose forwarders bill with different levels of detail. The
    app has no per-scenario code at all: References works out what each file can and
    cannot price, so switching dataset changes what it asks for because the *data*
    differs. That is the property worth demonstrating, and it only holds if nothing here
    knows which answer to expect.
    """
    path = DATA / "scenarios.json"
    if not path.exists():
        return {"default": None, "scenarios": []}
    return json.loads(path.read_text())


def scenario_dir(scenario_id):
    return DATA / scenario_id


# Every file this app can take, in one list.
#
# The whole of step 2 is rendered from this. A person arriving at the References step is
# asking one question -- *what files do you want from me?* -- and the answer has to be a
# short list they can read in one go, with each row saying plainly what is in that file
# and whether we already have it.
#
# Four rows, grouped the way a forwarder quotes rather than the way the engine reads. The
# two road legs at the doors are one document, because they are one kind of charge and
# one billing habit. The port-to-port tariff and everything charged at a quay are
# another. The consolidation quote is not a rate card at all -- it prices work never
# bought -- and keeping it separate is what lets the answer claim every dollar is
# evidenced without claiming any of it is invoiced. The trailer tender is the optional
# fourth.
#
# There is no site list here any more. Every warehouse a client delivers to is already
# named, hundreds of times, in the file they have just handed over; asking them to list
# their own sites was asking for something we could read. See resolve.sites_from_data.
#
# ``components`` is the legs a file can price, so a row can name exactly which of them is
# still unpriced. ``covers`` is (category, charge code) rather than category alone,
# because the split is by code: origin collection and origin THC share a category and sit
# on different documents.
def _card_codes(*component_keys):
    """The (category, code) pairs a component's own card source would match."""
    out = set()
    for key in component_keys:
        for src in C.COMPONENTS_BY_KEY[key]["sources"]:
            if src["kind"] == "card":
                out |= {(src["category"], code) for code in src["codes"]}
    return out


DOCUMENTS = [
    {"file": "door_charges.csv", "name": "Door charges", "kind": "rates",
     "holds": "Collection from your suppliers, and delivery from the discharge port.",
     "components": ("origin_collection", "destination_delivery"),
     # 1602 is a road move too, and only ever an analogue for the warehouse run.
     "covers": _card_codes("origin_collection", "destination_delivery")
               | {("ORIGIN_COMPONENT", "1602")}},
    {"file": "port_and_ocean.csv", "name": "Port and ocean", "kind": "rates",
     "holds": "Ocean freight per lane, plus terminal handling and export documents at "
              "both ends.",
     "components": ("ocean_freight", "origin_terminal", "destination_terminal"),
     "covers": _card_codes("ocean_freight", "origin_terminal", "destination_terminal")
               | {("OTHER", code) for code in ("1600", "1601", "1620")}},
    {"file": "consolidation_quote.csv", "name": "Consolidation quote", "kind": "rates",
     "holds": "Your forwarder's price for the warehouse work: receiving, handling, the "
              "run to the port, storage, and the strip at the far end.",
     "components": ("warehouse_handling", "warehouse_to_port", "warehouse_storage"),
     "covers": {("CONSOLIDATION", code)
                for code in rates_mod.service_codes().values()}},
    # The only genuinely optional file, and the one place a tender is raised. Without it
    # the model buys the inbound leg the way the client buys it today -- one collection per
    # shipment -- so the ask sits here, beside the uploader that answers it, and never in
    # the summary of an answer that does not use it.
    {"file": "ftl_rate_card.csv", "name": "Trailer tender", "kind": "rates",
     "holds": "A haulier's price per full trailer load, by pickup region. Without one "
              "we cost the leg the way you buy it today.",
     "components": (),
     "covers": {("FTL", "INBOUND_FTL")}},
]
DOCS_BY_FILE = {d["file"]: d for d in DOCUMENTS}

# One file carrying every rate document above except the trailer tender. The shortcut for a
# demo that does not need to dwell on the sequence.
PACK_FILE = "reference_pack.csv"

# How a category on an uploaded file maps back to the document it belongs to, so the app
# can name what it has just been given rather than making the user tell it.
CATEGORY_DOC = {key: d["name"] for d in DOCUMENTS for key in d["covers"]}

T.configure_page()
T.inject()

S = st.session_state
S.setdefault("step", "data")
S.setdefault("charge_bytes", None)
S.setdefault("charge_name", None)
S.setdefault("rate_card_bytes", None)
S.setdefault("rate_card_name", None)
S.setdefault("site_list_bytes", None)
S.setdefault("site_list_name", None)
S.setdefault("answers", {})
S.setdefault("overrides", {})
S.setdefault("service_pricing", {})
S.setdefault("result", None)
S.setdefault("build_log", [])
S.setdefault("scenario", None)
S.setdefault("loaded_refs", [])
S.setdefault("last_read", None)
S.setdefault("ref_round", 0)      # bumped to hand step 2 a fresh, empty uploader
S.setdefault("upload_errors", [])
S.setdefault("kept_rates", {})    # a quoted figure held while our benchmark is shown

# Regenerated sample files have their own contract too. If an open browser tab is holding
# an older seeded sample, replace it with that scenario's current bytes and return to the
# first step. Real client uploads have no scenario id and are never touched.
DEMO_DATA_VERSION = "classified-codes-useful-marginal-v1"
if S.get("demo_data_version") != DEMO_DATA_VERSION and S.scenario:
    _sample_charge = scenario_dir(S.scenario) / "charge_lines_raw.csv"
    if _sample_charge.exists() and _sample_charge.read_bytes() != S.charge_bytes:
        S.charge_bytes = _sample_charge.read_bytes()
        S.rate_card_bytes = S.rate_card_name = None
        S.site_list_bytes = S.site_list_name = None
        S.loaded_refs, S.last_read = [], None
        S.answers, S.overrides, S.service_pricing = {}, {}, {}
        S.result, S.build_log = None, []
        S.step = "data"
S.demo_data_version = DEMO_DATA_VERSION

# Results live in Streamlit's session state across code reloads.  When the shape or the
# meaning of an engine result changes, an open browser tab can otherwise try to render
# the old object with the new UI (the lane-rule rollout, for example, added two config
# keys and changed lanes from country level to destination-site level).  Version that
# contract explicitly and rebuild stale results instead of letting the final page fail.
RESULT_SCHEMA_VERSION = "warehouse-population-v4"
if S.get("result_schema_version") != RESULT_SCHEMA_VERSION:
    S.result, S.build_log = None, []
    if S.step == "results" and S.charge_bytes:
        S.step = "build"
S.result_schema_version = RESULT_SCHEMA_VERSION


# --------------------------------------------------------------------------------------
# Cached engine calls. Keyed on file contents, so an interaction that changes nothing
# does not re-read a five-thousand-row file.
# --------------------------------------------------------------------------------------
def _to_temp(data, suffix=".csv"):
    fh = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    fh.write(data)
    fh.close()
    return fh.name


@st.cache_data(show_spinner=False)
def cached_ingest(charge_bytes):
    return ingest_mod.ingest(_to_temp(charge_bytes))


@st.cache_data(show_spinner=False)
def cached_frame(data):
    return pd.read_csv(io.BytesIO(data))


@st.cache_data(show_spinner=False)
def cached_resolution(charge_bytes, site_list_bytes):
    ingested = cached_ingest(charge_bytes)
    site_list = cached_frame(site_list_bytes) if site_list_bytes else None
    return resolve_mod.resolve(ingested.shipments, site_list=site_list)


def goto(step):
    S.step = step
    st.rerun()


def identify_scenario(charge_bytes):
    """If the dropped charge-line file is one of the sample datasets, say which.

    Nothing on screen depends on the answer: the engine reads the file it was given
    either way. It only means step 2 can offer that dataset's own reference files as a
    shortcut, instead of making a demo run hunt through folders for four more CSVs.
    Matched on contents, because all three ship under the same filename.
    """
    for entry in scenarios()["scenarios"]:
        path = scenario_dir(entry["id"]) / "charge_lines_raw.csv"
        if path.exists() and path.read_bytes() == charge_bytes:
            return entry["id"]
    return None


def merge_reference(frame, label):
    """Fold another reference file into the set we already hold.

    Concatenated rather than replacing, because that is what actually happens: a client
    sends their freight tariff in one mail and their origin schedule a week later, and the
    step has to improve rather than start again. Later rows win on a collision, so
    re-sending a corrected file does what the sender expects.
    """
    existing = cached_frame(S.rate_card_bytes) if S.rate_card_bytes else None
    merged = (pd.concat([existing, frame], ignore_index=True)
              if existing is not None else frame)
    merged = merged.drop_duplicates(subset=["Category", "Ch_Code", "Node_From", "Node_To"],
                                    keep="last")
    S.rate_card_bytes = merged.to_csv(index=False).encode()
    S.loaded_refs = sorted(set(S.loaded_refs) | {label})
    S.rate_card_name = " + ".join(S.loaded_refs)
    # What arrived, named by the documents its categories belong to, so the next render
    # can confirm what was understood rather than leaving the user to infer it.
    pairs = {(str(r["Category"]).strip(), str(r["Ch_Code"]).strip())
             for r in frame[["Category", "Ch_Code"]].to_dict("records")}
    docs = sorted({CATEGORY_DOC[pair] for pair in pairs if pair in CATEGORY_DOC})
    note_read(docs or [label], int(len(frame)))
    S.result = None
    # No st.rerun() here. This runs from a button callback as often as not, where a rerun
    # is a no-op and Streamlit says so out loud on screen; the callback and the uploader
    # both rerun on their own afterwards.


def note_read(docs, rates):
    """Remember what we just understood, adding to anything read in the same drop.

    Several files can arrive together, and each is read separately. Overwriting rather
    than adding meant a drop of four files confirmed only the last one.
    """
    if S.last_read:
        docs = sorted(set(S.last_read[0]) | set(docs))
        rates = S.last_read[1] + rates
    S.last_read = (sorted(docs), rates)


def add_reference(filename):
    """Load one of the current scenario's sample reference files."""
    path = scenario_dir(S.scenario) / filename
    take_reference_file(path.read_bytes(), filename)


def load_sample_references():
    """Everything the sample dataset ships except the trailer tender.

    The tender stays a separate click, because the engine noticing a rate is missing,
    pricing what it would be worth and then being handed one is the sequence worth
    watching -- and it cannot be watched if the file is already there.
    """
    add_reference(PACK_FILE)


def reset_refs():
    """Put step 2 back to empty, so the board can be shown cold a second time.

    The uploader's key moves rather than its contents being cleared: a dropped file stays
    in the widget across reruns, so the same files would be read straight back in and the
    reset would appear to do nothing. A new key is a new, empty uploader.
    """
    S.rate_card_bytes = S.rate_card_name = None
    S.site_list_bytes = S.site_list_name = None
    S.loaded_refs, S.last_read, S.result = [], None, None
    S.ref_round += 1
    st.rerun()


RATE_COLUMNS = {"Category", "Ch_Code", "Rate"}
SITE_COLUMNS = {"Site_ID", "Site_Name"}


def take_reference_file(data, name):
    """Take a file the user uploaded, and work out from its columns what it is.

    The step promises we will read the file and identify it, so it has to actually do
    that. An earlier version validated every upload against the rate-file columns, which
    meant handing it the site list -- one of the files it asks for by name -- produced a
    complaint that the site list was not a rate card.

    Returns a complaint to show, or None if the file was understood. It returns rather
    than calling ``st.error`` itself because this runs before the page is drawn, and an
    error raised there would land above the heading.
    """
    try:
        frame = pd.read_csv(io.BytesIO(data))
    except Exception as exc:
        return f"**{name}** could not be read as a CSV. {exc}"
    columns = set(frame.columns)

    if SITE_COLUMNS <= columns:
        S.site_list_bytes, S.site_list_name = data, name
        note_read(["Site list"], int(len(frame)))
        S.result = None
        return None
    if RATE_COLUMNS <= columns:
        merge_reference(frame, name)
        return None

    return (
        f"**{name}** does not look like either kind of file we take. A rate file needs "
        f"`Category`, `Ch_Code` and `Rate`; a site list needs `Site_ID` and `Site_Name`. "
        f"This one has: {', '.join(sorted(columns)[:8])}"
        + ("…" if len(columns) > 8 else ""))


def take_pending_uploads():
    """Read anything sitting in the uploader, before a single row of the step is drawn.

    Runs twice over, and has to be safe to: once as the uploader's ``on_change``, which
    Streamlit calls before the script body, and once from the top of the step, because a
    keyed widget's new value is already in session state by then. Either way the files
    are read *before* the rows are rendered. Reading them where the uploader is drawn --
    below the inventory -- meant a file's tick only appeared once something else forced a
    second rerun, so the confirmation always lagged one file behind.

    Re-reading is free: a file already taken is skipped, which is also what stops uploads
    accumulating across reruns from being merged again on every interaction.
    """
    errors = []
    for up in st.session_state.get(f"ref_any_{S.ref_round}") or []:
        if up.name in S.loaded_refs or up.name == S.site_list_name:
            continue
        error = take_reference_file(up.getvalue(), up.name)
        if error:
            errors.append(error)
    # A file we could not read stays in the dropzone, so its complaint is recomputed
    # every run rather than being shown once and lost.
    S.upload_errors = errors
    return errors


def nav(back=None, forward=None, forward_label="Continue", disabled=False,
        forward_note=""):
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    # Step 1 has nowhere to go back to, and holding the Back column open for it left the
    # primary button floating in the middle of the row with a gap to its left.
    cols = st.columns([1, 1, 5]) if back else st.columns([1, 6])
    if back:
        with cols[0]:
            if st.button("Back", use_container_width=True):
                goto(back)
    if forward:
        with cols[1 if back else 0]:
            if st.button(forward_label, type="primary", use_container_width=True,
                         disabled=disabled):
                goto(forward)
    if forward_note:
        with cols[-1]:
            UI.note(forward_note, cls="aw-micro", style="padding-top:9px;")


# --------------------------------------------------------------------------------------
# 1. Data
# --------------------------------------------------------------------------------------
def step_data():
    UI.eyebrow("Step 1 of 6")
    UI.h("Start with your charge lines", 2)
    UI.lede("Straight out of your billing system. No cleaning — messy is what the engine "
            "is built to read.")

    up = st.file_uploader("Charge-line export (CSV)", type=["csv"],
                          label_visibility="collapsed")
    if up is not None and up.getvalue() != S.charge_bytes:
        S.charge_bytes, S.charge_name = up.getvalue(), up.name
        S.rate_card_bytes = S.rate_card_name = None
        S.site_list_bytes = S.site_list_name = None
        S.loaded_refs, S.last_read = [], None
        S.answers, S.overrides, S.service_pricing = {}, {}, {}
        S.result, S.build_log = None, []
        S.scenario = identify_scenario(S.charge_bytes)

    if not S.charge_bytes:
        nav(forward=None)
        return

    ing = cached_ingest(S.charge_bytes)
    st_ = ing.stats
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    UI.eyebrow(f"What we read from {S.charge_name}")
    UI.profile_row([
        ("charge lines", f"{st_['charge_lines']:,}"),
        ("shipments", f"{st_['shipments']:,}"),
        ("shipment groups", f"{st_['shipment_groups']:,}"),
        ("invoices", f"{st_['invoices']:,}"),
        ("charge codes", f"{st_['charge_codes']}"),
        ("total invoiced", f"${st_['total_invoiced_usd'] / 1e6:,.2f}m"),
    ])
    UI.note(f"{st_['date_range'][0]} to {st_['date_range'][1]} &middot; "
            f"{len(st_['modes'])} transport modes &middot; "
            f"{len(st_['terms'])} shipping terms",
            cls="aw-micro", style="margin:-6px 0 16px 2px;")

    UI.eyebrow("What the engine had to deal with")
    for f in ing.findings:
        if f.narrate:
            UI.finding(f.headline)
    with st.expander("Everything else it found"):
        for f in ing.findings:
            if not f.narrate:
                UI.h(f.headline, 5, margin="10px 0 2px 0")
                UI.note(f.note)

    nav(forward="references")


# --------------------------------------------------------------------------------------
# 2. References
# --------------------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def cached_sourcing(charge_bytes, site_list_bytes, rate_card_bytes, service_pricing):
    """The sourcing verdict for every cost component, given what has been uploaded."""
    ing = cached_ingest(charge_bytes)
    res = cached_resolution(charge_bytes, site_list_bytes)
    ship = resolve_mod.apply_resolution(ing.shipments, res)
    card = cached_frame(rate_card_bytes) if rate_card_bytes else None
    return sourcing_mod.plan(
        ing.lines, ship, rates_mod.index_rate_card(card),
        service_pricing=dict(service_pricing),
        containers_today=int(ing.stats["containers_today"]))


def file_status(plan, card_index):
    """For each file we can take: do we have it, do we need it, or is it a nicety.

    ``needed`` means a cost the engine will otherwise refuse to price -- and refuse is
    literal: there is no benchmark of ours behind any of these. ``optional`` is left for
    files that improve the process rather than the answer. The engine works this out from
    what the charge lines can support, so the list changes with the dataset without
    anything here knowing which dataset it is looking at.
    """
    out = []
    for doc in DOCUMENTS:
        held = sum(1 for k in card_index if (k[0], k[3]) in doc["covers"])
        # Outstanding legs beat rates already read: a client who sends the ocean tariff
        # and nothing else should not see the row tick while its terminal charges are
        # still unpriced.
        stops = sorted(C.COMPONENTS_BY_KEY[key]["label"] for key in doc["components"]
                       if key in plan and plan[key].needs_rate)
        if stops:
            out.append((doc, "needed",
                        (f"{held} read. " if held else "")
                        + "Still unpriced: " + ", ".join(stops).lower()))
        elif held:
            out.append((doc, "given", f"{held} rate{'s' if held != 1 else ''} read"))
        else:
            out.append((doc, "optional", ""))
    return out


def step_references():
    """Take whatever reference files the client has, and say what is still missing.

    One job. Everything that is a *finding* -- which costs could not be priced, which
    charge code was bundled, what an FTL rate would have to beat -- is reported after the
    model runs, on the build ticker and the results screen, because that is what it is:
    output to react to, not configuration to understand. Putting it here made this step
    read like something you had to study before you were allowed to continue.
    """
    UI.eyebrow("Step 2 of 6")
    UI.h("What we can use from you", 2)

    # Before anything is drawn, so every row below reflects the files just dropped in.
    errors = take_pending_uploads()

    plan = cached_sourcing(S.charge_bytes, S.site_list_bytes, S.rate_card_bytes,
                           tuple(sorted(S.service_pricing.items())))
    card_index = rates_mod.index_rate_card(
        cached_frame(S.rate_card_bytes) if S.rate_card_bytes else None)
    rows = file_status(plan, card_index)
    priced = sum(1 for cs in plan.values() if not cs.needs_rate)
    unpriced = len(plan) - priced
    needed = [d for d, status, _ in rows if status == "needed"]

    # Which of the unpriced legs can only be fixed *here*.
    #
    # The consolidation service has a second route — the settings step takes those figures
    # typed in — so an outstanding service rate is not a reason to hold somebody on this
    # screen. A freight or delivery leg has no second route: no card, no price, no model.
    # Letting that walk on meant the engine stopped them three steps later, on the build,
    # in front of a file uploader they could no longer see.
    file_only = sorted(
        cs.label for cs in plan.values() if cs.needs_rate
        and not any(s["kind"] == "service"
                    for s in C.COMPONENTS_BY_KEY[cs.key]["sources"]))

    # One line, and it moves as files arrive. That movement is the most product-like
    # thing in the flow, so it is the one piece of the sourcing story worth keeping here.
    #
    # One line, singular: what we have just read and what is still missing are the same
    # question asked twice, and answering them in two stacked callouts put two green boxes
    # above a four-row list that was already saying it a third time.
    state = (f"<b>{priced} of {len(plan)}</b> costs priced, <b>{unpriced}</b> still need "
             "a file." if unpriced else f"All <b>{len(plan)}</b> costs priced.")
    tone = "ask" if unpriced else "ok"
    if S.last_read:
        docs, read = S.last_read
        S.last_read = None
        UI.summary_line(f"Read your <b>{UI.named(docs)}</b> — {read} rates. {state}", tone)
    else:
        UI.summary_line(state, tone)

    for doc, status, detail in rows:
        st.markdown(UI.file_row(doc, status, detail), unsafe_allow_html=True)

    # A single uploader for all of them. The files carry a Category column, so the engine
    # identifies what it has been given rather than asking the user to route it -- which
    # is also why three separate dropzones were the wrong shape.
    UI.note("Drop them in together or one at a time — we identify each file from its "
            "columns.", style="margin:16px 0 6px 2px;")
    st.file_uploader("Reference files (CSV)", type=["csv"],
                     key=f"ref_any_{S.ref_round}", on_change=take_pending_uploads,
                     label_visibility="collapsed", accept_multiple_files=True)
    for error in errors:
        st.error(error)

    cols = st.columns([1.5, 1.4, 1.2, 2])
    if S.scenario:
        with cols[0]:
            st.button("Load the sample files", use_container_width=True,
                      on_click=load_sample_references)
        with cols[1]:
            if (scenario_dir(S.scenario) / "ftl_rate_card.csv").exists():
                st.button("Add the trailer tender", use_container_width=True,
                          on_click=add_reference, args=("ftl_rate_card.csv",))
    if S.loaded_refs or S.site_list_bytes:
        with cols[2]:
            if st.button("Clear", use_container_width=True):
                reset_refs()

    if file_only:
        one = len(file_only) == 1
        UI.summary_line(
            f"<b>No price for {', '.join(file_only).lower()}.</b> You pay for "
            + ("it" if one else "them")
            + " today, so leaving it off both sides would flatter the saving. A rate card "
              "is the only fix.", tone="warn")

    nav(back="data", forward=None if file_only else "resolve",
        forward_note="Drop the file above in and this clears." if file_only else "")



# A readable heading for each escalation rule. Keys must track resolve.py's rules; a
# rule missing from here renders as its raw identifier, which is how a reviewer ends up
# reading "supplier_office_not_origin" off a client-facing screen.
# What each kind of answer commits the model to, shown under the one selected. Keyed by
# the engine's own classification of the option rather than by its wording, so improving
# a phrase on screen cannot quietly detach it from its explanation.
OPTION_MEANING = {
    "site": "Priced on that site's rates, and it may share that site's containers.",
    "new_site": "A site of its own, its own delivery rate, its own containers.",
    "merge": "One warehouse under two names. The records join.",
    "separate": "Different places. Separate rates, and never the same container.",
    "region": "Origin rates taken from this region's collection and handling charges.",
    "exclude": "Out of the model — no cargo, no cost, on either side.",
}

# This is a route back to pricing, not a destination value. It only exists in the UI and
# is never passed into the resolution engine as though it were a warehouse name.
MISSING_DESTINATION_RATE = "The correct destination isn't listed"


def _site_of(item, option):
    """The delivery site an answer resolves to, or None if it is not a destination."""
    if item.kinds.get(option) in ("site", "new_site"):
        return item.values.get(option)
    return None


def _priced_decision_options(item, unpriceable, current):
    """Keep unpriceable destinations out of the radio while preserving an honest exit.

    Resolution asks where the cargo really goes; it must not force a reviewer to choose a
    false, priced destination. Known sites without a usable lane rate are therefore shown
    as context below the control, while one non-destination choice sends the reviewer back
    to add the missing rate.
    """
    all_options = list(dict.fromkeys(item.options))
    hidden = [option for option in all_options
              if unpriceable.get((item.uid, option))]
    if not hidden:
        selected = current if current in all_options else item.proposal
        return all_options, selected if selected in all_options else all_options[0], hidden

    visible = [option for option in all_options if option not in hidden]
    insert_at = visible.index(resolve_mod.EXCLUDE) if resolve_mod.EXCLUDE in visible else len(visible)
    visible.insert(insert_at, MISSING_DESTINATION_RATE)

    # A no-rate site selected before this safer control was introduced becomes an explicit
    # request to add the missing rate. It must not silently jump to a different warehouse.
    selected = MISSING_DESTINATION_RATE if current in hidden else current
    if selected not in visible:
        selected = item.proposal if item.proposal in visible else visible[0]
    return visible, selected, hidden


@st.cache_data(show_spinner=False)
def cached_lane_prices(charge_bytes, site_list_bytes, rate_card_bytes, pairs):
    """For each port-to-warehouse lane an answer could create: can we price it?

    A delivery rate is per lane, not per site. Cargo discharging at Barcelona can be
    sent to a warehouse the card only prices from Valencia, and that lane then has no
    rate on the card and no invoice history to derive one from, because the combination
    has never happened. The engine refuses to cost it -- correctly -- but it did so on
    the build, two steps after the answer that caused it, naming a leg rather than the
    decision. Asked here instead, the answer can carry the warning.
    """
    ing = cached_ingest(charge_bytes)
    res = cached_resolution(charge_bytes, site_list_bytes)
    ship = resolve_mod.apply_resolution(ing.shipments, res)
    card = rates_mod.index_rate_card(
        cached_frame(rate_card_bytes) if rate_card_bytes else None)
    # Asked through the index's own lookup, never by matching its keys directly. The card
    # names a warehouse "Granollers, ES" and the file resolves it to "Granollers", so an
    # exact tuple test on the keys missed a lane the engine prices perfectly well -- and
    # since a stranded lane disables the Continue button, that turned a priced lane into a
    # dead end two steps before the build. The index is what costing asks; this has to ask
    # the same question the same way.
    return {pair: (card.get(("DEST_DELIVERY", pair[0], pair[1], C.DAP_RATE_CODE)) is not None
                   or rates_mod.derive_destination(ing.lines, ship, *pair) is not None)
            for pair in pairs}


def delivery_warnings(queue, ship):
    """Per decision, the options that would leave the delivery leg unpriced."""
    pods = {}
    for item in queue:
        if item.kind != "site":
            continue
        rows = ship[ship["delivery_raw"].eq(item.key) & ship["in_scope"]]
        pods[item.uid] = sorted(set(rows["pod"]))

    pairs = sorted({(pod, _site_of(item, o))
                    for item in queue if item.uid in pods
                    for o in item.options for pod in pods[item.uid]
                    if _site_of(item, o)})
    priced = cached_lane_prices(S.charge_bytes, S.site_list_bytes, S.rate_card_bytes,
                                tuple(pairs))
    out = {}
    for item in queue:
        if item.uid not in pods:
            continue
        for option in item.options:
            site = _site_of(item, option)
            if not site:
                continue
            blind = [pod for pod in pods[item.uid] if not priced.get((pod, site), True)]
            if blind:
                out[(item.uid, option)] = blind
    return out


RULE_LABEL = {
    "not_a_place": "Address is not a place",
    "location_not_pinned": "Location could not be pinned to a site",
    "operator_multi_city": "One operator, several locations",
    "supplier_office_not_origin": "Supplier office is not the origin",
}


def step_resolve():
    UI.eyebrow("Step 3 of 6")
    res = cached_resolution(S.charge_bytes, S.site_list_bytes)
    rs = res.stats

    UI.h("A few things we will not guess", 2)
    UI.lede(f"<b>{rs['auto_resolved']} of {rs['mappings_total']}</b> mappings resolved "
            f"automatically. These {len(res.queue)} need you, each with a recommendation "
            "already selected.")

    if not res.queue:
        UI.card("Nothing to review",
                "Every mapping resolved on its own evidence.")

    ing = cached_ingest(S.charge_bytes)
    unpriceable = delivery_warnings(res.queue, ing.shipments)
    awaiting_destination_rate = []

    for item in res.queue:
        # Keyed so the stylesheet can reach it; see theme.py.
        with st.container(border=True, key=f"decision-{item.uid}"):
            head, badge = st.columns([5, 1])
            with head:
                st.markdown(
                    f"<div class='aw-eyebrow'>{RULE_LABEL.get(item.rule, item.rule)}</div>"
                    f"<div style='font-size:14px;font-weight:500;color:{T.INK_700};"
                    f"margin:2px 0 4px 0;'>{item.question}</div>"
                    f"<div class='aw-mono'>{item.key}</div>",
                    unsafe_allow_html=True)
            with badge:
                st.markdown(
                    f"<div style='text-align:right;padding-top:4px;'>"
                    f"{UI.confidence(item.confidence)}</div>",
                    unsafe_allow_html=True)

            current = S.answers.get(item.uid, item.proposal)
            options, current, hidden_options = _priced_decision_options(
                item, unpriceable, current)
            # Keyed on the decision's uid, not its label. Two decisions can share a
            # label -- one supplier loading at two warehouses -- and Streamlit rejects
            # duplicate widget keys, so a label-keyed radio crashes on that data.
            # Also clear a selection made against the old option list. Streamlit retains
            # widget state across reruns; without this guard a newly hidden no-rate site,
            # or the add-a-rate route after its rate arrives, could survive invisibly.
            radio_key = f"q_{item.uid}"
            if st.session_state.get(radio_key) not in (None, *options):
                st.session_state[radio_key] = current
            choice = st.radio(
                "Decision", options,
                index=options.index(current) if current in options else 0,
                key=radio_key, label_visibility="collapsed", horizontal=False)
            if choice == MISSING_DESTINATION_RATE:
                # Do not let this UI-only route leak into the mapping as a made-up site.
                S.answers.pop(item.uid, None)
                awaiting_destination_rate.append(item.key)
                UI.note("Add the correct destination lane to your rate card on step 2. "
                        "Once it has a rate, the destination will appear here.",
                        style="margin:-6px 0 6px 26px;")
            else:
                S.answers[item.uid] = choice
                consequence = OPTION_MEANING.get(item.kinds.get(choice, ""), "")
                if consequence:
                    UI.note(consequence, style="margin:-6px 0 6px 26px;")

            if hidden_options:
                hidden_sites = sorted({_site_of(item, option) or option
                                       for option in hidden_options})
                blind_pods = sorted({pod for option in hidden_options
                                     for pod in unpriceable.get((item.uid, option), [])})
                UI.note(
                    f"Not offered because no delivery rate is available from "
                    f"{', '.join(blind_pods)}: {', '.join(hidden_sites)}.",
                    cls="aw-micro", style="margin:-2px 0 8px 26px;")

            st.markdown(
                f"<div class='aw-quote' style='margin-top:6px;'>{item.evidence}"
                + (f"<br/><span style='color:{T.INK_400};'>{item.volume_note}</span>"
                   if item.volume_note else "")
                + "</div>", unsafe_allow_html=True)

    if res.queue and not awaiting_destination_rate:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        applied = resolve_mod.apply_answers(res, S.answers)
        c1, c2, _ = st.columns([1.1, 1.1, 3])
        with c1:
            st.download_button(
                "Site mapping (CSV)",
                applied.sites.to_csv(index=False).encode(),
                "site_mapping.csv", "text/csv", use_container_width=True)
        with c2:
            st.download_button(
                "Supplier mapping (CSV)",
                applied.suppliers.to_csv(index=False).encode(),
                "supplier_mapping.csv", "text/csv", use_container_width=True)
        UI.note("Hand these back next time and this step is skipped.", cls="aw-micro",
                style="margin-top:4px;")

    if awaiting_destination_rate:
        UI.summary_line(
            "<b>The correct destination needs a rate.</b> Add its delivery lane to your "
            "rate card on step 2, then return here. Or leave this cargo out of the model.",
            tone="warn")

    nav(back="references", forward=None if awaiting_destination_rate else "assumptions",
        forward_note=("Add the rate on step 2, then return here."
                      if awaiting_destination_rate else ""))


# --------------------------------------------------------------------------------------
# 4. Assumptions
# --------------------------------------------------------------------------------------
def _step_for(value, whole):
    """How much one press of the stepper should move a figure.

    A whole-number constant steps by one whatever its size. Sizing the step by magnitude
    alone made "days from last pallet ready to sailing" -- a 1, displayed to no decimal
    places -- step by 0.05, so pressing the button changed the value and not the number
    on screen. The field read as locked.
    """
    if whole:
        return 1.0
    return 0.05 if abs(float(value)) < 5 else (1.0 if abs(float(value)) < 100 else 25.0)


def _num_input(key, label=None, fmt="%.2f"):
    """A number input bound to an override, typed like the constant it edits."""
    meta = C.CONFIG[key]
    whole = isinstance(meta["value"], int)
    label = label or f"{meta['label']} ({meta['unit']})"
    val = float(S.overrides.get(key, meta["value"]))
    new = st.number_input(label, value=val, step=_step_for(val, whole), min_value=0.0,
                          key=f"cfg_{key}", format=fmt)
    S.overrides[key] = int(new) if whole else new
    return S.overrides[key]


def _note(text, colour=None):
    st.markdown(
        f"<div style='font-size:11px;color:{colour or T.INK_400};line-height:1.5;"
        f"margin:-10px 0 14px 0;'>{text}</div>", unsafe_allow_html=True)


def step_assumptions():
    UI.eyebrow("Step 4 of 6")
    UI.h("What we know, and what you have to tell us", 2)
    UI.lede("Everything so far came out of your data. These are the choices.")

    # --- paired caps and their dispatch targets --------------------------------
    UI.eyebrow("Container limits, and when a box is full enough to send")
    for pair in C.LIMIT_PAIRS:
        cap_meta = C.CONFIG[pair["max"]]
        pct_meta = C.CONFIG[pair["pct"]]
        c1, c2, c3 = st.columns([1.15, 1.15, 1.7])
        with c1:
            _num_input(pair["max"], f"{cap_meta['label']} ({pair['unit']})",
                       fmt="%.1f" if pair["decimals"] else "%.0f")
        with c2:
            current = float(S.overrides.get(pair["pct"], pct_meta["value"])) * 100
            pct = st.slider("Dispatch target", min_value=40, max_value=100,
                            value=int(round(current)), step=1,
                            key=f"cfg_{pair['pct']}", format="%d%%")
            S.overrides[pair["pct"]] = pct / 100.0
        with c3:
            cfg_now = C.values(S.overrides)
            st.markdown(
                f"<div class='aw-num' style='padding-top:26px;font-size:13px;"
                f"font-weight:500;color:{T.INK_700};'>"
                f"{C.describe_pair(cfg_now, pair)}</div>"
                f"<div class='aw-micro' style='margin-top:3px;'>"
                f"{pct_meta['source']}</div>",
                unsafe_allow_html=True)

    cols = st.columns(3)
    with cols[0]:
        _num_input("OUT_WEIGHT_MAX_KG", "Outbound container payload cap (kg)", fmt="%.0f")
        _note("A limit, not a target. Nothing sails because it is heavy enough.")

    # --- operating choices ----------------------------------------------------
    #
    card_index = rates_mod.index_rate_card(
        cached_frame(S.rate_card_bytes) if S.rate_card_bytes else None)

    # Folded away, because these are the ones a room never asks about and the container
    # limits are the ones it always does. The body of an expander runs whether or not it is
    # open, so every widget below still exists and still holds its value -- which is why
    # this is an expander and not an `if show:`.
    with st.expander("Operating choices — dwell, pooling, the day a box sails"):
        cols = st.columns(3)
        with cols[0]:
            _num_input("MAX_DWELL_DAYS", "Maximum warehouse dwell (days)", fmt="%.0f")
            _note(C.CONFIG["MAX_DWELL_DAYS"]["source"])
        with cols[1]:
            opts = ["cfs_pod_site", "cfs_pod"]
            labels = {"cfs_pod_site": "One site per container",
                      "cfs_pod": "Sites may mix, countries never"}
            val = S.overrides.get("POOL_KEY", C.CONFIG["POOL_KEY"]["value"])
            S.overrides["POOL_KEY"] = st.selectbox(
                C.CONFIG["POOL_KEY"]["label"], opts, index=opts.index(val),
                format_func=lambda v: labels[v], key="cfg_POOL_KEY")
            _note(C.CONFIG["POOL_KEY"]["source"])
        with cols[2]:
            _num_input("CFS_TO_VESSEL_DAYS", fmt="%.0f")
            _note(C.CONFIG["CFS_TO_VESSEL_DAYS"]["source"])

    # --- how much fits on one inbound truck -----------------------------------
    #
    # Not an FTL setting, which is what the heading here used to imply. These caps decide
    # how many separate deliveries the warehouse has to unload, and receiving is charged
    # per delivery -- so they price real money on a file with no tender anywhere near it.
    # On Meritt, tightening the trailer from 66 pallets to 33 turns 7 arrivals into 14 and
    # takes $910 of receiving to $1,820.
    #
    # What changes with a tender on file is what *else* they decide, so the line inside
    # says one thing or the other rather than describing a comparison that is not running.
    has_tender = bool(sourcing_mod.card_hits(card_index, "FTL", ["INBOUND_FTL"]))
    with st.expander("Inbound loads — how much fits on one truck"):
        st.markdown(
            f"<div class='aw-note' style='margin:-2px 0 12px 0;max-width:760px;'>"
            + ("Cargo is collected shipment by shipment today. These caps set how many "
               "loads that takes — what the warehouse charges to receive, and how many "
               "trailers your tender is costed on."
               if has_tender else
               "Cargo is collected shipment by shipment today. These caps set how many "
               "loads that takes — what the warehouse charges to receive, and what a "
               "trailer rate would have to beat. You have not given us one.")
            + "</div>", unsafe_allow_html=True)
        cols = st.columns(3)
        with cols[0]:
            _num_input("TRAILER_PALLET_MAX", "Pallets on one load", fmt="%.0f")
            _note(C.CONFIG["TRAILER_PALLET_MAX"]["source"])
        with cols[1]:
            _num_input("TRAILER_CBM_MAX", "Volume cap (CBM)", fmt="%.1f")
            _note(C.CONFIG["TRAILER_CBM_MAX"]["source"])
        with cols[2]:
            _num_input("TRAILER_WEIGHT_MAX_KG", "Payload cap (kg)", fmt="%.0f")
            _note(C.CONFIG["TRAILER_WEIGHT_MAX_KG"]["source"])

    # --- the consolidation service --------------------------------------------
    #
    # A rate the client has actually quoted is not ours to edit here.
    #
    # Every figure here is locked by default, and one toggle unlocks the lot.
    #
    # A rate the client has quoted is a fact, not a setting, and per-rate toggles made
    # that unreadable: a field you *could* type in sat next to one you could not, and the
    # only thing distinguishing them was a switch whose label described the number rather
    # than what the switch did. Locked-until-asked also means the demo path never invites
    # anybody to nudge a figure they were shown as their own.
    quoted_by_card = {
        key: card_index.get(("CONSOLIDATION", "", "", ch_code))
        for key, ch_code in rates_mod.service_codes().items()}
    n_fixed = sum(1 for v in quoted_by_card.values() if v)

    # Open only when there is something to do. A quote that prices all five is a set of
    # facts to glance at, and it can stay folded; one the quote does not cover blocks the
    # build, so the fields that clear it are on screen when the step opens. Computed from
    # the quote before anything renders, because the expander has to be told at creation.
    total_service = len(C.SERVICE_RATE_KEYS)
    unquoted = total_service - n_fixed

    with st.expander(
            f"Warehouse rate card — {unquoted} of {total_service} still to price"
            if unquoted else
            f"Warehouse rate card — all {total_service} priced by your quote",
            expanded=bool(unquoted) or bool(S.get("tweak_service"))):
        st.markdown(
            f"<div class='aw-note' style='max-width:760px;margin:-4px 0 12px 0;'>"
            + ("No invoice can evidence these — it is work you do not buy yet. They come "
               "off your forwarder's quote, exactly as it arrived."
               if n_fixed else
               "No invoice can evidence these — it is work you do not buy yet, so they "
               "have to come off your forwarder's quote.")
            + "</div>", unsafe_allow_html=True)

        tweak = st.toggle("Let me enter or change these figures", key="tweak_service")
        UI.note("Anything you type is recorded as yours, not ours." if tweak else
                "Off, because a quoted rate is a fact rather than a setting.",
                cls="aw-micro", style="margin:-8px 0 14px 2px;")

        missing = []
        for row_keys in [C.SERVICE_RATE_KEYS[:3], C.SERVICE_RATE_KEYS[3:]]:
            cols = st.columns(3)
            for i, key in enumerate(row_keys):
                meta = C.CONFIG[key]
                hit = quoted_by_card.get(key)
                label = f"{meta['label']} ({meta['unit']})"
                whole = isinstance(meta["value"], int)
                quoted = float(hit["rate_usd"]) if hit else None
                fmt = "%.0f" if whole else "%.2f"
                with cols[i]:
                    if not tweak:
                        # Held, not discarded, so locking does not throw away a figure
                        # they gave us verbally -- and while it is locked the model must
                        # cost the number the screen is showing.
                        if key in S.overrides:
                            S.kept_rates[key] = S.overrides.pop(key)
                        if hit:
                            UI.locked_rate(label, f"{quoted:,.0f}" if whole
                                           else f"{quoted:,.2f}",
                                           "fixed by your quote", tone="theirs")
                            S.service_pricing[key] = "quoted"
                            _note(hit["item"] or "Your forwarder’s figure")
                        else:
                            UI.locked_rate(label, "—", "no price from you", tone="ours")
                            S.service_pricing[key] = "benchmark"
                            missing.append(meta["label"])
                            _note("We will not put a figure of ours here.",
                                  colour=T.WARNING)
                        continue

                    # An empty box where there is no quote, rather than our old benchmark
                    # sitting in it. Pre-filling a figure of ours and then recording
                    # whatever is in the box as the client's number would re-introduce,
                    # quietly, the exact substitution this whole change removes.
                    current = S.overrides.get(key, S.kept_rates.pop(key, quoted))
                    value = st.number_input(
                        label, value=None if current is None else float(current),
                        step=_step_for(current if current is not None else meta["value"],
                                       whole),
                        min_value=0.0, key=f"cfg_{key}", format=fmt,
                        placeholder="your rate")
                    if value is None:
                        S.overrides.pop(key, None)
                        S.service_pricing[key] = "benchmark"
                        missing.append(meta["label"])
                        _note("Type your rate and it is yours.", colour=T.WARNING)
                        continue
                    S.overrides[key] = int(value) if whole else float(value)
                    changed = quoted is None or abs(float(value) - quoted) > 1e-9
                    S.service_pricing[key] = "edited" if changed else "quoted"
                    _note(f"Your figure. Your quote said {quoted:,.2f}."
                          if changed and hit
                          else meta["quoted_note"] if hit
                          else "Your figure, recorded as yours.")

    if missing:
        # Outside the expander, so the reason the Build button is gone is on screen even
        # when the group it refers to is folded shut.
        UI.summary_line(
            f"<b>No price for {', '.join(missing).lower()}.</b> This cost exists only on "
            "the future side, so a figure of ours would carry the saving. No model until "
            "you price it.", tone="warn")

    if st.button("Reset to recommended"):
        S.overrides, S.service_pricing, S.kept_rates = {}, {}, {}
        st.rerun()

    nav(back="resolve", forward=None if missing else "build",
        forward_label="Build the model",
        forward_note=("The engine runs against your file now — nothing is pre-computed."
                      if not missing else
                      "Add your consolidation quote on step 2, or type the figures above."))


# --------------------------------------------------------------------------------------
# 5. Build
# --------------------------------------------------------------------------------------
def _render_step(event):
    st.markdown(
        f"<div style='font-size:14px;font-weight:500;color:{T.INK_700};"
        f"margin-top:14px;'>{event['title']}</div>"
        f"<div class='aw-note'>{event['detail']}</div>", unsafe_allow_html=True)
    for headline in event["findings"]:
        UI.finding(headline)
    for a in event["applied"]:
        UI.applied(a["label"], a["value"])


def step_build():
    UI.eyebrow("Step 5 of 6")
    UI.h("Running the model", 2)

    if S.result is not None:
        # The log stays on screen. A client who has just watched the engine work
        # through their file should still be able to read what it did, rather than
        # being left with a success message where the narrative used to be.
        for event in S.build_log:
            _render_step(event)
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        UI.controls_strip(S.result["controls_summary"])
        nav(back="assumptions", forward="results", forward_label="See the results")
        return

    charge_path = _to_temp(S.charge_bytes)
    rate_card = cached_frame(S.rate_card_bytes) if S.rate_card_bytes else None
    site_list = cached_frame(S.site_list_bytes) if S.site_list_bytes else None

    log = st.container()
    bar = st.progress(0.0)
    total_steps = 8
    done = 0

    result, build_log = None, []
    try:
        for event in engine.run_streaming(
                charge_path, rate_card=rate_card, site_list=site_list,
                overrides=S.overrides or None, answers=S.answers or None,
                service_pricing=S.service_pricing or None):
            if isinstance(event, engine.Step):
                done += 1
                bar.progress(min(1.0, done / total_steps))
                entry = {"title": event.title, "detail": event.detail,
                         "findings": [f.headline for f in event.findings],
                         "applied": event.applied}
                build_log.append(entry)
                with log:
                    _render_step(entry)
            else:
                result = event
    except engine.MissingRates as stop:
        # The engine stopping is the story here, so it is shown as the engine's own
        # refusal rather than as an application error. Two different refusals, and they
        # need different words: the consolidation service can be priced here, on the
        # settings step, while an ocean or delivery leg can only be fixed by a rate card.
        # Telling somebody a freight leg "is the cost consolidating creates" is simply
        # untrue, and sends them to the wrong screen to fix it.
        bar.empty()
        UI.summary_line(
            "<b>The engine stopped.</b> " + ", ".join(stop.labels)
            + (" — nobody has priced this, and a figure of ours would carry the saving."
               if stop.service_only else
               " — legs you pay for today that nothing you have given us prices. Leaving "
               "one off both sides would flatter the saving."),
            tone="warn")
        nav(back="references" if not stop.service_only else "assumptions", forward=None,
            forward_note=("Add your consolidation quote on step 2, or type the figures "
                          "on step 4."
                          if stop.service_only else
                          "Back to step 2, and add the rate cards that cover them."))
        return

    bar.progress(1.0)
    S.result, S.build_log = result, build_log
    S.result_schema_version = RESULT_SCHEMA_VERSION
    st.rerun()


# --------------------------------------------------------------------------------------
# 6. Results
# --------------------------------------------------------------------------------------
def _inbound_panel(ib, s):
    """How cargo reaches the warehouse, and what the alternative was worth.

    Consolidation only exists because cargo can be pooled, and this is the one leg where
    the pooling is a decision the client gets to make rather than a consequence of the
    plan. So it gets a panel: the two ways of buying it, side by side, with the load counts
    both came from and the two costs that move -- the haul, and the warehouse receiving
    that everybody forgets.

    The side-by-side table is only honest when a complete tender exists. With no tender,
    or one that leaves regions unpriced, the result is a compact optional follow-up: it
    cannot look like a transport mode the plan selected or included in its saving.
    """
    taken = ib.get("path") == "ftl"
    trucks, loads = ib["trucks"], ib["loads_today"]
    saved_loads = ib.get("loads_saved", 0)

    if not ib.get("supplied"):
        UI.eyebrow("Optional follow-up — not included in this plan or its savings")
        UI.panel_callout(
            f"The plan keeps the <b>{loads:,}</b> separate inbound collections you buy "
            f"today, costed at <b>{UI.money(ib['groupage_total'])}</b>. We have not "
            f"assumed pooled trailer collections because you did not provide a trailer "
            f"rate. The same-day cargo could form <b>{trucks:,}</b> trailer-sized loads "
            f"without holding cargo at a factory. A haulage rate below "
            f"<b>${ib['headroom_per_load']:,.0f} per load</b>, plus "
            f"<b>${ib['receiving_rate']:,.0f}</b> warehouse receiving per arrival, may "
            f"reduce cost. Upload a trailer quote if you want the model to test it.",
            tone="quiet")
        return

    if ib.get("partial_regions"):
        UI.eyebrow("Trailer tender not included in this plan or its savings")
        UI.panel_callout(
            "The trailer tender does not cover "
            + ", ".join(sorted(ib["partial_regions"]))
            + ". The model therefore keeps the existing separate collections and does "
              "not show a cost comparison that would leave those regions unpriced. Add "
              "the missing regional rates if you want the tender tested.",
            tone="quiet")
        return

    if taken:
        headline = (f"Tendering the inbound leg takes "
                    f"<b>{UI.money(abs(ib['delta_total']))}</b> a year off the plan")
    else:
        headline = (f"Your trailer tender costs <b>{UI.money(ib['delta_total'])}</b> more "
                    f"than collecting shipment by shipment, so the model keeps the "
                    f"collections")

    UI.panel_head(
        "Getting cargo to the warehouse",
        headline,
        f"{trucks:,} full trailer loads against {loads:,} separate deliveries"
        + (f" · {saved_loads:,} fewer arrivals for the warehouse to receive"
           if saved_loads > 0 else " · no fewer arrivals to receive"),
        f"EXW cargo on the lanes the plan runs · trailers packed to "
        f"{ib['trailer_pallets_mean']:.0f} of {ib['trailer_cap_pallets']} pallets against "
        f"real cargo-ready dates · nothing waits at a factory for a trailer to fill")

    rows = [("Loads arriving at the warehouse", f"{loads:,}", f"{trucks:,}"),
            ("The haul", UI.money(ib["groupage_haul"]),
             UI.money(ib["ftl_haul"]) if ib.get("ftl_haul") is not None else "—"),
            (f"Warehouse receiving, ${ib['receiving_rate']:,.0f} a load",
             UI.money(ib["groupage_receiving"]),
             UI.money(ib["ftl_receiving"]) if ib.get("ftl_receiving") is not None else "—"),
            ("Inbound cost of the plan", UI.money(ib["groupage_total"]),
             UI.money(ib["ftl_total"]) if ib.get("ftl_total") is not None else "—")]
    head = ("How you buy it today", "Tendered by the trailer load")
    th = (f"text-align:right;padding:7px 10px;font-size:11px;font-weight:500;"
          f"color:{T.INK_500};")
    body = "".join(
        f"<tr><td style='padding:7px 10px;color:{T.INK_600};'>{label}</td>"
        f"<td style='padding:7px 10px;text-align:right;font-variant-numeric:tabular-nums;"
        f"font-weight:{600 if last else 500};color:{T.INK_700};"
        f"background:{T.INK_50 if not taken and last else 'transparent'};'>{a}</td>"
        f"<td style='padding:7px 10px;text-align:right;font-variant-numeric:tabular-nums;"
        f"font-weight:{600 if last else 500};color:{T.INK_700};"
        f"background:{T.INK_50 if taken and last else 'transparent'};'>{b}</td></tr>"
        for label, a, b in rows
        for last in [label.startswith("Inbound cost")])
    st.markdown(
        f"<table style='width:100%;border-collapse:collapse;font-size:13px;margin-top:10px;'>"
        f"<tr><th></th><th style='{th}'>{head[0]}</th><th style='{th}'>{head[1]}</th>"
        f"</tr>{body}</table>", unsafe_allow_html=True)

    UI.panel_note(
        "Each way is costed as it is sold: your forwarder's collection tariff per "
        "container, a haulier's tender per trailer load. Both load counts come from the "
        "same bin-pack against your own cargo-ready dates — once with every shipment on "
        "its own, once pooling a region's same-day cargo. Neither holds cargo back to "
        "fill a trailer. The packing opportunity is the same; a cheaper tender can still "
        "make a borderline site lane clear the explicit commercial rule.")

    haul, recv = ib["delta_haul"], ib["delta_receiving"]
    bigger = "haul" if abs(haul) >= abs(recv) else "receiving"
    UI.panel_callout(
        "Two things move, and "
        + ("they pull the same way. " if (haul < 0) == (recv < 0)
           else "they pull against each other. ")
        + f"The haul is <b>{UI.money(abs(haul))}</b> "
          f"{'cheaper' if haul < 0 else 'dearer'}, and the warehouse receives "
          f"{abs(saved_loads):,} {'fewer' if saved_loads > 0 else 'more'} deliveries, "
          f"worth <b>{UI.money(abs(recv))}</b>{' less' if recv < 0 else ' more'}. "
        + (f"The {bigger} decides it. " if bigger == "haul" else
           "The warehouse handling decides it — where this saving usually sits and "
           "almost never where it is looked for. ")
        + ("The plan is costed at the tender." if taken else
           "The plan is costed at your own collection tariff: we will not use a rate "
           "you gave us if it is the dearer one."),
        tone="strong" if taken else "quiet")


def _money_headline(summary, pools):
    """Name the largest fall and rise without inferring a false comparison.

    Net saving is the sum of every pool movement. It does not prove that the single
    largest fall is greater than the single largest rise (or vice versa), so the headline
    states those two measured movements neutrally.
    """
    moves = sorted(
        ((pool, summary["future"][pool] - summary["today"][pool]) for pool in pools
         if abs(summary["future"][pool] - summary["today"][pool]) > 1),
        key=lambda move: move[1])
    falls = [move for move in moves if move[1] < 0]
    rises = [move for move in moves if move[1] > 0]
    if falls and rises:
        fall_name, fall_value = falls[0]
        rise_name, rise_value = rises[-1]
        rise_phrase = (f"the warehouse step adds ${rise_value:,.0f}"
                       if rise_name == "Origin CFS" else
                       f"{rise_name} rises ${rise_value:,.0f}")
        return f"{fall_name} falls ${abs(fall_value):,.0f}, while {rise_phrase}"
    if falls:
        return (f"Every cost pool that moves falls; {falls[0][0].lower()} falls furthest "
                f"at ${abs(falls[0][1]):,.0f}")
    if rises:
        return (f"Every cost pool that moves rises; {rises[-1][0].lower()} rises furthest "
                f"at ${rises[-1][1]:,.0f}")
    return "No cost pool moves materially under this plan"


def step_results():
    r = S.result
    if r is None:
        goto("assumptions")
        return
    s, lt = r["summary"], r["lead_time"]
    # Keep the whole result backward-compatible with a result produced just before a hot
    # reload.  The schema guard above normally rebuilds it; completing its config here
    # also protects later consumers such as the workbook writer, not only this sentence.
    cfg = {**C.values(), **r["config_used"]}
    r["config_used"] = cfg
    lane_min_saving_usd = float(cfg["LANE_MIN_SAVING_USD"])
    lane_min_saving_pct = float(cfg["LANE_MIN_SAVING_PCT"])

    UI.eyebrow("Step 6 of 6")
    UI.controls_strip(r["controls_summary"])

    # A failed control means the figures below are not trustworthy, and the screen has
    # to say so louder than it says the headline. Showing a saving that a control has
    # rejected is worse than showing nothing.
    if not r["controls_summary"]["all_passed"]:
        failed = [c for c in r["controls"] if not c.passed]
        st.markdown(
            f"<div style='background:{T.NEGATIVE}0F;border:1px solid {T.NEGATIVE}44;"
            f"border-left:3px solid {T.NEGATIVE};border-radius:9px;padding:16px 20px;"
            f"margin-bottom:18px;'>"
            f"<div style='font-size:14px;font-weight:500;color:{T.NEGATIVE};"
            f"margin-bottom:7px;'>Do not use these figures</div>"
            f"<div style='font-size:13px;color:{T.INK_600};line-height:1.6;'>"
            f"{len(failed)} control{'s' if len(failed) > 1 else ''} failed. The numbers "
            "below are shown to be diagnosed, not quoted.</div>"
            + "".join(
                f"<div style='font-size:12px;color:{T.INK_600};line-height:1.55;"
                f"margin-top:10px;'><b>{c.name}</b><br/>{c.detail}</div>"
                for c in failed)
            + "</div>", unsafe_allow_html=True)

    # Every tile is written from the direction the number actually moved. "N fewer" on a
    # container count that rose, or "up from" on a fill that fell, is the kind of wording
    # that survives a hundred rehearsals on one dataset and is wrong the first time
    # somebody drops in a file that behaves differently.
    saved, fill_moved = s["containers_saved"], s["mean_fill_cbm"] - s["today_fill_cbm"]
    per_cbm_moved = s["cost_per_cbm_future"] - s["cost_per_cbm_today"]
    slip = lt.get("mean_delta_days_conservative", 0)

    # A file the plan cannot improve produces a total of exactly zero, and the tile has to
    # say that rather than announce a saving of $0 — which reads as a rounding error or a
    # broken run, and is the one reading this result must not invite.
    unchanged = abs(s["saving_usd"]) < 1
    tiles = [
        {"label": ("No net change" if unchanged else
                   "Net annual saving" if s["saving_usd"] > 0 else "Net annual increase"),
         "value": "$0" if unchanged else UI.money(abs(s["saving_usd"])),
         "delta": (f"on {UI.money(s['today']['Total'])} of freight — there is nothing on "
                   "this file consolidation can improve" if unchanged else
                   f"{abs(s['saving_pct']):.1%} of {UI.money(s['today']['Total'])} today"),
         "tone": "flat" if unchanged else ("up" if s["saving_usd"] > 0 else "down"),
         "hero": True},
        {"label": "Containers", "value": f"{s['containers_today']} → {s['containers_future']}",
         "delta": (f"{saved} fewer, {s['container_reduction_pct']:.1%}" if saved > 0
                   else f"{-saved} more, {abs(s['container_reduction_pct']):.1%}"
                   if saved < 0 else "no change"),
         "tone": "up" if saved > 0 else ("down" if saved < 0 else "flat")},
    ]
    # Only where there is any. A tile reading "0 CBM, 0% of volume" is a fact about
    # nothing, and it takes the place of one that says something.
    if s["lcl_cbm_today"] > 0:
        tiles.append(
            {"label": "Of which shipped LCL today",
             "value": f"{s['lcl_cbm_today']:,.0f} CBM",
             "delta": f"{s['lcl_cbm_share']:.0%} of volume, in no container of yours",
             "tone": "flat"})
    lanes_total = s["consolidated_lanes"] + s["declined_lanes"]
    if s["declined_lanes"]:
        tiles.append(
            {"label": "Lanes the plan will run",
             "value": f"{s['consolidated_lanes']} of {lanes_total}",
             "delta": (f"{s['declined_lanes']} do not clear the lane rule — "
                       f"{s['declined_cbm_share']:.0%} of your volume"),
             "tone": "flat"})
    tiles += [
        {"label": "Container fill", "value": f"{s['mean_fill_cbm']} CBM",
         "delta": (f"{'up' if fill_moved > 0 else 'down'} from {s['today_fill_cbm']}, "
                   f"{s['mean_fill_pct']:.0f}% of cap" if fill_moved
                   else f"unchanged, {s['mean_fill_pct']:.0f}% of cap"),
         "tone": "up" if fill_moved > 0 else ("down" if fill_moved < 0 else "flat")},
        {"label": "Cost per CBM shipped", "value": f"${s['cost_per_cbm_future']:,.0f}",
         "delta": (f"{'down' if per_cbm_moved < 0 else 'up'} from "
                   f"${s['cost_per_cbm_today']:,.0f}" if per_cbm_moved
                   else "unchanged"),
         "tone": "up" if per_cbm_moved < 0 else ("down" if per_cbm_moved > 0 else "flat")},
        {"label": "Delivery impact",
         "value": f"+{slip} days" if slip else "No delay",
         "delta": (f"{lt.get('unaffected_pct', 0):.0%} of shipments unaffected"
                   if lt.get("measurable_shipments")
                   else "no shipment had usable dates to measure"),
         "tone": "down" if slip else "flat"},
    ]
    UI.kpis(tiles, columns=4, hero_span=2)

    # The free storage period used to be named here as a figure of ours that priced
    # something without being a rate. It no longer can be one: a service figure that
    # nobody has quoted or typed now stops the build rather than falling back on a
    # benchmark, so by the time this screen renders every one of them is the client's.
    # The gate, stated before anything else the page claims, because it is the reason
    # every figure above is smaller than it could be made to look. A model that will not
    # add a container to a lane is a much easier thing to defend than one that nets a
    # gain on a lane it made worse.
    if s["declined_lanes"]:
        UI.summary_line(
            "<b>No lane gains a container.</b> That is a rule, not an outcome: the "
            f"{s['declined_lanes']} lanes that failed the packing or commercial rule are "
            "left exactly as they "
            f"ship today and carried at their own invoices — {s['declined_containers']:,} "
            f"containers, {s['declined_cbm']:,.0f} CBM.", tone="ok")
    else:
        UI.summary_line(
            f"<b>Every one of your {lanes_total} lanes saves at least one container</b>, so "
            "the plan runs all of them. A lane that could not would have been left alone; "
            "no lane gains a container under this plan.", tone="ok")

    UI.provenance_strip(s)
    UI.explain("Where these prices came from",
               explain_mod.provenance(s, r["rate_table"]))

    calibration = next((c for c in r["controls"]
                        if c.name.startswith("The rate model reproduces")), None)
    if calibration:
        # The claim this card makes depends entirely on the control passing. A failed
        # calibration means the saving is the gap between our rates and the client's,
        # not the effect of consolidation, and the card has to say that instead.
        ok = calibration.passed
        st.markdown(
            f"<div class='aw-card' style='border-left:3px solid "
            f"{T.POSITIVE if ok else T.NEGATIVE};'>"
            f"<div class='aw-card-title'>"
            f"{'Why this saving is real' if ok else 'Why this saving cannot be relied on'}"
            f"</div><div class='aw-card-sub'>{calibration.detail}"
            + ("" if ok else
               " Until the rate model lands on the invoiced total, the gap between the "
               "two states measures our reconstruction, not consolidation.")
            + "</div></div>", unsafe_allow_html=True)

    # --- what the sourcing turned up, reported as findings ---------------------
    #
    # This used to sit on the References step, before the model had run, where it read as
    # configuration the user had to understand. It belongs here: it is what the engine
    # found, and every figure in it depends on the plan that has only just been built.
    plan = r.get("sourcing") or {}
    bundled = sorted({b["code"] for cs in plan.values() for b in cs.blocked_by})
    blocked_legs = [cs for cs in plan.values() if cs.blocked_by]
    dray = r["rate_table"].get("SERVICE", "cfs_drayage") or {}
    # Runs the model actually buys on this leg: one per container it builds. A declined
    # lane's boxes are never at the warehouse, so they are never drayed out of it, and
    # counting every box in the plan had the page charging drayage on cargo that never
    # went near the place.
    conts = s["cfs_built_containers"]

    notes = []
    if bundled:
        codes = ", ".join(bundled)
        many = len(bundled) > 1
        # How those legs got priced in the end is the half of this that matters, and it
        # is not always the cards: a leg the bundle blocked can still derive off a
        # different code. Read from the plan rather than asserted.
        by_state = {}
        for cs in blocked_legs:
            by_state.setdefault(cs.state, []).append(cs.label)
        ending = {
            "card": "came off your cards",
            "derived": "still derived, off a different charge code",
            "analogue": "were priced by analogy, and are marked as such",
            "quoted": "came off your forwarder's quote",
        }

        def _list(names):
            names = sorted(n.lower() for n in names)
            return (names[0] if len(names) == 1
                    else " and ".join([", ".join(names[:-1]), names[-1]]))

        outcome = "; ".join(
            f"{_list(labels)} {ending.get(state, f'ended {state}')}"
            for state, labels in sorted(by_state.items()))
        # The leg names are lower-cased to read inside a sentence, and this is the one
        # place one of them starts a sentence: "…cannot be attributed. discharge port to
        # warehouse came off your cards."
        outcome = outcome[:1].upper() + outcome[1:]
        notes.append(
            f"Charge code{'s' if many else ''} <b>{codes}</b> "
            f"{'arrive' if many else 'arrives'} bundled — several legs on one line — so "
            "nothing derives from them. Every dollar still reconciles; it just cannot be "
            "attributed. "
            + (f"{outcome}." if outcome else ""))

    # A rate built from the right kind of charge on the wrong leg. It prices the model,
    # so it has to be said out loud here rather than left in the rates table.
    for cs in plan.values():
        if cs.state == "analogue":
            notes.append(
                f"<b>{cs.label}</b> was priced by analogy, not from the leg itself"
                + (f" — {cs.caveat}" if cs.caveat else "")
                + ". Low confidence for that reason; a rate card replaces it.")
    # What the two new road legs actually cost, in the words of what was bought.
    #
    # Out of the warehouse there is nothing to decide: moving a sealed box to the quay is a
    # drayage and the unit is one container, so there is no cheaper way to buy it and no
    # bin-packing to do. Into the warehouse there is a decision, and it has its own panel
    # above rather than a line here.
    rate = float(dray["rate_usd"]) if dray else 0.0
    if dray and conts:
        notes.append(
            f"Warehouse to quay runs on your <b>drayage</b> rate — <b>${rate:,.2f}</b> a "
            f"container across <b>{conts:,}</b> runs, <b>${rate * conts:,.0f}</b>. One box, "
            "one truck: nothing to tender here, which is why the trailer question sits on "
            "the inbound leg.")

    # The cost of turning up. New on the future side and only there -- today this cargo is
    # received at a port CFS as part of what the origin charges already pay for -- so it is
    # named rather than left to be found in the ledger.
    inb = r["inbound"]
    recv = r["rate_table"].get("SERVICE", "cfs_inbound") or {}
    if recv and inb.get("priced") and inb.get("trucks"):
        arrivals = inb["trucks"] if inb.get("path") == "ftl" else inb["loads_today"]
        notes.append(
            f"Every load reaching the warehouse is unloaded, checked and put away — "
            f"<b>{arrivals:,}</b> arrivals at <b>${float(recv['rate_usd']):,.2f}</b>, "
            f"<b>${float(recv['rate_usd']) * arrivals:,.0f}</b>. New on the future side "
            "only, and the reason fewer, fuller inbound loads are worth anything.")

    # Deconsolidation, stated either way: charged where boxes carry more than one site,
    # and explicitly zero where they do not. A destination charge that is simply absent
    # from the page is the first thing a freight person assumes has been forgotten.
    led = r["ledger"]
    stripped = led[led["rate_id"] == "NEW-DECONSOL"]
    strip_usd = float(stripped["usd"].sum())
    # Counted off the charges themselves. Counting commas in the site list instead makes
    # every container look mixed, because a site name is "Perpignan, FR".
    mixed = int(stripped["container"].nunique())
    if strip_usd:
        notes.append(
            f"<b>{mixed:,}</b> container{'s' if mixed != 1 else ''} carry two or more "
            f"warehouses, so they are stripped at destination: <b>${strip_usd:,.0f}</b> "
            "of deconsolidation, charged above.")
    else:
        notes.append(
            "One site per container, so nothing is stripped at destination. Letting sites "
            "share fills boxes fuller and buys that charge — the setting is on step 4.")

    if notes:
        st.markdown("---")
        UI.eyebrow("What we found in your rates")
        for note in notes:
            st.markdown(
                f"<div style='font-size:13px;color:{T.INK_600};line-height:1.65;"
                f"padding:8px 0 8px 13px;border-left:2px solid {T.INK_200};"
                f"margin-bottom:8px;'>{note}</div>", unsafe_allow_html=True)

    st.markdown("---")
    UI.eyebrow("Where the money goes")
    UI.h(_money_headline(s, C.COST_POOLS), 3)
    st.plotly_chart(charts.cost_waterfall(s, C.COST_POOLS),
                    use_container_width=True, config={"displayModeBar": False})
    UI.explain("Explain this saving", explain_mod.saving(s))

    ib = r["inbound"]
    if ib.get("priced") and ib.get("trucks"):
        st.markdown("---")
        _inbound_panel(ib, s)

    st.markdown("---")
    UI.eyebrow("Lane by lane")
    # "Not every lane is worth consolidating" was the honest heading on the file it was
    # written against and a false one on a file where every lane clears the bar. The
    # heading is the verdict count, phrased.
    counts = r["lanes"]["verdict"].value_counts()
    worth = int(counts.get("Consolidate", 0))
    total_lanes = int(len(r["lanes"]))
    UI.h("No lane is worth consolidating on its own" if not worth else
         f"All {total_lanes} lanes are worth consolidating" if worth == total_lanes else
         f"{worth} of {total_lanes} lanes are worth consolidating; the rest are not", 3)
    UI.note(
        f"Rule applied to every origin–port–destination-site lane: consolidate only when "
        f"it saves more than ${lane_min_saving_usd:,.0f} a year or "
        f"{lane_min_saving_pct:.0%} of that lane's current cost. A lane that fails "
        "is restored to today's boxes and cost before the dashboard totals are calculated.",
        style="margin:-4px 0 12px 2px;")
    st.markdown(
        "&nbsp;&nbsp;&nbsp;".join(
            f"{UI.verdict(v)} <span style='font-size:12px;color:{T.INK_500};'>"
            f"{int(counts.get(v, 0))}</span>"
            for v in ["Consolidate", "Marginal", "Leave alone"] if counts.get(v, 0)),
        unsafe_allow_html=True)
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    lanes_view = r["lanes"][[
        "verdict", "cfs", "pod", "site", "containers_today", "containers_future",
        "containers_saved", "lcl_cbm_today", "saving_usd", "mean_fill_cbm",
        "mean_dwell", "why"]].copy()
    lanes_view.columns = ["Verdict", "Origin CFS", "Discharge port",
                          "Final delivery site", "Today boxes",
                          "Modelled box share", "Saved box share", "LCL today",
                          "Saving", "Fill", "Dwell", "Why"]
    # A lane that saves a few cents either way rounds to zero, and IEEE keeps the sign of
    # a negative that rounds away -- so the column printed "$-0" beside "$0".
    lanes_view["Saving"] = lanes_view["Saving"].round(0) + 0.0
    # Sized to the rows it has, capped where it would take over the page. A fixed height
    # left three empty rows under a seven-lane file.
    st.dataframe(
        lanes_view, use_container_width=True, hide_index=True,
        height=min(340, 36 * len(lanes_view) + 44),
        column_config={
            "Saving": st.column_config.NumberColumn(format="$%,.0f"),
            "Modelled box share": st.column_config.NumberColumn(
                format="%.1f",
                help="A mixed container is allocated by each final site's share of its "
                     "CBM, so the site rows add back to the plan's physical box count."),
            "Saved box share": st.column_config.NumberColumn(format="%.1f"),
            "Fill": st.column_config.NumberColumn(format="%.1f CBM"),
            "LCL today": st.column_config.NumberColumn(
                format="%.0f CBM",
                help="Cargo shipping LCL today, which books none of your containers. "
                     "Where a lane's box count rises, this is why."),
            "Dwell": st.column_config.NumberColumn(format="%.1f d"),
            "Why": st.column_config.TextColumn(width="large"),
        })
    st.plotly_chart(charts.containers_by_lane(r["lanes"]),
                    use_container_width=True, config={"displayModeBar": False})

    # --- what it does to delivery dates ----------------------------------------
    #
    # Laid out as the deck this analysis was first presented in laid it out, because that
    # is the part of the answer an operations audience reads first and the part they
    # argued with least: one panel per origin, the distribution beside the same shipments
    # as named outcomes, and the exclusions stated under the chart rather than in a
    # footnote nobody reaches. Every word of it is rendered from this run.
    st.markdown("---")
    UI.eyebrow("What it costs in service")
    if not lt.get("measurable_shipments"):
        if not s["consolidated_lanes"]:
            UI.h("No delivery-date impact — every lane stays as it ships today", 3)
            UI.panel_note(
                "No lane cleared the commercial adoption rule, so the final plan changes "
                "no sailing or delivery date. This is an unchanged result, not missing "
                "timing data.")
        else:
            UI.h("No shipment carried dates good enough to compare", 3)
            UI.panel_note(
                f"{lt.get('excluded_shipments', 0)} shipment groups are missing a "
                "cargo-ready, departure or delivery date, or record a departure before "
                "their own cargo was ready. The cost answer above stands; the timing "
                "answer needs dates.")
    else:
        UI.h(f"{lt['unaffected']} of {lt['measurable_shipments']} shipments arrive on "
             "the day they do today", 3)

        for panel in r.get("lead_time_origins") or []:
            median = (f"Median {panel['median_today']:.0f} days, unchanged"
                      if panel["median_modelled"] == panel["median_today"] else
                      f"Median {panel['median_today']:.0f} → "
                      f"{panel['median_modelled']:.0f} days")
            UI.panel_head(
                "Lead time by origin",
                (f"{panel['origin']} — {panel['unchanged']} of {panel['shipments']} "
                 "shipments keep the same delivery date."
                 if panel["unchanged"] else
                 f"{panel['origin']} — every one of {panel['shipments']} shipments "
                 "changes date."),
                f"{median}&nbsp; · &nbsp;{panel['unchanged_pct']:.0%} unchanged, "
                f"{panel['earlier_pct']:.0%} earlier, {panel['later_pct']:.0%} later",
                f"Change in cargo ready → final delivery · {panel['origin_full']} only")

            p1, p2 = st.columns([1.18, 1])
            with p1:
                fig = charts.origin_histogram(panel)
                if fig:
                    st.plotly_chart(fig, use_container_width=True,
                                    config={"displayModeBar": False})
            with p2:
                fig = charts.origin_buckets(panel)
                if fig:
                    st.plotly_chart(fig, use_container_width=True,
                                    config={"displayModeBar": False})

            bits = []
            if panel["cannot_move"]:
                bits.append(
                    f"{panel['cannot_move']} of {panel['origin_total']} groups out of "
                    f"{panel['origin']} are air, road or non-EXW/FOB cargo the plan "
                    "cannot touch — left out, not counted in as unchanged.")
            if panel.get("left_alone"):
                bits.append(
                    f"A further {panel['left_alone']} ship exactly as they do today — "
                    "either on a lane the plan rejects or in a box consolidation does not "
                    "change — so their dates do not move and they are not counted here.")
            if panel["unmeasurable"]:
                bits.append(f"{panel['unmeasurable']} more have dates too poor to "
                            "compare.")
            bits.append(f"Worst case +{panel['worst_days']} days, to "
                        f"{panel['worst_site']}." if panel["later"] else
                        "Nothing from this origin arrives later.")
            UI.panel_note(" ".join(bits))

            worst_bucket = panel["buckets"][-1]
            UI.panel_callout(
                f"Of the {panel['shipments']} {panel['origin']} shipments the plan moves, "
                f"<b>{panel['unchanged']} keep their delivery date</b>"
                + (f"; {worst_bucket['count']} "
                   f"{'arrives' if worst_bucket['count'] == 1 else 'arrive'} 15 or more "
                   f"days later, worst case +{panel['worst_days']} days."
                   if worst_bucket["count"]
                   else f", and nothing lands more than {max(0, panel['worst_days'])} "
                        "days late."))

        # --- where the lateness actually sits ----------------------------------
        risk = r.get("lead_time_risk") or {}
        fig = charts.lane_risk_chart(risk)
        if fig:
            concentrated = risk["concentrated"]
            st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
            UI.panel_head(
                "Where the risk sits",
                ("Lateness concentrates in a handful of lanes, not the whole network"
                 if concentrated else
                 f"Lateness is spread across {risk['lanes_total']} lanes rather than "
                 "sitting in a few"),
                f"{risk['later']} of {risk['measurable']} shipments arrive later · "
                f"{risk['lanes_clean']} of {risk['lanes_total']} lanes produce none",
                "Share of each lane's own shipments that arrive later than today")
            k1, k2 = st.columns([1.7, 1])
            with k1:
                st.plotly_chart(fig, use_container_width=True,
                                config={"displayModeBar": False})
            with k2:
                stats = [
                    (f"{risk['later']} of {risk['measurable']}",
                     f"arrive later — {risk['later_share']:.0%} of the cargo the plan "
                     "moves."
                     + (f" {risk['over_fortnight']} by more than a fortnight."
                        if risk["over_fortnight"] else " None by more than a fortnight.")),
                    (f"{risk['lanes_clean']} of {risk['lanes_total']}",
                     "lanes produce no late shipment at all."
                     if risk["lanes_clean"] else "lanes are clean — every one carries "
                     "some lateness."),
                    (f"+{risk['worst_days']} days",
                     f"is the worst case in the file, on {risk['worst_lane']}."),
                ]
                UI.stat_block(stats)
                if risk["thin_lanes"]:
                    UI.panel_note(
                        "Read thin lanes with care: "
                        + ", ".join(risk["thin_lanes"][:3])
                        + " move several points per shipment.")
            UI.panel_callout(
                (f"The three worst lanes hold <b>{risk['top_lanes_share']:.0%}</b> of "
                 f"the lateness on {risk['top_lanes_volume_share']:.0%} of the volume. "
                 "Manage it lane by lane rather than accept it as a property of the "
                 "network."
                 if concentrated else
                 f"The three worst lanes hold <b>{risk['top_lanes_share']:.0%}</b> of the "
                 f"lateness on {risk['top_lanes_volume_share']:.0%} of the volume — so it "
                 "tracks how much a lane ships, not which lane it is. The dwell cap and "
                 "dispatch target answer it, not a named lane."), tone="strong")

        UI.explain("Explain the service impact", explain_mod.lead_time(lt))

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    warehouse_frame = charts.warehouse_containers(r["containers_costed"])
    warehouse_boxes = len(warehouse_frame)
    c3, c4 = st.columns(2)
    with c3:
        if warehouse_boxes and int(warehouse_frame["dwell_days"].max()) == 0:
            UI.h(f"All {warehouse_boxes:,} warehouse-built containers turn around "
                 "the same day", 4)
            UI.panel_note(
                "Every box is dispatched on the day its first cargo is ready, so there "
                "is no overnight dwell to plot and the dwell cap is never approached.")
        else:
            dwell_fig = charts.dwell_distribution(
                r["containers_costed"], cfg["MAX_DWELL_DAYS"])
        if warehouse_boxes and int(warehouse_frame["dwell_days"].max()) > 0:
            UI.h(f"Dwell for the {warehouse_boxes:,} containers built at the warehouse", 4)
            st.plotly_chart(dwell_fig, use_container_width=True,
                            config={"displayModeBar": False})
            UI.note(f"Only containers the plan sends through the warehouse are shown. "
                    f"The dashed line is the {cfg['MAX_DWELL_DAYS']}-day cap.",
                    cls="aw-micro", style="margin-top:-8px;")
        elif not warehouse_boxes:
            UI.h("No warehouse dwell to report", 4)
            UI.note("This plan leaves every lane in its current operation, so no "
                    "container enters the consolidation warehouse.", cls="aw-micro")
    with c4:
        fig = charts.dispatch_reasons(r["containers_costed"])
        if fig:
            UI.h(f"Why those {warehouse_boxes:,} containers left", 4)
            st.plotly_chart(fig, use_container_width=True,
                            config={"displayModeBar": False})

    st.markdown("---")
    UI.eyebrow("The rates behind the answer")
    # A file where every leg was carded derives nothing, and the heading has to say that
    # rather than sit above an empty space. It is not a lesser answer -- a contracted
    # rate beats a reconstructed one -- so it is not phrased as a shortfall.
    derived = int((r["rates"]["source"] == "DERIVED_FROM_INVOICES").sum())
    fig = charts.derived_vs_observed(r["rates"])
    if fig:
        UI.h("Every derived rate, against the invoices it came from", 3)
        st.plotly_chart(fig, use_container_width=True,
                        config={"displayModeBar": False})
        UI.note("Grey bar: what your invoices paid on that lane. Green dot: the rate used "
                "— total over containers, so weighted, not the mid-point.",
                cls="aw-micro", style="margin-top:-8px;")
    elif derived:
        UI.h(f"{derived} rates were derived from your invoices", 3)
        UI.panel_note("None is an ocean or delivery rate with a spread to plot. The "
                      "arithmetic is listed below.")
    else:
        UI.h("Every rate in this answer came from a file you gave us", 3)
        UI.panel_note("Nothing was reconstructed, so there is no derivation to check.")

    with st.expander("Every rate, with its provenance and formula"):
        rates_view = r["rates"][[
            "category", "item", "rate_usd", "source", "confidence",
            "population_groups", "observed_min", "observed_median", "observed_max",
            "derivation"]].copy()
        rates_view.columns = ["Category", "Item", "Rate USD", "Source", "Confidence",
                              "Invoiced groups", "Min", "Median", "Max", "How it was built"]
        st.dataframe(rates_view, use_container_width=True, hide_index=True, height=420,
                     column_config={
                         "Rate USD": st.column_config.NumberColumn(format="$%,.2f"),
                         "Min": st.column_config.NumberColumn(format="$%,.0f"),
                         "Median": st.column_config.NumberColumn(format="$%,.0f"),
                         "Max": st.column_config.NumberColumn(format="$%,.0f"),
                         "How it was built": st.column_config.TextColumn(width="large"),
                     })

    st.markdown("---")
    UI.h("The full worksheet", 3)
    # Named from the writer's own tab list, so the description cannot drift from the file
    # it describes -- which it had, promising twelve tabs of a seven-tab workbook. The
    # glosses have gone: each tab explains itself on its own first row, and repeating all
    # seven here was a paragraph of prose in front of a download button.
    st.markdown(
        f"<div class='aw-note' style='max-width:680px;'>"
        f"{len(workbook_mod.SHEETS)} tabs: "
        + ", ".join(name.split(" ", 1)[1].capitalize()
                    for name, _ in workbook_mod.SHEETS)
        + ".</div>", unsafe_allow_html=True)
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    buf = io.BytesIO()
    workbook_mod.build_workbook(buf, r)
    d1, d2, d3, _ = st.columns([1.3, 1.1, 1.1, 2])
    with d1:
        st.download_button(
            "Download workbook (.xlsx)", buf.getvalue(),
            "arcwise_consolidation.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary", use_container_width=True)
    with d2:
        st.download_button("Cost ledger (CSV)", r["ledger"].to_csv(index=False).encode(),
                           "cost_ledger.csv", "text/csv", use_container_width=True)
    with d3:
        st.download_button("Lane verdicts (CSV)", r["lanes"].to_csv(index=False).encode(),
                           "lane_verdicts.csv", "text/csv", use_container_width=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    b1, b2, _ = st.columns([1, 1.4, 3])
    with b1:
        if st.button("Back", use_container_width=True):
            goto("assumptions")
    with b2:
        if st.button("Change an assumption and rebuild", use_container_width=True):
            S.result, S.build_log = None, []
            goto("assumptions")


# --------------------------------------------------------------------------------------
T.header()
UI.rail(S.step)

if S.step != "data" and not S.charge_bytes:
    S.step = "data"

{
    "data": step_data,
    "references": step_references,
    "resolve": step_resolve,
    "assumptions": step_assumptions,
    "build": step_build,
    "results": step_results,
}[S.step]()
