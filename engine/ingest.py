"""Turn a messy charge-line export into a clean shipment-group table.

Charge lines are billing records, not shipments. One shipment appears on as many
rows as it has charges, and every row repeats the shipment's own details, so
almost any aggregation of the raw file is wrong by a factor of the charges per
invoice. Undoing that is the whole job here.

Three pieces of mess are handled loudly, because each one stands between a raw
invoice and a rate the client will accept:

    ``read_line_costs``          the repeated invoice total, and the ``-related-``
                                 sentinel that marks it
    ``equipment_by_group``       equipment stated against master bills and blank
                                 on most rows
    ``map_charge_pools``         one charge code arriving under several free-text
                                 descriptions, plus codes the register has never
                                 seen

Mixed date formats, the three-currency billing mix and out-of-scope transport
modes are handled quietly. They are real, but none of them moves a headline
number, so they are recorded and not narrated.

Every function that cleans something returns both the cleaned data and a
``Finding`` describing what it did, in rows and in dollars. Those findings are
what the build narrates and what the workbook's Data Quality tab publishes. The
engine never fixes anything silently.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config as C


@dataclass
class Finding:
    """One thing the engine noticed and what it did about it."""
    rule: str
    headline: str                 # single line, written to be read aloud
    rows: int = 0
    dollars: float = 0.0
    note: str = ""                # the fuller explanation, for the workbook
    narrate: bool = False         # does the build ticker call this out?


@dataclass
class Ingested:
    shipments: pd.DataFrame       # one row per shipment group
    lines: pd.DataFrame           # charge lines, cleaned and pool-tagged
    findings: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


# --------------------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------------------
def _clean_id(value):
    """Stable text key for identifiers that survive a trip through a spreadsheet.

    Excel turns an integer group number into ``647935.0`` given the chance, and a
    join on that silently matches nothing.
    """
    if pd.isna(value):
        return ""
    s = str(value).strip()
    return s[:-2] if s.endswith(".0") else s


def read_charge_lines(path):
    """Read the export with every column as text.

    Typing is deliberately deferred. Pandas' chunked dtype inference produces
    mixed int/str values in the equipment columns -- the same column reporting
    twice as many distinct values as it holds -- and every container count derived
    from it is then quietly wrong.
    """
    raw = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    raw.columns = [c.strip() for c in raw.columns]

    required = {"CT #", "GRP #", "M #", "SI CC", "USD SI CC", "Transport Mode",
                "Shipping Term", "Origin", "Port of Discharge", "Delivery", "Shipper"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"charge-line file is missing required columns: {sorted(missing)}")

    # A row is a shipment only if it names a transport mode. Source workbooks
    # routinely carry a footer analysis block below the last shipment whose cells
    # hold prose, and those rows are not cargo.
    is_cargo = raw["Transport Mode"].astype(str).str.strip() != ""
    dropped = int((~is_cargo).sum())
    raw = raw[is_cargo].reset_index(drop=True)

    raw["grp_key"] = raw["GRP #"].map(_clean_id)
    raw["ct_key"] = raw["CT #"].map(_clean_id)
    raw["mb_key"] = raw["M #"].map(_clean_id)
    raw["code"] = raw["SI CC"].map(_clean_id)
    return raw, dropped


# --------------------------------------------------------------------------------------
# Mess 1 -- the invoice total is repeated, and one column marks where it is real
# --------------------------------------------------------------------------------------
def read_line_costs(raw):
    """Establish what each charge line actually cost, and prove the total.

    The export states an invoice's total on the first line of that invoice and
    writes the literal string ``-related-`` on every other line, while a second
    column repeats the same total on *every* line. Two traps follow:

      * summing the repeated column multiplies the client's spend by the number of
        charges per invoice
      * filling the sentinel down -- the obvious spreadsheet move -- reproduces
        exactly that error

    The only per-line figure in the file is the charge amount itself. It is used
    for everything, and the invoice totals are then a control on it rather than an
    input: the charges of an invoice must sum to the total that invoice declared.
    """
    raw = raw.copy()
    raw["line_usd"] = pd.to_numeric(raw["USD SI CC"], errors="coerce").fillna(0.0)

    sentinel = raw["USD Sales Amount"].astype(str).str.strip().str.lower() == "-related-"
    declared = pd.to_numeric(
        raw["USD Sales Amount"].where(~sentinel), errors="coerce")

    true_total = float(raw["line_usd"].sum())
    declared_total = float(declared.sum(skipna=True))

    # What a naive read of the repeated column would have reported.
    fx = raw["Currency"].map(C.REPORTING_FX_TO_USD).fillna(1.0)
    repeated = pd.to_numeric(raw["Billed Sales Amount"], errors="coerce").fillna(0.0) * fx
    inflated_total = float(repeated.sum())

    finding = Finding(
        rule="repeated_invoice_total",
        headline=(f"{int(sentinel.sum()):,} of {len(raw):,} lines carry the "
                  f"'-related-' marker — invoice totals counted once, not once per charge"),
        rows=int(sentinel.sum()),
        dollars=round(inflated_total - true_total, 2),
        note=("The invoice total is stated on the first line of an invoice and marked "
              "'-related-' on the rest, while the billed-amount column repeats it on every "
              f"line. Summing that column reports ${inflated_total:,.0f} of spend against an "
              f"actual ${true_total:,.0f}. Cost is taken per line from the charge amount, and "
              f"the declared invoice totals (${declared_total:,.2f}) are then used as a control "
              "on that figure rather than as an input to it."),
        narrate=True,
    )
    return raw, finding, {"true_total": round(true_total, 2),
                          "declared_total": round(declared_total, 2),
                          "inflated_total": round(inflated_total, 2)}


# --------------------------------------------------------------------------------------
# Mess 2 -- equipment is stated against master bills and blank almost everywhere
# --------------------------------------------------------------------------------------
def equipment_by_group(raw):
    """Rebuild how many containers each shipment group actually moved.

    Every charge line repeats its shipment's equipment block, and most rows leave
    it empty. Counting rows therefore multiplies containers by the number of
    charges; taking a maximum over the whole group loses the second box of a
    two-box booking.

    The rule that survives both: take the maximum stated equipment for each
    (group, master bill) pair, then sum those master-bill counts up to the group.
    A booking is a master bill, so the maximum is the count that bill declared,
    and a group spanning two bills correctly gets the sum of them.

    This count is load-bearing twice over. It is the container figure the saving
    is measured against, and it is the denominator of every per-container rate the
    engine later derives from these invoices.
    """
    eq = raw[raw["grp_key"].ne("") & raw["mb_key"].ne("")].copy()
    for col in C.EQUIPMENT_COLS:
        eq[col + "_n"] = pd.to_numeric(eq[col], errors="coerce").fillna(0).astype(int)

    stated_rows = int((eq[[c + "_n" for c in C.EQUIPMENT_COLS]].sum(axis=1) > 0).sum())

    per_bill = (eq.groupby(["grp_key", "mb_key"], as_index=False)
                [[c + "_n" for c in C.EQUIPMENT_COLS]].max())
    by_group = per_bill.groupby("grp_key", as_index=False).agg(
        master_bills=("mb_key", "nunique"),
        **{c: (c + "_n", "sum") for c in C.EQUIPMENT_COLS})
    by_group["containers_today"] = by_group[C.EQUIPMENT_COLS].sum(axis=1)

    # What a row count would have claimed, for the record.
    naive = int(eq[[c + "_n" for c in C.EQUIPMENT_COLS]].sum(axis=1).sum())
    rebuilt = int(by_group["containers_today"].sum())

    blank = len(raw) - stated_rows
    finding = Finding(
        rule="equipment_rebuilt_from_master_bills",
        headline=(f"equipment blank on {blank:,} of {len(raw):,} lines — "
                  f"{rebuilt:,} containers rebuilt from {int(by_group['master_bills'].sum()):,} "
                  "master bills"),
        rows=blank,
        note=(f"The equipment block is stated on {stated_rows:,} lines and blank on the rest. "
              f"Counting stated rows claims {naive:,} containers; the maximum per master bill, "
              f"summed to the group, gives {rebuilt:,}. This count is both the baseline the "
              "saving is measured against and the denominator of every per-container rate "
              "derived from these invoices."),
        narrate=True,
    )
    return by_group, finding


# --------------------------------------------------------------------------------------
# Mess 3 -- one code, several descriptions, and codes nobody recognises
# --------------------------------------------------------------------------------------
def map_charge_pools(raw):
    """Place every charge in a cost pool by its code, never by its description.

    Operators type the description, so the same code arrives under several names.
    In this file the destination delivery charge -- the one a per-container rate
    gets derived from -- appears under four different descriptions. Matching on
    text would split one rate population into four and price none of them
    correctly.

    Codes the register does not recognise are reported and kept. Their dollars
    stay in the reconciliation and land in a clearly-labelled pool; they are never
    quietly dropped, because a discarded charge is the fastest way to lose an
    audit.
    """
    raw = raw.copy()
    raw["pool"] = raw["code"].map(C.CHARGE_CODE_POOLS)

    unknown = raw["pool"].isna()
    unknown_codes = sorted(raw.loc[unknown, "code"].unique())
    unknown_usd = float(raw.loc[unknown, "line_usd"].sum())
    raw.loc[unknown, "pool"] = "Destination Other"
    raw["code_unrecognised"] = unknown

    # How much description drift the register absorbed.
    spellings = (raw.groupby("code")["SI CC Description"].nunique()
                 .sort_values(ascending=False))
    worst_code = spellings.index[0] if len(spellings) else ""
    worst_n = int(spellings.iloc[0]) if len(spellings) else 0
    multi = int((spellings > 1).sum())

    pool_finding = Finding(
        rule="charge_codes_normalised",
        headline=(f"{len(spellings):,} charge codes under "
                  f"{int(raw['SI CC Description'].nunique()):,} descriptions — "
                  f"code {worst_code} alone appears under {worst_n}"),
        rows=int(raw.loc[raw["code"].isin(spellings[spellings > 1].index)].shape[0]),
        note=(f"{multi} codes arrive under more than one description. Pools are assigned from "
              f"the code, never the text: code {worst_code} appears under {worst_n} descriptions "
              "and matching on any of them would split a single rate population."),
        narrate=True,
    )

    unknown_finding = Finding(
        rule="unrecognised_charge_codes",
        headline=((f"{len(unknown_codes)} charge codes need classification "
                   f"({int(unknown.sum())} lines, ${unknown_usd:,.0f}) — usable results "
                   "are blocked")
                  if unknown_codes else "Every charge code is classified in the register"),
        rows=int(unknown.sum()),
        dollars=round(unknown_usd, 2),
        note=("Codes " + ", ".join(unknown_codes) + " have no pool in the register. Their "
              "dollars are held in Destination Other and remain in the reconciliation so the "
              "ledger still ties to the invoices. They need a pool assignment before these "
              "charges can be modelled properly."
              if unknown_codes else "Every charge code was recognised."),
        narrate=False,
    )
    return raw, [pool_finding, unknown_finding]


# --------------------------------------------------------------------------------------
# Dates -- two formats in one file, and departures that precede cargo-ready
# --------------------------------------------------------------------------------------
def parse_mixed_dates(series):
    """Parse both formats present in the export without guessing per cell.

    Each format is tried explicitly. Letting pandas infer per value silently
    swaps day and month on any date whose day is 12 or less.
    """
    s = series.astype(str).str.strip().replace({"": None})
    out = pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")
    remaining = out.isna() & s.notna()
    if remaining.any():
        out.loc[remaining] = pd.to_datetime(s[remaining], format="%Y-%m-%d", errors="coerce")
    return out


DATE_COLUMNS = {
    "Cargo Ready": "cargo_ready",
    "Act Depart": "act_depart",
    "Act Arriv": "act_arriv",
    "Act Deliv": "act_deliv",
}


# --------------------------------------------------------------------------------------
# Shipment groups
# --------------------------------------------------------------------------------------
def build_shipments(raw, equipment):
    """Collapse charge lines to one row per shipment group.

    Cargo is stated once per shipment, on the line that carries the shipment-level
    block, and a group is the sum of its shipments. Costs are summed by pool from
    the per-line amounts. Attributes are taken from the group's first line, which
    is safe because they are properties of the booking and identical across it.
    """
    # --- cargo, from the one line per shipment that states it ------------------
    block = raw[pd.to_numeric(raw["CT Plts"], errors="coerce").notna()].copy()
    block = block.drop_duplicates("ct_key", keep="first")
    for src, dst in [("CT Plts", "pallets"), ("CT CBM", "cbm"), ("CT GWT kg", "gwt")]:
        block[dst] = pd.to_numeric(block[src], errors="coerce").fillna(0.0)
    cargo = block.groupby("grp_key", as_index=False).agg(
        pallets=("pallets", "sum"), cbm=("cbm", "sum"), gwt=("gwt", "sum"),
        shipments=("ct_key", "nunique"))
    cargo["pallets"] = cargo["pallets"].round().astype(int)

    # --- cost by pool ----------------------------------------------------------
    pools = (raw.pivot_table(index="grp_key", columns="pool", values="line_usd",
                             aggfunc="sum", fill_value=0.0)
             .reindex(columns=C.COST_POOLS, fill_value=0.0)
             .reset_index())
    pools["invoiced_usd"] = pools[C.COST_POOLS].sum(axis=1)

    # --- attributes ------------------------------------------------------------
    attr_cols = ["Shipping Term", "Transport Mode", "Shipper", "Consignee",
                 "Origin", "Port of Discharge", "Delivery", "Destination Country",
                 "Origin Country", "Currency", "Sales Invoice #"]
    attrs = raw.drop_duplicates("grp_key", keep="first")[["grp_key"] + attr_cols].copy()
    attrs = attrs.rename(columns={
        "Shipping Term": "term", "Transport Mode": "mode", "Shipper": "shipper",
        "Consignee": "consignee", "Origin": "origin", "Port of Discharge": "pod",
        "Delivery": "delivery_raw", "Destination Country": "pod_country",
        "Origin Country": "origin_country", "Currency": "currency",
        "Sales Invoice #": "invoice"})

    # --- dates -----------------------------------------------------------------
    dates = raw.drop_duplicates("grp_key", keep="first")[["grp_key"] + list(DATE_COLUMNS)].copy()
    for src, dst in DATE_COLUMNS.items():
        dates[dst] = parse_mixed_dates(dates[src])
    dates = dates[["grp_key"] + list(DATE_COLUMNS.values())]

    ship = (attrs.merge(cargo, on="grp_key", how="left")
            .merge(pools, on="grp_key", how="left")
            # The equipment breakdown travels with the total, not just the total.
            # A per-container rate is only meaningful across boxes of comparable
            # size, so the rate derivation has to be able to restrict its
            # population to 40ft and 40'HC bookings.
            .merge(equipment[["grp_key", "containers_today", "master_bills"]
                             + C.EQUIPMENT_COLS],
                   on="grp_key", how="left")
            .merge(dates, on="grp_key", how="left"))
    for col in ["pallets", "containers_today", "master_bills", "shipments"] + C.EQUIPMENT_COLS:
        ship[col] = ship[col].fillna(0).astype(int)
    for col in ["cbm", "gwt"] + C.COST_POOLS + ["invoiced_usd"]:
        ship[col] = ship[col].fillna(0.0)

    # A shipment whose recorded departure precedes its own cargo-ready date cannot
    # be used to measure lead time. The row still costs; it is excluded from the
    # timing comparison only, and the count is published.
    ship["date_quality"] = np.where(
        ship["cargo_ready"].isna() | ship["act_depart"].isna() | ship["act_deliv"].isna(),
        "MISSING",
        np.where(ship["act_depart"] < ship["cargo_ready"], "DEPART_BEFORE_READY", "OK"))
    return ship


def apply_scope(ship):
    """Flag the groups consolidation can actually act on.

    Ocean only -- air and road cargo cannot be combined into a container. EXW or
    FOB only, because on DAP, DDP or CIF terms the supplier or their carrier
    controls the leg and there is nothing of ours to combine. Out-of-scope cargo
    stays in the file and in the client's total spend; it simply cannot move.
    """
    ship = ship.copy()
    is_ocean = ship["mode"].str.contains(C.IN_SCOPE_MODE_SUBSTRING, case=False, na=False)
    good_term = ship["term"].isin(C.IN_SCOPE_TERMS)
    ship["in_scope"] = is_ocean & good_term
    ship["is_fcl"] = ship["mode"].eq(C.FCL_MODE)

    out_usd = float(ship.loc[~ship["in_scope"], "invoiced_usd"].sum())
    finding = Finding(
        rule="scope_filter",
        headline=(f"{int((~ship['in_scope']).sum()):,} of {len(ship):,} shipment groups "
                  f"out of scope (air, road or non-EXW/FOB terms) — ${out_usd:,.0f} untouched"),
        rows=int((~ship["in_scope"]).sum()),
        dollars=round(out_usd, 2),
        note=("Consolidation applies to ocean cargo on EXW or FOB terms. Air and road cannot "
              "be combined into a container, and on DAP/DDP/CIF terms the counterparty "
              "controls the leg. This spend stays exactly as it is."),
        narrate=False,
    )
    return ship, finding


# --------------------------------------------------------------------------------------
def ingest(path):
    """Read a charge-line export and return clean shipment groups plus findings."""
    raw, footer_rows = read_charge_lines(path)
    raw, cost_finding, cost_stats = read_line_costs(raw)
    equipment, equipment_finding = equipment_by_group(raw)
    raw, pool_findings = map_charge_pools(raw)

    ship = build_shipments(raw, equipment)
    ship, scope_finding = apply_scope(ship)

    findings = [cost_finding, equipment_finding, *pool_findings, scope_finding]
    if footer_rows:
        findings.append(Finding(
            rule="footer_rows_dropped",
            headline=f"{footer_rows} non-shipment rows dropped (no transport mode)",
            rows=footer_rows,
            note="Rows below the last shipment holding analysis text rather than cargo.",
        ))

    fx_usd = float(ship.loc[ship["currency"].ne("USD"), "invoiced_usd"].sum())
    stats = {
        "charge_lines": int(len(raw)),
        "shipments": int(ship["shipments"].sum()),
        "shipment_groups": int(len(ship)),
        "invoices": int(raw["Sales Invoice #"].nunique()),
        "master_bills": int(raw["mb_key"].nunique()),
        "charge_codes": int(raw["code"].nunique()),
        "date_range": [str(ship["cargo_ready"].min().date()),
                       str(ship["cargo_ready"].max().date())],
        "modes": sorted(ship["mode"].unique().tolist()),
        "terms": sorted(ship["term"].unique().tolist()),
        "total_invoiced_usd": cost_stats["true_total"],
        "declared_invoice_total_usd": cost_stats["declared_total"],
        "naive_repeated_total_usd": cost_stats["inflated_total"],
        "in_scope_groups": int(ship["in_scope"].sum()),
        "containers_today": int(ship.loc[ship["in_scope"], "containers_today"].sum()),
        "in_scope_pallets": int(ship.loc[ship["in_scope"], "pallets"].sum()),
        "in_scope_cbm": round(float(ship.loc[ship["in_scope"], "cbm"].sum()), 1),
        "in_scope_usd": round(float(ship.loc[ship["in_scope"], "invoiced_usd"].sum()), 2),
        "non_usd_share": round(fx_usd / max(1.0, float(ship["invoiced_usd"].sum())), 4),
        "bad_date_groups": int((ship["date_quality"] != "OK").sum()),
    }
    return Ingested(shipments=ship, lines=raw, findings=findings, stats=stats)
