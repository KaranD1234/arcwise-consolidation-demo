"""Reusable pieces of the interface.

Most of these render hand-written HTML rather than using the equivalent Streamlit widget.
That is deliberate for the KPI tiles and the progress rail in particular: the stock
versions are instantly recognisable, and a prospect who recognises the framework starts
evaluating the prototype instead of the analysis.

Two rules run through all of it. **Every word has to do a job** — a sentence that reassures
without informing is a sentence a product would not ship, and there were a lot of them in
here. And **a mark that is only a mark is an icon, not a character**: ticks, warnings and
locks are Tabler glyphs from ``theme.icon``, not HTML entities and an emoji.
"""

import html

import streamlit as st

import theme as T

STEPS = [
    ("data", "Data"),
    ("references", "References"),
    ("resolve", "Resolve"),
    ("assumptions", "Settings"),
    ("build", "Build"),
    ("results", "Results"),
]


def rail(current):
    """The progress rail. Always visible, so the shape of the flow is never a mystery."""
    order = [k for k, _ in STEPS]
    here = order.index(current) if current in order else 0
    chunks = []
    for i, (key, label) in enumerate(STEPS):
        state = "now" if i == here else ("done" if i < here else "")
        mark = T.icon("check", 13, stroke=2.2) if i < here else str(i + 1)
        chunks.append(f'<div class="aw-step {state}"><span class="n">{mark}</span>{label}</div>')
    st.markdown(f'<div class="aw-rail">{"".join(chunks)}</div>', unsafe_allow_html=True)


def h(text, level=3, margin="0 0 8px 0"):
    """A heading, on the product's type scale. See ``theme.heading``."""
    st.markdown(T.heading(text, level, margin=margin), unsafe_allow_html=True)


def lede(text):
    """The one line under a step heading. One line: if it needs two, it needs cutting."""
    st.markdown(f'<div class="aw-lede">{text}</div>', unsafe_allow_html=True)


def eyebrow(text):
    st.markdown(f'<div class="aw-eyebrow">{html.escape(text)}</div>', unsafe_allow_html=True)


def note(text, cls="aw-note", style=""):
    st.markdown(f'<div class="{cls}" style="{style}">{text}</div>', unsafe_allow_html=True)


def card(title, body, extra=""):
    st.markdown(
        f'<div class="aw-card"><div class="aw-card-title">{title}</div>'
        f'<div class="aw-card-sub">{body}</div>{extra}</div>',
        unsafe_allow_html=True)


def kpis(tiles, columns=None, hero_span=1):
    """Hand-built KPI tiles.

    ``tiles`` is a list of dicts: ``label``, ``value``, optional ``delta`` and ``tone``
    ("up" | "down" | "flat"), optional ``hero`` to highlight the headline. The tone is
    carried by colour alone.

    It briefly had a trend arrow too, and the arrow was wrong twice on the same screen: a
    tile whose good news is *fewer* containers, or a cost that went *down*, is an
    improvement pointing downwards, and an up-arrow beside the words "101 fewer" asks the
    reader to resolve a contradiction that the colour had already settled.

    ``hero_span`` lets the headline occupy more than one column, which is what makes seven
    facts fit a four-column grid as two full rows. Whichever way the numbers fall, the last
    tile then widens to close the row: how many tiles there are depends on whether the file
    has LCL cargo and whether any lane was declined, so a fixed grid leaves a hole on some
    datasets and not others, and a hole in a row of cards is what reads as unfinished.
    """
    columns = columns or len(tiles)
    cells_used = hero_span + max(0, len(tiles) - 1)
    remainder = cells_used % columns
    cells = []
    for i, t in enumerate(tiles):
        delta = ""
        if t.get("delta"):
            delta = (f'<div class="delta {t.get("tone", "flat")}">'
                     f'<span>{t["delta"]}</span></div>')
        width = hero_span if t.get("hero") else 1
        if remainder and i == len(tiles) - 1:
            width += columns - remainder
        span = f'style="grid-column:span {width};"' if width > 1 else ""
        cells.append(
            f'<div class="aw-kpi{" hero" if t.get("hero") else ""}" {span}>'
            f'<div class="label">{t["label"]}</div>'
            f'<div class="value">{t["value"]}</div>{delta}</div>')
    st.markdown(
        f'<div class="aw-kpis" style="grid-template-columns:repeat({columns},1fr);">'
        f'{"".join(cells)}</div>',
        unsafe_allow_html=True)


