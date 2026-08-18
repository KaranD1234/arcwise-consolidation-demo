"""Arcwise design tokens, and the CSS that stops this looking like Streamlit.

These shared values are the source of truth for the demo UI. They keep native Streamlit
components and the custom interface visually consistent:

* **Type.** Inter. Body 14/1.6, captions 12, micro 11. Headings are the Mantine ``Title``
  scale — 28 / 24 / 20 / 16 / 14 / 12 — at **weight 500**, line-height 1.2, and no
  letter-spacing. The app has no negative tracking and no 600-weight headings anywhere.
* **Weight.** 400 for everything, 500 for headings, labels and the one active nav item,
  600 only for a link. Faux weights (560, 620, 680) were the loudest tell in here.
* **Radius.** 4 badge, 6 button and input, 8 inner, 10 card. Not a 999px pill in sight:
  ``Badge`` defaults to ``radius="xs"``.
* **Colour.** Body text is ``dark.6``, muted text ``dark.5``, headings ``dark.7``. Accents
  are load-bearing only — green for a pass, red for a stop, amber for a caveat.

Two further rules the product keeps and a dashboard tends not to: nothing is UPPERCASE,
and there are no gradients. Both were in here, and both read as decoration applied to a
prototype rather than as a product's own surface.

The chrome removal below is not housekeeping either. A prospect who recognises the
framework stops looking at the analysis and starts assessing the prototype, so the
hamburger, the footer, the deploy badge and the default top padding all have to go.
"""

import base64
import html as _html
from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# --- brand blue -----------------------------------------------------------------
BRAND_50 = "#EBF2FA"
BRAND_100 = "#D4E6F5"
BRAND_200 = "#A8C4E2"
BRAND_300 = "#7BA3CF"
BRAND_400 = "#4E81BC"
BRAND_500 = "#2E5F9A"
BRAND_600 = "#0D2E5E"
BRAND_700 = "#0A2448"
BRAND_800 = "#071A36"
BRAND_900 = "#040F1E"
BRAND_LOGO = "#093796"

# --- ink / neutral --------------------------------------------------------------
INK_50 = "#F4F7FB"
INK_100 = "#EEF2F8"
INK_200 = "#E8EDF5"
INK_300 = "#D6DCE8"
INK_400 = "#8A97AB"
INK_500 = "#6B7A8F"
INK_600 = "#3D4E63"
INK_700 = "#0F1828"
INK_800 = "#0A1018"
INK_900 = "#050810"

# --- semantic accents, used sparingly ------------------------------------------
POSITIVE = "#10B981"
NEGATIVE = "#C0362A"
WARNING = "#F59E0B"

SURFACE_PAGE = "#FBFCFE"
SURFACE_CARD = "#FFFFFF"
SURFACE_INPUT = "#FEFEFF"

# Categorical series for charts: the brand ramp, darkest first, so a two-series
# chart reads as one system rather than as two unrelated colours.
SERIES = [BRAND_600, BRAND_400, BRAND_300, BRAND_500, BRAND_200, INK_400]

SHADOW_SOFT = "0 2px 4px rgba(13, 46, 94, 0.07)"
SHADOW_CARD = "0 4px 12px rgba(13, 46, 94, 0.10)"
SHADOW_FLOAT = "0 8px 24px rgba(13, 46, 94, 0.12)"

CONFIDENCE_COLOUR = {
    "HIGH": POSITIVE, "MEDIUM": WARNING, "LOW": NEGATIVE, "DECLARED": BRAND_400,
}

VERDICT_COLOUR = {
    "Consolidate": POSITIVE, "Marginal": WARNING, "Leave alone": INK_400,
}

SOURCE_LABEL = {
    "CLIENT_RATE_CARD": "From your rate card",
    "DERIVED_FROM_INVOICES": "Derived from your invoices",
    "QUOTED_NOT_YET_BOUGHT": "Your forwarder's quote",
    "CLIENT_ASSUMPTION": "Our benchmark, not yours",
    "ACTUAL_INVOICE": "Actual invoiced cost",
}

