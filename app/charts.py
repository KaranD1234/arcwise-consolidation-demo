"""Charts for the results view, in the Arcwise palette.

Every chart here answers one question and is labelled with that question. Colour
carries meaning only where meaning exists: the brand ramp for ordinary series, and
the semantic green/red only for a saving and a cost. Gridlines are faint, axes are
unboxed, and nothing is coloured merely to fill space.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import theme as T

# What an audience walks in expecting consolidation to cost them, shaded on the
# distribution so the measured answer can be read against it. It is a rule of thumb and
# is labelled as one -- it comes from no file, prices nothing, and moves no figure in
# this model. It is on the chart because the point of the chart is that the measured
# distribution sits to the left of what the room already believes.
EXPECTATION_DAYS = (3, 7)

FONT = dict(family="InterVariable, -apple-system, Segoe UI, sans-serif",
            size=12, color=T.INK_600)


def _alpha(hex_colour, a):
    """One colour at four strengths. Plotly rejects the 8-digit hex CSS accepts."""
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{a})"


def _shell(fig, height=320, legend=False, ymoney=False):
    fig.update_layout(
        height=height,
        font=FONT,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=8, b=8),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
        hoverlabel=dict(bgcolor=T.SURFACE_CARD, bordercolor=T.INK_200,
                        font=dict(color=T.INK_700, size=12)),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, showline=True,
                     linecolor=T.INK_200, tickfont=dict(size=11, color=T.INK_500))
    fig.update_yaxes(showgrid=True, gridcolor=T.INK_100, zeroline=False,
                     showline=False, tickfont=dict(size=11, color=T.INK_500),
                     tickprefix="$" if ymoney else None)
    return fig


def cost_waterfall(summary, pools):
    """Where the money goes, pool by pool, including the cost consolidation adds.

    A waterfall rather than two stacked bars, because the honest story is not "cost
    went down" -- it is "freight and delivery fell by more than the new warehouse
    step cost". Two bars hide that; a waterfall is the argument.
    """
    deltas = [(p, summary["future"][p] - summary["today"][p]) for p in pools]
    deltas = [(p, d) for p, d in deltas if abs(d) > 1]
    deltas.sort(key=lambda t: t[1])

    labels = ["Today"] + [p for p, _ in deltas] + ["Modelled"]
    measures = ["absolute"] + ["relative"] * len(deltas) + ["total"]
    values = ([summary["today"]["Total"]] + [d for _, d in deltas]
              + [summary["future"]["Total"]])

    fig = go.Figure(go.Waterfall(
        orientation="v", measure=measures, x=labels, y=values,
        text=[f"${v:,.0f}" if m == "absolute" or m == "total" else f"{v:+,.0f}"
              for v, m in zip(values, measures)],
        textposition="outside",
        textfont=dict(size=10.5, color=T.INK_500),
        connector=dict(line=dict(color=T.INK_300, width=1)),
        decreasing=dict(marker=dict(color=T.POSITIVE)),
        increasing=dict(marker=dict(color=T.NEGATIVE)),
        totals=dict(marker=dict(color=T.BRAND_600)),
        hovertemplate="%{x}<br>$%{y:,.0f}<extra></extra>",
    ))
    # ymoney has to be set through _shell: _shell rewrites the y-axis last, so a
    # tickprefix applied before it is silently discarded.
    fig = _shell(fig, height=390, ymoney=True)
    fig.update_yaxes(tickformat=",.0f")
    return fig


def containers_by_lane(lanes, top=14):
    """Containers today against containers modelled, lane by lane.

    Paired bars on a shared axis, sorted by what the lane saves, so the eye lands on
    the lanes that matter and can still see the ones that save nothing.
    """
    d = lanes.copy()
    # Origin is part of the lane too. Omitting it merges two rows that share a discharge
    # port and final site into one y-axis label, visually hiding a lane even though the
    # dataframe still contains it.
    d["lane"] = (d["site"] + "  ← " + d["pod"].str.split(",").str[0]
                 + "  ← " + d["cfs"])
    d = d.nlargest(top, "containers_today").sort_values("containers_today")

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=d["lane"], x=d["containers_today"], orientation="h", name="Today",
        marker=dict(color=T.INK_300),
        hovertemplate="%{y}<br>%{x} containers today<extra></extra>"))
    fig.add_trace(go.Bar(
        y=d["lane"], x=d["containers_future"], orientation="h", name="Modelled",
        marker=dict(color=T.BRAND_600),
        hovertemplate="%{y}<br>%{x} containers modelled<extra></extra>"))
    fig.update_layout(barmode="overlay", bargap=0.35)
    fig.update_traces(width=0.72, selector=dict(name="Today"))
    fig.update_traces(width=0.42, selector=dict(name="Modelled"))
    fig.update_xaxes(showgrid=True, gridcolor=T.INK_100, showline=False)
    fig.update_yaxes(showgrid=False, tickfont=dict(size=10.5))
    return _shell(fig, height=max(300, 26 * len(d)), legend=True)


# --------------------------------------------------------------------------------------
# The origin panel: distribution on the left, the same shipments as named buckets on the
# right. Two views of one number because they answer different questions -- the
# distribution shows the tail, the buckets size it, and an audience reads the second
# faster while trusting the first.
# --------------------------------------------------------------------------------------
def origin_histogram(panel):
    """Every shipment out of one origin, by how many days the plan moves it.

    The unchanged bar is clipped where it would otherwise flatten everything else into
    the axis, and clipping is stated on the chart rather than left to be noticed: the
    shape of the tail is the point, and a bar four times the height of the plot area
    hides it.
    """
    hist = panel.get("histogram") or []
    if not hist:
        return None
    series = {
        "Earlier": ([h["days"] for h in hist if h["days"] < 0],
                    [h["count"] for h in hist if h["days"] < 0], T.POSITIVE,
                    panel["earlier"]),
        "No change": ([h["days"] for h in hist if h["days"] == 0],
                      [h["count"] for h in hist if h["days"] == 0], T.INK_300,
                      panel["unchanged"]),
        "Later": ([h["days"] for h in hist if h["days"] > 0],
                  [h["count"] for h in hist if h["days"] > 0], T.NEGATIVE,
                  panel["later"]),
    }

    fig = go.Figure()
    for name, (x, y, colour, total) in series.items():
        if not x:
            continue
        fig.add_trace(go.Bar(
            x=x, y=y, name=f"{name} — {total}", marker=dict(color=colour),
            hovertemplate="%{y} shipments %{x:+d} days<extra></extra>"))

    moved = [h["count"] for h in hist if h["days"] != 0]
    peak = max(moved) if moved else 1
    unchanged = panel["unchanged"]
    if unchanged > 2.2 * peak:
        fig.update_yaxes(range=[0, peak * 1.45])
        fig.add_annotation(
            x=0, y=peak * 1.42, yanchor="top", showarrow=False,
            text=f"<b>{unchanged} unchanged</b><br><span style='font-size:10px'>"
                 "bar clipped</span>",
            font=dict(size=11.5, color=T.INK_600), align="center")

    lo, hi = EXPECTATION_DAYS
    fig.add_vrect(x0=lo, x1=hi, fillcolor=T.NEGATIVE, opacity=0.07, line_width=0)
    fig.add_annotation(
        x=(lo + hi) / 2, y=0.72, yref="paper", ax=62, ay=-52, xanchor="left",
        text=f"Usually assumed:<br>+{lo} to +{hi} days",
        font=dict(size=10.5, color=T.NEGATIVE), align="left",
        arrowcolor=T.NEGATIVE, arrowwidth=1, arrowsize=1.1, arrowhead=2)
    fig.add_annotation(
        x=panel["mean_delta"], y=0.30, yref="paper", ax=-70, ay=-46,
        xanchor="right", text=f"<b>Mean: {panel['mean_delta']:+.2f} days</b>",
        font=dict(size=11, color=T.INK_700), align="left",
        arrowcolor=T.INK_600, arrowwidth=1, arrowsize=1.1, arrowhead=2)

    fig.add_vline(x=0, line=dict(color=T.INK_300, width=1))
    fig.update_xaxes(title=dict(text="Days earlier (−) or later (+) than today",
                                font=dict(size=11, color=T.INK_500)))
    fig.update_yaxes(title=dict(text="Shipments", font=dict(size=11, color=T.INK_500)))
    fig.update_layout(bargap=0.15)
    fig = _shell(fig, height=340, legend=True)
    # _shell's margins are built for a chart with no axis titles. These two have both,
    # and an axis title drawn into an 8px margin lands on top of the note underneath.
    fig.update_layout(margin=dict(l=52, r=10, t=34, b=52))
    return fig


BUCKET_COLOUR = {
    "8+ days earlier": T.POSITIVE,
    "1–7 days earlier": T.POSITIVE,
    "No change": T.INK_300,
    "1–7 days later": T.NEGATIVE,
    "8–14 days later": T.NEGATIVE,
    "15+ days later": T.NEGATIVE,
}


def origin_buckets(panel):
    """The same shipments as six named outcomes, counted and shared."""
    rows = list(reversed(panel.get("buckets") or []))
    if not rows:
        return None
    biggest = max(r["count"] for r in rows) or 1

    fig = go.Figure(go.Bar(
        x=[r["count"] for r in rows], y=[r["label"] for r in rows], orientation="h",
        marker=dict(color=[BUCKET_COLOUR.get(r["label"], T.INK_400) for r in rows]),
        text=[f"  {r['count']}   {r['share']:.0%}" for r in rows],
        textposition="outside", textfont=dict(size=11.5, color=T.INK_600),
        cliponaxis=False,
        hovertemplate="%{y}: %{x} shipments<extra></extra>"))
    fig.update_xaxes(range=[0, biggest * 1.3], showticklabels=False, showgrid=False,
                     showline=False, title=None)
    fig.update_yaxes(showgrid=False, showline=True, linecolor=T.INK_300,
                     tickfont=dict(size=11.5, color=T.INK_600))
    fig.update_layout(bargap=0.42)
    fig = _shell(fig, height=340)
    # Room for the outcome names on the left and for the count and share on the right.
    fig.update_layout(margin=dict(l=122, r=62, t=34, b=18))
    return fig


def lane_risk_chart(risk, per_origin=6):
    """Where the later arrivals sit, as each lane's share of its own shipments.

    Stacked by how late, because "12% late" reads very differently when the twelve
    percent is three days than when it is a fortnight, and one bar can carry both.
    """
    lanes = [r for r in (risk.get("lanes") or []) if r["late"]]
    if not lanes:
        return None
    # Origins in order of how much cargo they ship, so the biggest panel is read first.
    # Ordering them by whichever happened to hold the single worst lane put a six-shipment
    # origin above one carrying two hundred.
    size = {}
    for r in risk["lanes"]:
        size[r["origin"]] = size.get(r["origin"], 0) + r["shipments"]
    origins = sorted({r["origin"] for r in lanes}, key=lambda o: -size.get(o, 0))

    shown = {o: [r for r in lanes if r["origin"] == o][:per_origin] for o in origins}
    origins = [o for o in origins if shown[o]]
    heights = [len(shown[o]) for o in origins]

    titles = []
    for o in origins:
        at = [r for r in risk["lanes"] if r["origin"] == o]
        ships = sum(r["shipments"] for r in at)
        late = sum(r["late"] for r in at)
        titles.append(f"<b>{o}</b>  ·  {late} of {ships} shipments late "
                      f"({late / max(1, ships):.0%})")

    fig = make_subplots(rows=len(origins), cols=1, shared_xaxes=True,
                        row_heights=[h / sum(heights) for h in heights],
                        vertical_spacing=0.14 / max(1, len(origins)),
                        subplot_titles=titles)

    colours = [_alpha(T.NEGATIVE, a) for a in (0.25, 0.48, 0.72, 1.0)]
    for i, origin in enumerate(origins, start=1):
        rows = list(reversed(shown[origin]))
        labels = [f"{r['site']}  n={r['shipments']}" for r in rows]
        for b, colour in enumerate(colours):
            fig.add_trace(go.Bar(
                y=labels, x=[r["buckets"][b]["share"] for r in rows], orientation="h",
                name=rows[0]["buckets"][b]["label"], marker=dict(color=colour),
                legendgroup=rows[0]["buckets"][b]["label"], showlegend=(i == 1),
                hovertemplate="%{y}<br>%{customdata} shipments "
                              + rows[0]["buckets"][b]["label"] + "<extra></extra>",
                customdata=[r["buckets"][b]["count"] for r in rows]),
                row=i, col=1)
        for r, label in zip(rows, labels):
            fig.add_annotation(
                x=r["late_share"], y=label, xanchor="left", xshift=8, showarrow=False,
                text=f"{r['late_share']:.0%}  <span style='color:{T.INK_400}'>"
                     f"({r['late']} of {r['shipments']} late)</span>",
                font=dict(size=11, color=T.INK_600), row=i, col=1)

    top = max(r["late_share"] for r in lanes)
    fig.update_layout(barmode="stack", bargap=0.34)
    fig.update_xaxes(range=[0, top * 1.42], tickformat=".0%", showgrid=True,
                     gridcolor=T.INK_100, showline=False)
    fig.update_yaxes(showgrid=False, showline=True, linecolor=T.INK_300,
                     tickfont=dict(size=11, color=T.INK_600))
    fig.update_xaxes(title=dict(text="Share of the lane's own shipments that arrive late",
                                font=dict(size=11, color=T.INK_500)),
                     row=len(origins), col=1)
    fig = _shell(fig, height=120 + 46 * sum(heights) + 30 * len(origins), legend=True)
    # Destination names on the left and the "16% (9 of 56 late)" reading on the right both
    # sit outside the plot area, and _shell's 8px margins clip them to single characters.
    # Top margin allows for the legend wrapping to two rows in a narrow column, which it
    # does at the width this sits in; below this the second row landed on the first
    # origin's heading.
    fig.update_layout(margin=dict(l=136, r=130, t=110, b=48),
                      legend=dict(y=1.13))
    for note in fig.layout.annotations[:len(origins)]:
        note.update(font=dict(size=12.5, color=T.INK_700), x=0, xanchor="left")
    return fig


def warehouse_containers(containers):
    """The containers that actually pass through the consolidation warehouse.

    Declined lanes are represented in the model as their as-shipped boxes so their
    count and invoice cost remain visible.  They never visit the warehouse, though,
    and therefore do not belong in either a warehouse-dwell or dispatch-reason chart.
    Keeping the filter here gives both charts one explicit, shared population.
    """
    con = pd.DataFrame(containers)
    if con.empty:
        return con
    if "passthrough" in con.columns:
        con = con[~con["passthrough"].fillna(False).astype(bool)]
    elif "consolidated" in con.columns:
        con = con[con["consolidated"].fillna(True).astype(bool)]
    return con


def dwell_distribution(containers, cap):
    """How long warehouse-built containers wait, against the cap that governs them.

    The cap line is the point of the chart: it shows the distribution pressed up
    against a service commitment rather than running past it.
    """
    con = warehouse_containers(containers)
    if con.empty:
        return None
    counts = con["dwell_days"].value_counts().sort_index()
    colours = [T.WARNING if k >= cap else T.BRAND_400 for k in counts.index]

    fig = go.Figure(go.Bar(
        x=counts.index, y=counts.values, marker=dict(color=colours),
        hovertemplate="%{y} containers waited %{x} days<extra></extra>"))
    fig.add_vline(x=cap, line=dict(color=T.NEGATIVE, width=1.5, dash="dash"),
                  annotation_text=f"{cap}-day cap",
                  annotation_font=dict(size=10.5, color=T.NEGATIVE),
                  annotation_position="top right")
    fig.update_xaxes(title=dict(text="days held at the warehouse",
                                font=dict(size=11, color=T.INK_400)))
    fig.update_yaxes(title=dict(text="containers", font=dict(size=11, color=T.INK_400)))
    return _shell(fig, height=280)


def fill_comparison(summary, containers, cap):
    """How full a container is today against how full the plan makes it."""
    con = pd.DataFrame(containers)
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=con["cbm"], nbinsx=26, marker=dict(color=T.BRAND_400),
        name="Modelled", hovertemplate="%{y} containers at %{x} CBM<extra></extra>"))
    fig.add_vline(x=summary["today_fill_cbm"],
                  line=dict(color=T.INK_400, width=1.5, dash="dot"),
                  annotation_text=f"today {summary['today_fill_cbm']} CBM",
                  annotation_font=dict(size=10.5, color=T.INK_500),
                  annotation_position="top left")
    fig.add_vline(x=cap, line=dict(color=T.NEGATIVE, width=1.5, dash="dash"),
                  annotation_text=f"cap {cap}", annotation_position="top right",
                  annotation_font=dict(size=10.5, color=T.NEGATIVE))
    fig.update_xaxes(title=dict(text="container volume, CBM",
                                font=dict(size=11, color=T.INK_400)))
    fig.update_yaxes(title=dict(text="containers", font=dict(size=11, color=T.INK_400)))
    return _shell(fig, height=280)


def rate_provenance(rates):
    """How many rates came from where, and the dollars behind each source."""
    order = ["CLIENT_RATE_CARD", "DERIVED_FROM_INVOICES",
             "QUOTED_NOT_YET_BOUGHT", "CLIENT_ASSUMPTION"]
    counts = rates["source"].value_counts()
    present = [s for s in order if s in counts.index]
    colours = {"CLIENT_RATE_CARD": T.BRAND_500,
               "DERIVED_FROM_INVOICES": T.POSITIVE,
               "QUOTED_NOT_YET_BOUGHT": T.BRAND_300,
               "CLIENT_ASSUMPTION": T.WARNING}

    fig = go.Figure(go.Bar(
        x=[counts[s] for s in present],
        y=[T.SOURCE_LABEL[s] for s in present],
        orientation="h",
        marker=dict(color=[colours[s] for s in present]),
        text=[f"{counts[s]} rates" for s in present],
        textposition="auto", textfont=dict(size=11, color="#fff"),
        hovertemplate="%{y}: %{x} rates<extra></extra>"))
    fig.update_xaxes(showgrid=True, gridcolor=T.INK_100, showline=False)
    fig.update_yaxes(showgrid=False)
    return _shell(fig, height=190)


def derived_vs_observed(rates):
    """Each derived rate against the spread of what was actually paid.

    The credibility chart. A single reconstructed number means little; the same
    number shown sitting inside the range of invoices it came from is evidence.
    """
    d = rates[rates["source"].eq("DERIVED_FROM_INVOICES")
              & rates["observed_min"].notna()
              & rates["category"].isin(["DEST_DELIVERY", "OCEAN"])].copy()
    if not len(d):
        return None
    d = d.sort_values("rate_usd")
    label = d["node_from"].str.split(",").str[0] + " → " + d["node_to"]

    fig = go.Figure()
    for i, r in enumerate(d.to_dict("records")):
        fig.add_trace(go.Scatter(
            x=[r["observed_min"], r["observed_max"]], y=[i, i],
            mode="lines", line=dict(color=T.INK_300, width=3),
            hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(
        x=d["observed_median"], y=list(range(len(d))), mode="markers",
        marker=dict(color=T.INK_400, size=7, symbol="line-ns-open"),
        name="median invoiced",
        hovertemplate="median invoiced $%{x:,.0f}<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=d["rate_usd"], y=list(range(len(d))), mode="markers",
        marker=dict(color=T.POSITIVE, size=10, line=dict(color="#fff", width=1.5)),
        name="rate used",
        hovertemplate="derived rate $%{x:,.0f}<extra></extra>"))
    fig.update_yaxes(tickmode="array", tickvals=list(range(len(d))),
                     ticktext=label.tolist(), showgrid=False,
                     tickfont=dict(size=10.5))
    fig.update_xaxes(tickprefix="$", showgrid=True, gridcolor=T.INK_100,
                     showline=False)
    return _shell(fig, height=max(220, 34 * len(d) + 60), legend=True)


def dispatch_reasons(containers):
    """Why warehouse-built containers left -- the best read on dispatch quality."""
    con = warehouse_containers(containers)
    if con.empty:
        return None
    reasons = con["dispatch_reason"].value_counts().to_dict()
    pretty = {
        "target_reached": "Reached the dispatch target",
        "no_qualifying_arrival": "No further cargo due in time",
        "max_dwell_reached": "Hit the dwell cap",
        "end_of_history": "Still filling when the data ends",
    }
    items = sorted(reasons.items(), key=lambda t: -t[1])
    colours = {"target_reached": T.POSITIVE,
               "no_qualifying_arrival": T.WARNING,
               "max_dwell_reached": T.NEGATIVE,
               "end_of_history": T.INK_300}
    fig = go.Figure(go.Bar(
        x=[v for _, v in items],
        y=[pretty.get(k, k) for k, _ in items],
        orientation="h",
        marker=dict(color=[colours.get(k, T.BRAND_400) for k, _ in items]),
        text=[f"{v}" for _, v in items], textposition="auto",
        textfont=dict(size=11, color="#fff"),
        hovertemplate="%{y}: %{x} containers<extra></extra>"))
    fig.update_xaxes(showgrid=True, gridcolor=T.INK_100, showline=False)
    fig.update_yaxes(showgrid=False, tickfont=dict(size=10.5))
    return _shell(fig, height=210)