def provenance_strip(summary, parameters=()):
    """Where the prices came from, as the numbers themselves.

    This is the pitch rendered as a fact rather than a claim, which is why it sits directly
    under the headline instead of in a footnote.
    """
    p = summary["provenance"]
    # Benchmark pricing is not an available model state: an unpriced consolidation service
    # stops the build. Show the evidence that was actually used, not a reassuring zero for
    # a source the app does not permit.
    cells = [
        (p["rates_from_card"], "From your rate card", False),
        (p["rates_derived"], "Derived from your invoices", False),
        (p["rates_quoted"], "From your forwarder's quote", False),
        (0, "Invented", True),
    ]
    inner = "".join(
        f'<div class="{"zero" if zero else ""}"><div class="n">{n}</div>'
        f'<div class="k">{k}</div></div>'
        for n, k, zero in cells)
    st.markdown(f'<div class="aw-prov">{inner}</div>', unsafe_allow_html=True)
    share = p["assumed_share"]
    st.markdown(
        "<div class='aw-note' style='margin:-6px 0 18px 2px;'>"
        + (f"{p['evidenced_share']:.0%} of the modelled cost is evidenced — your card, "
           "your invoices, your forwarder's quote. "
           "Nothing rests on a figure we made up."
           if share == 0 else
           f"This result contains {share:.0%} unsupported modelled cost and must not be "
           "presented until those rates are supplied.")
        + "".join(f" {p_}" for p_ in parameters)
        + "</div>", unsafe_allow_html=True)


def finding(text):
    st.markdown(
        f'<div class="aw-finding">{T.icon("check", 14, stroke=2)}'
        f'<span>{html.escape(text)}</span></div>',
        unsafe_allow_html=True)


def applied(label, value, source=""):
    """A constant the engine just used, named as it is used.

    Label and figure, not a sentence. Forty of these run down the build screen, and the
    word "applying" in front of every one of them was forty words carrying no information.
    """
    tail = f' <span class="aw-micro">{html.escape(source)}</span>' if source else ""
    st.markdown(
        f'<div class="aw-applied"><span class="k">{html.escape(label)}</span>'
        f'<span class="v">{html.escape(str(value))}</span>{tail}</div>',
        unsafe_allow_html=True)


def confidence(level):
    return T.pill(level.capitalize(), T.CONFIDENCE_COLOUR.get(level, T.INK_400))


def verdict(v):
    return T.pill(v, T.VERDICT_COLOUR.get(v, T.INK_400))


def source_pill(source):
    colour = {
        "CLIENT_RATE_CARD": T.BRAND_500,
        "DERIVED_FROM_INVOICES": T.POSITIVE,
        "CLIENT_ASSUMPTION": T.WARNING,
        "ACTUAL_INVOICE": T.INK_400,
    }.get(source, T.INK_400)
    return T.pill(T.SOURCE_LABEL.get(source, source), colour)


def money(v, decimals=0):
    return f"${v:,.{decimals}f}"


def profile_row(pairs):
    """A compact fact list, used to show a file back to the person who uploaded it."""
    cells = "".join(
        f'<div style="flex:1 1 130px;padding:12px 16px;border-right:1px solid {T.INK_200};">'
        f'<div style="font-size:18px;font-weight:500;color:{T.INK_700};'
        f'font-variant-numeric:tabular-nums;">{v}</div>'
        f'<div style="font-size:12px;color:{T.INK_500};margin-top:2px;">{k}</div></div>'
        for k, v in pairs)
    st.markdown(
        f'<div style="display:flex;flex-wrap:wrap;background:{T.SURFACE_CARD};'
        f'border:1px solid {T.INK_200};border-radius:10px;overflow:hidden;'
        f'box-shadow:{T.SHADOW_SOFT};margin-bottom:14px;">{cells}</div>',
        unsafe_allow_html=True)