# --- the sourcing states --------------------------------------------------------
#
# These are not rendered as cards any more -- step 2 is a four-row file list, and what the
# engine could and could not price is reported on Results, after the run, where it is
# output to react to rather than configuration to study. The vocabulary is kept because
# `sourcing.py` still returns these states and the findings on Results read from them.
#
# One entry per state a cost component can be in. Colour carries the meaning, so the
# assignment matters more than it looks: brand blue for a contracted rate, green for a
# rate rebuilt from the client's own money, amber for anything qualified, red for a leg
# we will not price without being told, and one state that is not about the past at all --
# an alternative worth testing that nobody has given us a rate for.
#
# That last one was violet, which is a colour the product does not own. It is brand blue
# now: an opportunity is the one thing on the board we are asking for, and asking is what
# the primary colour is for.
OPPORTUNITY = BRAND_500

STATE = {
    "card": {"label": "From your rate card", "colour": BRAND_500,
             "gloss": "A contracted rate. What you will actually be billed."},
    "derived": {"label": "Derived from your invoices", "colour": POSITIVE,
                "gloss": "Rebuilt from your own charge lines — your money, your volumes."},
    "analogue": {"label": "Derived by analogy", "colour": WARNING,
                 "gloss": "The right kind of charge on the wrong leg. Directionally "
                          "sound, and not the real rate."},
    "thin": {"label": "Too few invoices", "colour": WARNING,
             "gloss": "A population exists but is too small to be a rate."},
    "quoted": {"label": "Your forwarder's quote", "colour": BRAND_400,
               "gloss": "Work you do not buy today, priced by the forwarder proposing it."},
    "benchmark": {"label": "Our benchmark", "colour": WARNING,
                  "gloss": "Our figure, standing in until you have a quote."},
    "unpriced": {"label": "Nothing here can price this", "colour": NEGATIVE,
                 "gloss": "We will not reach for a number. Give us a rate card."},
    "opportunity": {"label": "Worth testing", "colour": OPPORTUNITY,
                    "gloss": "A cheaper way of buying this leg that you have given us "
                             "no rate for."},
}

STATE_ORDER = ["card", "derived", "quoted", "analogue", "thin", "benchmark", "unpriced"]

# The accent on the lead-time panels. It was gold, carried over from the deck this
# analysis was first presented in -- a colour that appears nowhere in the product. Brand
# blue instead: one system, and nothing on screen has to work out what gold means.
PANEL_ACCENT = BRAND_500


# --- icons ----------------------------------------------------------------------
#
# Tabler, which is what the product draws from (303 imports of @tabler/icons-react
# against 64 of anything else). Inlined as paths rather than pulled from a CDN, and
# stroked in currentColor so an icon inherits the colour of the thing it marks.
#
# They are here to replace glyphs, not to decorate: a padlock emoji, a bare "!" in a
# circle and a HTML-entity tick were doing the work of an icon set and reading as three
# unrelated pieces of punctuation.
_ICONS = {
    "check": ["M5 12l5 5l10 -10"],
    "alert": ["M12 9v4", "M10.363 3.591l-8.106 13.534a1.914 1.914 0 0 0 1.636 2.871h16.214"
              "a1.914 1.914 0 0 0 1.636 -2.87l-8.106 -13.536a1.914 1.914 0 0 0 -3.274 0z",
              "M12 16h.01"],
    "info": ["M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0 -18", "M12 8h.01", "M11 12h1v4h1"],
    "lock": ["M5 13a2 2 0 0 1 2 -2h10a2 2 0 0 1 2 2v6a2 2 0 0 1 -2 2h-10a2 2 0 0 1 -2 -2z",
             "M11 16a1 1 0 1 0 2 0a1 1 0 0 0 -2 0", "M8 11v-4a4 4 0 1 1 8 0v4"],
    "arrow-right": ["M5 12l14 0", "M15 16l4 -4", "M15 8l4 4"],
    "file": ["M14 3v4a1 1 0 0 0 1 1h4",
             "M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2z"],
    "file-check": ["M14 3v4a1 1 0 0 0 1 1h4",
                   "M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2z",
                   "M9 15l2 2l4 -4"],
}


def icon(name, size=16, colour="currentColor", stroke=1.75, style=""):
    """One Tabler glyph, inline, inheriting colour unless told otherwise."""
    paths = "".join(f'<path d="{d}"/>' for d in _ICONS[name])
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="{colour}" stroke-width="{stroke}" stroke-linecap="round" '
            f'stroke-linejoin="round" style="flex:none;{style}" '
            f'aria-hidden="true">{paths}</svg>')


def logo_data_uri():
    """The Arcwise mark, inlined. Small enough that a request would be wasteful."""
    svg = (ASSETS / "arcwise.svg").read_bytes()
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode()


def configure_page():
    st.set_page_config(
        page_title="Arcwise — Consolidation",
        page_icon=str(ASSETS / "favicon.png"),
        layout="wide",
        initial_sidebar_state="collapsed",
    )


def inject():
    """Fonts, tokens and the chrome removal. Called once per rerun."""
    st.markdown(
        f"""
<style>
:root {{
  --brand-50:{BRAND_50}; --brand-100:{BRAND_100}; --brand-200:{BRAND_200};
  --brand-300:{BRAND_300}; --brand-400:{BRAND_400}; --brand-500:{BRAND_500};
  --brand-600:{BRAND_600}; --brand-700:{BRAND_700}; --brand-900:{BRAND_900};
  --ink-50:{INK_50}; --ink-100:{INK_100}; --ink-200:{INK_200}; --ink-300:{INK_300};
  --ink-400:{INK_400}; --ink-500:{INK_500}; --ink-600:{INK_600}; --ink-700:{INK_700};
  --positive:{POSITIVE}; --negative:{NEGATIVE}; --warning:{WARNING};
  --surface-page:{SURFACE_PAGE}; --surface-card:{SURFACE_CARD};
  --surface-input:{SURFACE_INPUT};
  --shadow-soft:{SHADOW_SOFT}; --shadow-card:{SHADOW_CARD};
  --r-badge:4px; --r-control:6px; --r-inner:8px; --r-card:10px;
}}

/* ---- remove the framework's own furniture -------------------------------- */
#MainMenu, footer, header[data-testid="stHeader"],
[data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"], .stDeployButton,
[data-testid="stAppDeployButton"], [data-testid="stMainMenu"] {{
  display: none !important;
  visibility: hidden !important;
  height: 0 !important;
}}

/* The default top padding leaves a band of empty page above the content, which
   reads as a script with a gap rather than as an application. */
[data-testid="stAppViewBlockContainer"],
[data-testid="stMainBlockContainer"],
.block-container {{
  padding-top: 1.4rem !important;
  padding-bottom: 3rem !important;
  max-width: 1280px;
}}

body {{ line-height: 1.6; }}
::selection {{ background: rgba(46,95,154,.18); color: var(--brand-700); }}

/* The type scale, the weights and Inter itself are set in .streamlit/config.toml, so
   they reach the widgets a stylesheet cannot. What is left here is the one thing the
   config cannot express: headings are dark.7 while body text is dark.6, and Streamlit
   paints both from a single textColor. */
h1, h2, h3, h4, h5, h6 {{
  color: var(--ink-700) !important;
  letter-spacing: normal !important;
  line-height: 1.2 !important;
  padding: 0 !important;
}}
h4, h5, h6 {{ line-height: 1.3 !important; }}

/* ---- header -------------------------------------------------------------- */
.aw-header {{
  display:flex; align-items:center; gap:12px;
  padding: 2px 0 16px 0;
  border-bottom: 1px solid var(--ink-200);
}}
.aw-header img {{ width: 24px; height: 24px; }}
.aw-wordmark {{ font-size: 16px; font-weight: 500; color: var(--brand-600); }}
.aw-product {{
  font-size: 14px; color: var(--ink-500); font-weight: 400;
  padding-left: 12px; border-left: 1px solid var(--ink-300);
}}
.aw-badge-demo {{
  margin-left:auto; font-size:11px; font-weight:500;
  color: var(--brand-500); background: var(--brand-50);
  border: 1px solid var(--brand-100); border-radius: var(--r-badge);
  padding: 3px 8px; white-space: nowrap;
}}

/* ---- progress rail. The product's active-nav treatment: blue.0 on blue.6, --
        6px radius, weight 500. Not a filled dark pill with a badge inside it. -- */
.aw-rail {{ display:flex; gap:2px; margin: 14px 0 22px 0; flex-wrap: wrap; }}
.aw-step {{
  display:flex; align-items:center; gap:7px; height:30px; padding: 0 11px;
  border-radius: var(--r-control);
  font-size:12px; font-weight:400; color: var(--ink-500);
}}
.aw-step .n {{
  display:inline-flex; align-items:center; justify-content:center; width:14px;
  font-size:11px; color: var(--ink-400); font-variant-numeric: tabular-nums;
}}
.aw-step.done .n {{ color: var(--positive); }}
.aw-step.now {{
  background: var(--brand-50); color: var(--brand-600); font-weight:500;
}}
.aw-step.now .n {{ color: var(--brand-400); }}

/* ---- text roles. Six sizes, not sixteen. --------------------------------- */
.aw-lede {{
  font-size:14px; line-height:1.6; color: var(--ink-500);
  max-width: 680px; margin: 2px 0 18px 0;
}}
.aw-note {{ font-size:12px; line-height:1.55; color: var(--ink-500); }}
.aw-micro {{ font-size:11px; line-height:1.5; color: var(--ink-400); }}
.aw-mono {{
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size:12px; color: var(--ink-500);
}}
.aw-quote {{
  font-size:13px; line-height:1.6; color: var(--ink-500);
  border-left: 2px solid var(--ink-200); padding-left: 12px;
}}
.aw-eyebrow {{
  font-size:12px; font-weight:500; color: var(--ink-400); margin: 2px 0 6px 0;
}}
.aw-num {{ font-variant-numeric: tabular-nums; }}

/* ---- cards --------------------------------------------------------------- */
.aw-card {{
  background: var(--surface-card); border:1px solid var(--ink-200);
  border-radius: var(--r-card); padding: 16px 20px; box-shadow: var(--shadow-soft);
  margin-bottom: 14px;
}}
.aw-card-title {{ font-size: 14px; font-weight:500; color: var(--ink-700); margin-bottom: 4px; }}
.aw-card-sub {{ font-size:13px; color: var(--ink-500); line-height:1.6; }}

/* ---- KPI tiles. The default metric widget is the single biggest tell. ----- */
.aw-kpis {{ display:grid; gap:12px; margin: 4px 0 18px 0; }}
.aw-kpi {{
  background: var(--surface-card); border:1px solid var(--ink-200);
  border-radius: var(--r-card); padding:14px 18px; box-shadow: var(--shadow-soft);
}}
.aw-kpi .label {{ font-size:12px; font-weight:400; color: var(--ink-500); margin-bottom:6px; }}
.aw-kpi .value {{
  font-size:28px; font-weight:500; color: var(--ink-700); line-height:1.2;
  font-variant-numeric: tabular-nums;
}}
.aw-kpi .delta {{
  display:flex; align-items:center; gap:5px;
  font-size:12px; font-weight:400; color: var(--ink-500); margin-top:6px; line-height:1.45;
}}
.aw-kpi .delta.up {{ color: var(--positive); }}
.aw-kpi .delta.down {{ color: var(--negative); }}
/* The headline. Flat brand, because the product has no gradients. */
.aw-kpi.hero {{ background: var(--brand-600); border-color: var(--brand-600); }}
.aw-kpi.hero .label {{ color: rgba(255,255,255,.66); }}
.aw-kpi.hero .value {{ color:#fff; font-size:32px; }}
.aw-kpi.hero .delta,
.aw-kpi.hero .delta.up, .aw-kpi.hero .delta.down {{ color: rgba(255,255,255,.80) !important; }}

/* ---- provenance strip ---------------------------------------------------- */
.aw-prov {{
  display:flex; flex-wrap:wrap; gap:0; margin: 2px 0 18px 0;
  background: var(--surface-card); border:1px solid var(--ink-200);
  border-radius: var(--r-card); overflow:hidden; box-shadow: var(--shadow-soft);
}}
.aw-prov > div {{
  flex:1 1 150px; padding:13px 18px; border-right:1px solid var(--ink-200);
}}
.aw-prov > div:last-child {{ border-right:none; }}
.aw-prov .n {{
  font-size:20px; font-weight:500; color: var(--ink-700);
  font-variant-numeric: tabular-nums;
}}
.aw-prov .k {{ font-size:12px; color: var(--ink-500); margin-top:2px; line-height:1.45; }}
.aw-prov .zero .n {{ color: var(--positive); }}

/* ---- findings and the constants the engine applied ----------------------- */
.aw-finding {{
  display:flex; gap:8px; align-items:flex-start;
  font-size:13px; color: var(--ink-600); line-height:1.55; padding: 4px 0;
}}
.aw-finding svg {{ margin-top: 3px; color: var(--positive); }}
.aw-applied {{
  display:flex; gap:10px; align-items:baseline; padding: 3px 0;
  font-size:12px; color: var(--ink-400);
}}
.aw-applied .k {{ color: var(--ink-500); }}
.aw-applied .v {{ color: var(--ink-600); font-variant-numeric: tabular-nums; }}

/* ---- badges. Mantine Badge: radius xs, 11px, weight 500, no uppercase. --- */
.aw-pill {{
  display:inline-block; font-size:11px; font-weight:500;
  border-radius: var(--r-badge); padding:2px 7px; white-space:nowrap;
}}

/* ---- callouts ------------------------------------------------------------ */
.aw-callout {{
  display:flex; gap:9px; align-items:flex-start;
  border-radius: var(--r-inner); padding:11px 14px; margin: 2px 0 16px 0;
  font-size:13px; line-height:1.6; color: var(--ink-600);
}}
.aw-callout svg {{ margin-top: 2px; }}

/* ---- the widgets we do keep --------------------------------------------- */
[data-testid="stFileUploaderDropzone"] {{
  background: var(--surface-card); border:1px dashed var(--ink-300);
  border-radius: var(--r-card); padding: 18px;
}}
[data-testid="stFileUploaderDropzone"]:hover {{ border-color: var(--brand-400); }}
[data-testid="stFileUploaderDropzone"] small {{ color: var(--ink-400); }}

/* Button: height 32, radius 6, 12px, weight 400. Filled is blue.6 -> blue.7. */
.stButton > button, .stDownloadButton > button {{
  min-height: 32px; height: 32px; padding: 0 16px;
  border-radius: var(--r-control); font-size: 12px; font-weight: 400;
  background: var(--surface-card); color: var(--brand-600);
  border: 1px solid var(--ink-300); box-shadow: none; transition: all .15s ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
  background: var(--brand-50); border-color: var(--brand-200); color: var(--brand-600);
}}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{
  background: var(--brand-600); border-color: var(--brand-600); color:#fff;
}}
.stButton > button[kind="primary"]:hover,
.stDownloadButton > button[kind="primary"]:hover {{
  background: var(--brand-700); border-color: var(--brand-700);
}}
.stButton > button:disabled {{
  background: var(--ink-200); border-color: var(--ink-200); color: var(--ink-400);
}}

/* Input: height 36, inputBg, dark.3 border, and the product's focus ring. */
[data-testid="stNumberInputContainer"], .stTextInput div[data-baseweb="input"],
.stSelectbox div[data-baseweb="select"] > div {{
  border-radius: var(--r-control) !important;
  border-color: var(--ink-300) !important;
  background: var(--surface-input) !important;
  min-height: 36px;
}}
[data-testid="stNumberInputContainer"]:focus-within,
.stTextInput div[data-baseweb="input"]:focus-within {{
  border-color: var(--brand-600) !important;
  box-shadow: 0 0 0 3px rgba(13,46,94,.08);
}}
[data-testid="stNumberInput"] input, .stTextInput input {{
  font-size: 14px; color: var(--ink-700); font-variant-numeric: tabular-nums;
}}
[data-testid="stWidgetLabel"] p, .stSlider [data-testid="stWidgetLabel"] p {{
  font-size: 14px !important; font-weight: 500 !important; color: var(--ink-700) !important;
  line-height: 1.4 !important;
}}
[data-testid="stNumberInputStepUp"], [data-testid="stNumberInputStepDown"] {{
  color: var(--ink-500);
}}
.stRadio [data-testid="stWidgetLabel"] p, .stToggle [data-testid="stWidgetLabel"] p {{
  font-weight: 400 !important;
}}
.stRadio label p, .stCheckbox label p {{ font-size: 13px !important; }}

/* Accordion: radius 10, dark.2 border, shadow sm, 44px control, 12px/500 label. */
[data-testid="stExpander"] details {{
  border:1px solid var(--ink-200); border-radius: var(--r-card);
  background: var(--surface-card); box-shadow: var(--shadow-soft);
}}
[data-testid="stExpander"] summary {{
  min-height: 44px; font-size:12px; font-weight:500; color: var(--ink-700);
}}
[data-testid="stExpander"] summary:hover {{ background: var(--ink-50); }}
[data-testid="stExpander"] summary svg {{ color: var(--ink-500); }}

/* Bordered container, used for a decision on the review step. Given the card radius
   and shadow so it belongs to the same family as everything else on the page. */
[class*="st-key-decision-"] {{
  border-radius: var(--r-card) !important;
  box-shadow: var(--shadow-soft);
  background: var(--surface-card);
}}

hr {{ border-color: var(--ink-200); margin: 22px 0; }}
[data-testid="stDataFrame"] {{ border:1px solid var(--ink-200); border-radius: var(--r-inner); }}
[data-testid="stDataFrame"] * {{ font-variant-numeric: tabular-nums; }}
.stProgress > div > div > div > div {{ background: var(--brand-500); }}
[data-testid="stMetricValue"] {{ font-variant-numeric: tabular-nums; }}
.stAlert {{ border-radius: var(--r-inner); font-size: 13px; }}
</style>
        """,
        unsafe_allow_html=True,
    )