def locked_rate(label, value, tag, tone="theirs"):
    """A figure shown as a fact rather than a setting, in place of an input for it.

    Two tones, and the difference between them is the whole point of the screen. ``theirs``
    is a rate out of the client's own quote: brand blue, ticked. ``ours`` is our benchmark
    standing in until they have a number: grey, marked amber, because a figure of ours must
    never wear the same colours as a figure of theirs.

    Built to occupy the same space as the number input it replaces -- label, then a field
    the same height, then a line where that field's caption would be -- so a row holding
    some locked figures and some open ones still reads as a row. The pixel figures are
    measured against a real st.number_input: 36px of field under a 14px label.
    """
    theirs = tone == "theirs"
    edge = T.BRAND_200 if theirs else T.INK_200
    fill = T.BRAND_50 if theirs else T.SURFACE_PAGE
    ink = T.BRAND_600 if theirs else T.INK_500
    mark = (T.icon("check", 13, T.POSITIVE, stroke=2.2) if theirs
            else T.icon("alert", 13, T.WARNING))
    st.markdown(
        f'<div style="margin-bottom:2px;">'
        f'<div style="font-size:14px;font-weight:500;line-height:1.4;color:{T.INK_700};'
        f'margin-bottom:8px;">{html.escape(label)}</div>'
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'gap:8px;height:36px;padding:0 12px;border:1px solid {edge};'
        f'border-radius:6px;background:{fill};">'
        f'<span style="font-size:14px;font-weight:500;color:{ink};'
        f'font-variant-numeric:tabular-nums;">{html.escape(value)}</span>'
        f'{T.icon("lock", 14, T.BRAND_400 if theirs else T.INK_300)}</div>'
        f'<div style="height:24px;display:flex;align-items:center;gap:5px;'
        f'margin-top:18px;">{mark}'
        f'<span style="font-size:11px;color:{T.INK_500};">{html.escape(tag)}</span>'
        f'</div></div>',
        unsafe_allow_html=True)


def panel_head(eyebrow_text, headline, subtitle, caption=""):
    """A slide's worth of framing above a chart: what it is, what it says, what it covers.

    Modelled on the deck this lead-time analysis was first presented in, where the headline
    was the finding rather than the chart's name -- "157 of 214 shipments have the same
    delivery date", not "lead time distribution". Every word of it is rendered from the run,
    so it cannot say something the chart underneath does not show.
    """
    st.markdown(
        f'<div style="margin:6px 0 2px 0;">'
        f'<div class="aw-eyebrow">{html.escape(eyebrow_text)}</div>'
        + T.heading(headline, 3, margin="0 0 6px 0")
        + f'<div style="font-size:13px;font-weight:500;color:{T.PANEL_ACCENT};">'
          f'{subtitle}</div>'
        + (f'<div class="aw-note" style="margin-top:5px;">{html.escape(caption)}</div>'
           if caption else "")
        + '</div>', unsafe_allow_html=True)


def panel_note(text):
    """The exclusions, under the chart they were excluded from."""
    st.markdown(
        f'<div class="aw-note" style="margin:-4px 0 12px 2px;max-width:780px;">{text}</div>',
        unsafe_allow_html=True)


def panel_callout(text, tone="quiet"):
    """The one sentence to leave the room with. ``strong`` is the section's conclusion."""
    if tone == "strong":
        return st.markdown(
            f'<div style="background:{T.BRAND_600};border-radius:10px;padding:14px 18px;'
            f'margin:6px 0 4px 0;font-size:13px;line-height:1.6;color:#EAF1FA;">'
            f'{text}</div>', unsafe_allow_html=True)
    return st.markdown(
        f'<div style="background:{T.INK_50};border:1px solid {T.INK_200};'
        f'border-radius:10px;padding:13px 18px;margin:6px 0 4px 0;font-size:13px;'
        f'line-height:1.6;color:{T.INK_600};">{text}</div>', unsafe_allow_html=True)


def stat_block(items):
    """A figure, then the sentence that says why it matters. The deck's right-hand rail."""
    body = "".join(
        f'<div style="margin-bottom:16px;">'
        f'<div style="font-size:24px;font-weight:500;color:{T.PANEL_ACCENT};'
        f'font-variant-numeric:tabular-nums;line-height:1.2;">{v}</div>'
        f'<div style="font-size:12px;color:{T.INK_600};line-height:1.55;margin-top:3px;">'
        f'{k}</div></div>'
        for v, k in items)
    st.markdown(
        f'<div style="background:{T.INK_50};border-radius:10px;padding:18px 20px 2px 20px;">'
        f'{body}</div>', unsafe_allow_html=True)


FILE_STATUS = {
    "given": ("Given", T.POSITIVE, "file-check"),
    "needed": ("Needed", T.NEGATIVE, "file"),
    "optional": ("Optional", T.INK_400, "file"),
}