def header(product="Consolidation"):
    st.markdown(
        f"""<div class="aw-header">
  <img src="{logo_data_uri()}" alt="Arcwise"/>
  <span class="aw-wordmark">Arcwise</span>
  <span class="aw-product">{product}</span>
  <span class="aw-badge-demo">Illustrative data</span>
</div>""",
        unsafe_allow_html=True,
    )


def pill(text, colour):
    """A Mantine badge: 4px radius, 11px, weight 500, tinted, sentence case."""
    return (f'<span class="aw-pill" style="color:{colour};'
            f'background:{colour}14;border:1px solid {colour}33;">{text}</span>')


def heading(text, level=3, escape=False, margin="0 0 8px 0"):
    """A heading rendered as HTML rather than as markdown.

    Two reasons, and the second is not cosmetic. Streamlit's markdown treats ``$`` as the
    start of LaTeX, so a heading naming two figures -- *"Freight falls $638,266, more than
    the $434,113 the warehouse step adds"* -- rendered the words between them as maths, in
    a serif font, on the headline of the results screen. Sizes also come straight off the
    Mantine ``Title`` scale here instead of depending on which ``#`` count Streamlit was
    given.
    """
    size, lh = {1: (28, 1.2), 2: (24, 1.2), 3: (20, 1.2),
                4: (16, 1.3), 5: (14, 1.3), 6: (12, 1.4)}[level]
    body = _html.escape(text) if escape else text
    return (f'<div style="font-size:{size}px;line-height:{lh};font-weight:500;'
            f'color:{INK_700};margin:{margin};">{body}</div>')