def file_row(doc, status, detail):
    """One file this app can take, as a row in the inventory.

    The name is the loudest thing on the row and the upload control is the quietest, which
    is the opposite of a plain file-picker layout. Somebody reading this step is asking what
    files we want, not looking for somewhere to drop one -- three identical grey dropzones
    answer the second question and bury the first.
    """
    label, colour, glyph = FILE_STATUS[status]
    return f"""<div class="aw-filerow" style="display:flex;gap:11px;align-items:flex-start;
     padding:11px 2px;border-bottom:1px solid {T.INK_100};">
  <div style="margin-top:2px;">{T.icon(glyph, 16, colour, stroke=1.6)}</div>
  <div style="flex:1 1 auto;">
    <div style="font-size:14px;font-weight:500;color:{T.INK_700};">
      {html.escape(doc["name"])}
      <span class="aw-pill" style="color:{colour};background:{colour}14;
            border:1px solid {colour}33;margin-left:6px;vertical-align:1px;">{label}</span></div>
    <div class="aw-note" style="margin-top:3px;">{html.escape(doc["holds"])}</div>
    <div style="font-size:11px;line-height:1.5;margin-top:3px;
         color:{colour if status == "needed" else T.INK_400};">{detail}</div>
  </div>
</div>"""


def named(docs):
    """A list of documents as a phrase.

    Naming the document back is what turns a file-picker into something that appears to be
    paying attention -- and it is the only way the person uploading finds out that the
    engine identifies these files by their contents rather than by which box they went in.
    """
    docs = [html.escape(d) for d in docs]
    if len(docs) == 1:
        return docs[0]
    return ", ".join(docs[:-1]) + f" and {docs[-1]}"


def _callout(text, colour, glyph):
    return st.markdown(
        f'<div class="aw-callout" style="background:{colour}0D;'
        f'border:1px solid {colour}2E;">{T.icon(glyph, 15, colour, stroke=2)}'
        f'<span>{text}</span></div>', unsafe_allow_html=True)


def summary_line(text, tone="ok"):
    colour = {"ok": T.POSITIVE, "ask": T.BRAND_500, "warn": T.WARNING}.get(tone, T.INK_400)
    glyph = {"ok": "check", "ask": "arrow-right", "warn": "alert"}.get(tone, "info")
    return _callout(text, colour, glyph)


def explain(label, body, expanded=False):
    """A data-bound explanation. Never canned -- always rendered from the result."""
    with st.expander(label, expanded=expanded):
        st.markdown(
            f'<div style="font-size:13px;line-height:1.65;color:{T.INK_600};">'
            + "".join(f"<p style='margin:0 0 10px 0;'>{html.escape(p)}</p>"
                      for p in body.split("\n\n") if p.strip())
            + "</div>",
            unsafe_allow_html=True)


def controls_strip(controls_summary):
    """The checks, and — when one fails — what it means and what to do.

    A failure used to render as the check's name after the word FAILED, which reads as "the
    software broke" and gives the reader nothing to act on. The two kinds of failure are not
    the same event: an ``integrity`` failure is our arithmetic and the figures must not be
    used; a ``fit`` failure is the model not yet reproducing this particular file, which is
    answerable with another rate card.

    When every check passes the strip says so and stops. The sentence that used to follow --
    "every check that must pass before a number leaves this screen" -- was reassurance, and
    the green tick had already given it.
    """
    ok = controls_summary["all_passed"]
    broken = bool(controls_summary.get("integrity_failed"))
    colour = T.POSITIVE if ok else (T.NEGATIVE if broken else T.WARNING)
    text = (f'{controls_summary["controls_passed"]} of '
            f'{controls_summary["controls_total"]} controls passed')
    detail = ("" if ok else
              "the arithmetic does not hold — these figures should not be used" if broken
              else "the model does not yet reproduce this file closely enough")
    st.markdown(
        f'<div class="aw-callout" style="background:{colour}0F;border:1px solid {colour}33;'
        f'align-items:center;">{T.icon("check" if ok else "alert", 15, colour, stroke=2)}'
        f'<span style="color:{T.INK_700};">{text}</span>'
        + (f'<span class="aw-note">{detail}</span>' if detail else "")
        + '</div>', unsafe_allow_html=True)
    for c in controls_summary.get("failed", []):
        edge = T.NEGATIVE if c["kind"] == "integrity" else T.WARNING
        st.markdown(
            f'<div style="border-left:2px solid {edge};padding:2px 0 2px 12px;'
            f'margin:-8px 0 14px 4px;">'
            f'<div style="font-size:13px;font-weight:500;color:{T.INK_700};">'
            f'{html.escape(c["name"])}'
            + (f' <span class="aw-micro" style="display:inline;">'
               f'({html.escape(c["tolerance"])})</span>' if c["tolerance"] else "")
            + f'</div><div class="aw-note" style="margin-top:2px;">'
            f'{html.escape(c["detail"])}</div>'
            + (f'<div style="font-size:12px;color:{edge};line-height:1.55;margin-top:4px;">'
               f'{html.escape(c["remedy"])}</div>' if c["remedy"] else "")
            + '</div>', unsafe_allow_html=True)
