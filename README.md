# Arcwise Consolidation — client-facing demo

A demo of a product we have not built yet. It shows the real shape of the eventual
Arcwise consolidation product, running a real engine against invented data.

```bash
./run.sh
```

Then walk the six steps: **Data → References → Resolve → Settings → Build → Results**.

---

## What is real and what is not

Being precise about this matters, because the demo is shown to prospects and nobody
on our side should ever overstate it.

| | |
| :-- | :-- |
| **The data is invented.** | None of the three importers exist. Every importer, supplier, lane, rate and delivery-site identifier was made up. The *warehouse operators* are real European 3PLs, used as plausible placeholders — they are not tied to any client and no real 3PL is party to anything here. No client data is anywhere in this repository, and `validate.py`'s sibling check plus the entity scan described below are how that is kept true rather than assumed. |
| **The engine is real.** | It genuinely parses the file, rebuilds container counts, resolves mappings, packs containers by replaying the calendar, derives rates from the invoices and costs the result. Nothing on the results screen is pre-computed. |
| **The answer is not fixed in advance.** | Change an assumption and the numbers move, because the model re-runs. That is the point of building it this way. |
| **The three datasets are not three scripts.** | There is no per-scenario code in the app at all. The References board reads what each file can and cannot price, so a different dataset produces a different board because the *data* differs. |
| **The pacing is presentational.** | The engine finishes in about a second. Each step is held to a ~1.2s floor (`STEP_MIN_SECONDS` in `engine/config.py`) so the build reads at human speed. It changes no number. Say so if anyone asks. |
| **It is badged.** | A persistent *Demo · illustrative data* marker sits in the header. Leave it there. A prospect who mistakes this for shipping software expects it next week. |

## The pitch

> We derive what we can from your own invoices, we tell you plainly when we can't, and
> you can always overrule us with your contracted rate.

Every rate carries one of four provenances, and the results screen counts them:

- `CLIENT_RATE_CARD` — priced by a card the client uploaded
- `DERIVED_FROM_INVOICES` — no card row, so reverse-engineered from their own charge
  lines: what they paid divided by what they moved, published with the formula, the
  population and the observed spread
- `QUOTED_NOT_YET_BOUGHT` — consolidation introduces a step that has never happened, so
  no invoice can evidence it. A forwarder quotes that service, and a quote for work not
  yet bought is evidence of a different kind.
There is no fourth kind. `CLIENT_ASSUMPTION` — our benchmark standing in for a rate they
have not given us — **is not available for the consolidation service**, and that is the
most important rule in the model. The service is the cost consolidating creates: it exists
only on the future side of the comparison, so a figure of ours there does not shade the
answer, it *carries* it. On these datasets, pricing it ourselves put around 60% of the
saving on numbers the client had never seen. Leaving it out instead is worse again — the
saving would grow the less they had told us.

So the consolidation quote is required. With no price of theirs for receiving an inbound
load, handling, drayage, storage, the strip or the free storage period, `engine/run.py`
raises `MissingServiceQuote` and there is no answer at all. The client can upload their forwarder's quote or type the
figures on the settings step; either is theirs. Neither is ours.

Nothing is invented. `engine/reconcile.py` fails the run if that stops being true.

### The number that carries the argument

The control named *"The rate model reproduces what you actually paid"* prices
the containers the client actually moved using the engine's own rate table and compares
it to their invoices. It lands inside **0.3% on all three datasets**. That is what shows
the saving comes from moving fewer containers rather than from quietly cheaper rates —
which is the first thing a sceptical freight person will test.

## The three datasets

Three invented importers, differing along **two** axes on purpose: how much their
forwarder itemises, and how strong the opportunity is. Every dataset contains something
worth acting on, because every demo needs a useful finding; none is uniformly flattering,
because the lane-level rule still has to reject work that does not pay.

| | **Northgate** (UK) | **Calderwood** (DE) | **Meritt** (ES) |
| :-- | :-- | :-- | :-- |
| Origins | Ningbo · Ho Chi Minh City | Qingdao · Chennai | Shenzhen |
| Scale | 5.2k lines, 521 containers | 3.4k lines, 423 containers | 2.0k lines, 263 containers |
| Origin billing | itemised, codes 1631–1637 | **bundled** into code 1630 | **bundled** |
| Destination billing | itemised, code 1638 | itemised | **folded into freight**, code 1300 |
| Board with no cards | 5 derived, 1 analogue, **3 unpriced** | 3 derived, **6 unpriced** | 1 derived, **8 unpriced** |
| How they book | small lots, boxes leave 58% full | larger lots, boxes leave 70% full | **by the container**, boxes leave 90% full |
| Container fill today | 37.2 CBM | 44.9 CBM | **57.8 CBM** |
| **The case** | **strong** | **borderline** | **marginal** |
| Saving, one site per box | $618,338 (15.0%) | $182,268 (5.5%) | **$54,516 (3.5%)** |
| Saving, sites may mix | $812,577 (19.7%) | $260,441 (7.9%) | **$18,302 (1.2%)** |
| Containers | 521 → 422 | 423 → 385 | 263 → 254 |
| Lanes the plan will run | 20 of 24 | **8 of 20** | **3 of 7** |
| Lane verdicts | 20 consolidate, 4 leave | 8 consolidate, **12 leave** | **3 consolidate, 4 leave** |
| Review queue | 3 decisions, 35 auto | 3 decisions, 29 auto | 3 decisions, 20 auto |
| Inbound tender | **adopted**, $47,710 a year | **tested and rejected** by $7,095 | **never supplied**, target shown from its cargo |

A bundled file is *coarse, not broken*: still charge-line grain, still carrying the
`-related-` sentinel and the blank-equipment mess, still reconciling to the cent. The
money is all present; it simply cannot be attributed to a leg. That is the commonest real
reason a rate cannot be derived, and the board names the charge code responsible rather
than reporting a bare absence.

Note the two axes are independent. Meritt has the coarsest billing and the smallest case,
but the weak result is not caused by weak evidence: with the reference pack loaded every
leg is priced and the answer is 100% evidenced. Its disciplined container-sized ordering
simply leaves only three site lanes with enough recoverable air.

### The rules that keep the answer defensible: physical and commercial adoption

**A lane is consolidated only if consolidating it saves a container.** Nothing else could
be worth doing — running cargo through a warehouse buys receiving, handling, drayage and
storage, and the only thing it can sell in return is a box off the bill. So each pool is
packed, checked against what the client books on that lane today, and handed straight back
if it needs as many boxes as they already move or more. Its cargo ships exactly as it
ships now, at its own invoiced cost, and contributes precisely zero to every figure on the
screen. The surviving candidate is then costed at origin–port–destination-site grain and
must save more than **$25,000 a year or 5% of that lane's current cost**. A site lane that
fails either the physical gate or both commercial hurdles is restored to today's boxes
and invoiced cost before the dashboard totals are calculated.

This is the rule the demo is most likely to be attacked on, so it is worth being exact
about what it is and is not:

* The physical gate prevents the candidate adding a box. The commercial gate prevents a
  rejected candidate appearing as though it were part of the plan. *Leave alone* always
  means identical boxes, cost and delivery dates in the final result.
* The verdict is applied at **origin–port–destination-site grain**. When sites may share a
  country-level container, its boxes and cost are allocated back by each site's CBM share,
  so every final delivery leg remains visible and the rows still reconcile to the total.
* It has a **side effect worth knowing**: cargo that ships LCL today books none of the
  client's containers, so a lane that is mostly groupage can rarely clear the gate, and the
  chance to pull that cargo into their own boxes is left on the table. The results screen
  names the LCL volume rather than burying it.

The runtime controls and `validate.py` assert on every dataset and both pool keys that every
site lane appears exactly once, all adopted lanes clear the commercial rule, declined
lanes are unchanged, and the lane rows reconcile to the final boxes and saving.

### What consolidation actually costs, and where the FTL question really lives

Four costs on the origin side are modelled explicitly, because between them they decide
whether any of this is worth doing:

| Cost | Unit | Why it is that unit |
| :-- | :-- | :-- |
| Collection (code 1631) | per **inbound load the cargo needs**, from the shipment's own container count | A truck goes to a factory and takes what is there. Consolidation visits no fewer factories and moves no fewer cubic metres, so it buys no fewer collections. Charging this per *modelled container* — which is how every other origin component correctly works — had the plan paying collection on 420 boxes where the client pays it on 521 loads: about $100k a year of saving that came from nothing but the denominator. |
| Warehouse receiving | per **inbound delivery**, $130–165 | Every load that arrives has to be unloaded, checked against its packing list and put away. It is the cost of how *often* cargo turns up, not how much of it there is — which is exactly why buying the inbound leg as fewer, fuller loads is worth something. |
| Warehouse handling | per container built | The step consolidation is made of. |
| Warehouse to quay | per container built | One sealed box, one truck. There is nothing to tender and no bin-packing to do, which is why the trailer question does **not** sit here. |

The trailer question sits on the **inbound** leg, where the unit is a pallet and the count
is therefore ours to change. Today every load on the road carries one supplier's cargo,
because it is going to a port CFS to be stuffed into that supplier's own container. Under
the plan the destination is a warehouse that is going to mix the cargo anyway, so one
trailer can sweep up three suppliers in a region on the same day. The engine bin-packs both
states off the client's own cargo-ready dates — `pack.plan_inbound_trucks`, run once with
each shipment on its own and once pooling a region's same-day cargo — against a trailer
capped three ways at 66 pallets, 76 CBM and 24 t.

Two costs then move together, and the second is the one clients underestimate: the haul is
bought per trailer instead of per container collected, and the warehouse receives fewer
deliveries so it charges for fewer. Both halves are reported as their own line whichever
way the verdict goes, and the results panel names which one decided it *on that file*
rather than asserting a generalisation.

Nothing waits at a factory for a trailer to fill. That is deliberate and it is what lets
the panel say the container plan is identical either way: no pallet reaches the warehouse a
day later than it does now, so nothing about which box it joins can move. It also caps how
much pooling can ever be worth, which is the honest trade — a fuller trailer is available
for the price of a delay nobody has agreed to.

### What decides whether consolidating is worth it

Only one thing, and it is not the rates: **how full their containers leave today.** The
plan can fill a box to somewhere between 46 and 61 CBM depending on the settings. A client
already shipping at 37 CBM has 27 CBM of air per box to recover and the case is
overwhelming; a client at 60 CBM has none, and every warehouse charge is a new cost with
nothing to pay for it.

That is set per world in `generator/worlds/*.py`, in the `BOOKING` block:

| Knob | What it means | Northgate | Calderwood | Meritt |
| :-- | :-- | :-- | :-- | :-- |
| `pallets` | lognormal (mu, sigma) for consignment size | (3.55, 0.60) → median 35 | (3.78, 0.40) → median 44 | — |
| `lot_fill` | orders raised to fill a box: the fill they arrive at | — | — | (0.90, 0.99) |
| `efficiency` | how full a box leaves when booked one shipment at a time | (0.60, 0.86) | (0.80, 0.97) | **(0.96, 1.00)** |
| `lcl_share` | share of groups riding groupage, booking no box | 0.14 | 0.14 | 0.04 |

Meritt's `efficiency` is the most sensitive number in the three worlds. `(0.96, 1.00)` is
deliberately disciplined but not perfect: the gate finds three worthwhile lanes, rejects
four, removes nine containers and produces a 3.5% saving. The commercial threshold is
unchanged; the opportunity comes from realistic fragmentation in the generated bookings.

One further generator detail earns its place here, because without it the inbound tender is
untestable: **cargo-ready dates snap to a weekly ex-works day per pickup region**
(`world.exw_ready_weekday`). Factories work to a weekly schedule and a collection round
follows it. Drawing ready dates uniformly across the year — the obvious thing to do —
means no two suppliers in a region are ever ready on the same day, no trailer can pool
anything, and the model concludes that tendering the inbound leg is worthless for a reason
that is an artefact of the generator rather than a property of freight.

Two settings on the Settings step are worth showing, because they are where a borderline
file tips either way:

| Setting | Northgate | Calderwood | Meritt |
| :-- | :-- | :-- | :-- |
| Default: 14-day dwell, 80% target, one site per box | +15.0% | **+5.5%** | **+3.5%** |
| Sites may mix, countries never | +19.7% | **+7.9%** | **+1.2%** |
| 3-day dwell, 60% target, one site per box | +8.5% | **+2.2%** | +3.5% |
| 21-day dwell, sites may mix | +22.2% | +9.5% | +1.2% |

So the rehearsal script writes itself:

* **Northgate** — open here. It works under every setting, which is the point: *"we have
  not tuned this to a flattering set of assumptions; here is the worst case and it is
  still +8.5%."* Add the trailer tender and the saving grows $47,710, with the arithmetic
  and both load counts on screen.
* **Calderwood** — the interesting one. At the defaults it is 6.0%, which is arguable. Turn
  on *sites may mix* and it goes to 9.4%; tighten the dwell to three days and it falls to
  2.8%. **The service promise, not the freight, decides whether this client should do it.**
  Nothing about the rates changed between those three numbers. Then drop in their trailer
  tender and watch the engine reject it: $7,095 a year dearer than their own collections,
  so the model keeps the collections and the saving does not move by a cent.
* **Meritt** — the marginal play. Every leg is priced and every control passes, but only
  **three of seven destination-site lanes** clear the commercial rule. The plan removes
  nine containers and saves 3.5%; the four rejected lanes stay exactly as they are today.
  Letting sites mix weakens the result to one worthwhile lane, which makes it a useful
  example of a plausible operating choice making the answer worse rather than better.

### Deconsolidation, and why it does not flip the pooling decision

A destination strip is four jobs, not one: the box is drayed to a bond store instead of
straight to the door, devanned and re-palletised, held and re-loaded, then delivered a
second time. Priced accordingly on each quote — $780 Northgate, $860 Calderwood, $910
Meritt — which is roughly double what an earlier version of this demo assumed.

It is a real cost and it still does not change the pooling answer on a file with any air
in it, because the two sides of that trade are an order of magnitude apart. Letting sites
share a container on Northgate removes 44 boxes worth $284,204 of freight and delivery and
buys $82,680 of strip across 106 extra sites. Mixing wins by $201,524. For the strip to
make mixing the wrong call it would have to be about **$2,680 per extra site**, which no
forwarder will quote and nobody should believe.

On Meritt most mixed-site candidates do not clear the commercial rule, so their warehouse
and strip cost never enters the final plan. One lane still clears it, preserving a small
useful finding while rejected candidate economics remain outside the dashboard total.

## References: one screen, one job

Step 2 takes files. That is all it does. It answers the only question somebody has when
they get there — *what do you want from me?* — with a short list they can read in one go:

```
Step 2 of 6

What we can use from you

→ 1 of 9 costs priced, 8 still need a file.

  ▢ Door charges           Needed     Still unpriced: discharge port to
                                      warehouse, supplier to warehouse
  ▢ Port and ocean         Needed     Still unpriced: ocean freight, origin
                                      terminal and export documents
  ▢ Consolidation quote    Needed     Still unpriced: receiving cargo at the
                                      warehouse, building the container,
                                      storage while it fills
  ▢ Trailer tender         Optional

  Drop them in together or one at a time — we identify each file from its
  columns.
  [                    Upload                        ]
  [ Load the samples ]

  Back    Continue
```

One uploader, not one per file: the files carry a `Category` column, so the engine
identifies what it has been handed and names it back — *"Read your Freight rate card and
Origin rate schedule — 43 rates in all."* Three separate dropzones answered the wrong
question and buried the list.

The status of each row is computed, never scripted. **Needed** means a cost the engine
will otherwise refuse to price, and refuse is literal — there is no benchmark of ours
behind any of it. **Optional** is left for files that improve the process rather than the
answer, which today is only the trailer tender. The counting line moves as files
arrive, which is the one piece of the sourcing story that belongs *before* the build.

Everything else that used to live on this screen — the nine components, which charge
code was bundled, what a trailer rate would have to beat — now appears **after** the model
runs, under *"what we found in your rates"* on Results. It is output to react to, not
configuration to study, and putting it first made the step read like something you had to
understand before you were allowed to continue.

Under the hood there are nine cost components, and every state is computed from the data:

| State | Meaning |
| :-- | :-- |
| `card` | a contracted rate prices it. Beats a derivation: it is what they will be billed. |
| `derived` | rebuilt from their own charge lines, with the arithmetic shown |
| `analogue` | the right kind of charge on the **wrong leg** — code 1602 prices the supplier-to-port run, not warehouse-to-port. Usable, caveated, never `HIGH` confidence. |
| `thin` | a population exists but is under `MIN_DERIVE_GROUPS`. Reported, not used. |
| `quoted` | the consolidation service, priced by their forwarder's quote or typed by them. There is no benchmark of ours behind it: unpriced is the only other state it has. |
| `unpriced` | nothing available. The engine refuses to cost the leg and asks. |
| `opportunity` | an alternative they have given us no rate for — see below |

### The trailer opportunity

The one state that is not about the past. Consolidating turns a hundred and ninety
one-supplier collections into a hundred and eighty trailer loads that could be tendered by
region, and almost nobody has a contracted rate for work they have never bought. So the
engine bin-packs the trailers off the client's own dates, states what a rate would have to
beat **per load**, asks for one, and tests it when it arrives — against both halves of what
it would replace, the haul and the warehouse receiving.

It has to be able to say no, and on Calderwood it does: their tender is $7,095 a year
dearer than their own collections, so the model keeps the collections and says so on
screen. The saving does not move by a cent, nothing is charged on the rejected rate, and
`validate.py` asserts both. A demo that only ever confirms the client's hopes is selling;
one that occasionally tells them no is advising.

A partial tender is a real possibility, since a trailer rate is priced by region: covering
three regions of five prices three regions of five, and comparing that against the whole
inbound bill would credit it with the two it does not touch. The engine reports it as
partial and keeps the collections.

The container plan is identical either way, because nothing waits at a factory for a
trailer to fill — and the panel says so, so nobody thinks the plan was tuned to the
answer.

## The three-layer model

The flow exists because a real engagement has three kinds of input, not one.

1. **Transactional** — the charge-line export. Uploaded.
2. **Reference** — rate cards, quotes, the site list. Any subset, in any order; each one
   improves whichever board cards it covers. All optional.
3. **Resolution** — the joins that need judgement. These do *not* exist as a file the
   client can send: they do not exist until someone decides. The engine auto-resolves
   what it can defend and escalates the rest with a proposal, the evidence and the
   volume riding on the answer.

Every dataset escalates exactly **three** decisions, one of each kind, because three is
what a room will sit through and each one has to be a different argument:

1. **The address is a placeholder** — `City`, `N/A`, `TBC`. Nowhere to deliver to.
2. **One operator appears at two towns** — Rhenus at Tilburg and Duisburg, Turia at
   Ribarroja and Alicante. One warehouse or two? Only the client knows.
3. **A supplier is recorded at an office in another country** — a Manchester or Singapore
   address on cargo that leaves Ningbo or Shenzhen, so no pickup region can be priced.

`resolve.py` carries two further rules — a region rather than a town, and a material site
missing from a supplied list — because a prospect's own file will trip them. They are
simply not baked into our three datasets any more: the same decision watched three times
is a worse demo than three different ones.

The resolved mappings download as two CSVs. Hand them back on the next run and the
review step is empty — first run is work, every run after it is free. `validate.py`
round-trips this, so the claim is tested rather than asserted.

## Design

The interface uses the same Arcwise design language throughout. Shared values live in
`.streamlit/config.toml` and `app/theme.py` so native Streamlit components and custom
components remain visually consistent.

| | The product, and therefore this |
| :-- | :-- |
| Type | Inter. Body 14/1.6, captions 12, micro 11. Headings on the `Title` scale — 28 / 24 / 20 / 16 / 14 / 12 |
| Weight | 400 everywhere; 500 for headings, field labels and the active nav item; 600 only for a link |
| Radius | 4 badge, 6 button and input, 8 inner, 10 card |
| Colour | Body text `dark.6`, muted `dark.5`, headings `dark.7`. Accents are load-bearing only |
| Icons | Tabler, inlined as paths and stroked in `currentColor` — the set the product imports 300-odd times |

And four things the product never does, all of which were in here: UPPERCASE micro-labels,
negative letter-spacing, gradients, and an HTML entity or an emoji standing in for an icon.
Those are the tells that make a screen read as a dashboard applied to a prototype. A block
in the UI harness asserts all four stay gone, along with faux font weights (560, 620, 680)
and the type scale collapsing back out to sixteen sizes.

Almost everything above is set in `.streamlit/config.toml` rather than in injected CSS,
because Streamlit derives colours it never exposes to a stylesheet — the tint behind a
bordered container, a widget's focus ring — from those values, and because the dataframe
draws its text to a canvas that no CSS reaches. Without `font` and `fontFaces` set in the
config, every table renders in the system sans while the page around it is in Inter.
`app/theme.py` is then only what the config cannot express.

One consequence worth knowing about: a heading with money in it must go through
`UI.h()`, not `st.markdown("#### …")`. Streamlit reads a pair of `$` as LaTeX, so
*"Freight falls $638,266 — more than the $432,083 the warehouse step adds"* set its own
figures as serif maths on the headline of the results screen.

## Words

Every word on screen has to do a job, which mostly means saying what the run found. The
recurring failures, all of which have been through here:

- **Reassurance.** "Every check that must pass before a number leaves this screen", under a
  green tick that had already said it.
- **The same fact twice.** A tile counting declined lanes above a callout counting them
  again in the same words. The tile counts; the callout states the rule.
- **A word the interface already carries.** "Applying" in front of forty label-and-figure
  pairs on the build ticker. A trend arrow beside the word "fewer" — which was also
  pointing the wrong way, because fewer containers is an improvement that goes down.
- **Repetition down a list.** "No delivery rate from Valencia, Spain" on ten of thirteen
  options in one review decision. The options say "no rate"; the port is named once
  underneath.
- **Naming the step twice.** The eyebrow said "Step 3 of 6 — review" above a heading that
  was already the review.

## Layout

```
data/<scenario>/    charge lines, reference files, site list, ground-truth manifest
data/scenarios.json the registry the app reads
generator/          world.py holds what the worlds share; worlds/ holds the three;
                    make_demo_data.py writes every file
engine/             the model — see below
app/                the Streamlit interface
assets/             Arcwise brand marks
```

Each scenario directory carries `reference_pack.csv` — every rate the client already has,
in one file, which is the one-click demo path — plus the same rows split the way a
forwarder quotes (`door_charges.csv` for the road legs at each end, `port_and_ocean.csv`
for the freight and everything charged at a quay, `consolidation_quote.csv` for the
warehouse work) so the board can be shown half-answered, and `ftl_rate_card.csv` where
that world has one.

There is no `site_list.csv` any more, in the data or on the References step. Every
warehouse a client delivers to is already named, hundreds of times, in the file they have
just handed over, so `resolve.sites_from_data` reads them out of the delivery addresses
instead. A client who *has* a list can still supply one and it is laid over the top — their
naming and their country win for the sites it covers, and the sites it misses are still
known. `validate.py` builds a deliberately bad two-row list and checks that supplying it
never lengthens the review, which is the property that matters: giving us something must
never be worse than giving us nothing.

### Engine

| File | Job |
| :-- | :-- |
| `config.py` | every constant with its label and who is accountable; the charge register; the sourcing plan |
| `ingest.py` | messy charge lines → clean shipment groups, plus a finding per rule applied |
| `resolve.py` | auto-resolve and escalate the judgement calls |
| `sourcing.py` | how each cost component can be priced, and why not where it cannot |
| `rates.py` | card → derived → quote, with the audit trail for each |
| `pallets.py` | groups → pallets, at each group's own volume and weight |
| `pack.py` | build containers by replaying the calendar day by day; decline any lane that cannot save one; bin-pack the inbound trailers |
| `costing.py` | seven cost pools, one ledger row per charge; choose how the inbound leg is bought |
| `leadtime.py` | paired per-shipment delivery deltas, on vessels that actually sailed |
| `reconcile.py` | the controls that gate the whole thing |
| `explain.py` | plain-language explanations rendered from the actual result |
| `workbook.py` | the seven-tab deliverable, named in `workbook.SHEETS` so the app cannot promise tabs it does not write |
| `run.py` | orchestrator; yields progress events for the build ticker |
| `validate.py` | proves all three demos are rehearsable |

The engine includes a master-bill equipment rebuild, pallet explosion, arrival-order
first-fit packer, event-driven dispatch simulation and auditable rate derivation. The
demo implementation is self-contained and operates only on the invented datasets in
this repository.

## The mess in the datasets

Each charge-line file is deliberately messy in three specific ways, and each one stands
between a raw invoice and a defensible rate:

1. **The invoice total is repeated.** One column states it on the first line of an
   invoice and writes `-related-` on the rest. Summing it reports several times the
   actual spend.
2. **Equipment is blank on ~70–80% of rows.** Container counts have to be rebuilt as the
   maximum per master bill, summed to the group. That count is both the baseline the
   saving is measured against and the denominator of every derived per-container rate.
3. **One code arrives under several descriptions.** Code 1638 — the destination
   delivery charge a rate gets derived from — appears under four.

Mixed date formats, three billing currencies, out-of-scope transport modes and a long
tail of unusual but registered charge codes are also present. A genuinely unknown code
is retained for reconciliation but now fails the classification control, so no usable
answer can depend on a cost the engine cannot place. Duplicate and credit lines are
deliberately *not* generated: they cost demo time and move no number.

The mess is realistic, never adversarial. There are no traps designed to look
impressive.

### Demo-data boundary

All companies, suppliers, sites, identifiers, shipment records and commercial figures
in this repository are invented for demonstration. The demo is self-contained and does
not read from a client project or production data source.

### Regenerating

```bash
python3 generator/make_demo_data.py
python3 engine/validate.py
```

Each world is seeded independently and reads no clock, so repeated runs are
byte-identical. That is what makes the demo rehearsable — you know the numbers before
you walk in. If you change a generator, re-run `validate.py`: it will tell you what
moved.

## Running the demo on a call

1. `./run.sh`, full-screen the browser.
2. Drag a `data/<scenario>/charge_lines_raw.csv` onto step 1. **Northgate** for the case
   that works, **Calderwood** if the room wants to argue about whether it is worth it, and
   **Meritt** when you want the marginal case — coarse billing, a small saving, and four of
   seven lanes rejected. See *The three datasets* for what each one produces. Step 1 takes a file and
   nothing else;
   a prospect should watch their own export go in, not pick from a menu of three demos.
   The app recognises a sample file by its contents, which is the only reason step 2 can
   still offer that dataset's own reference files as a shortcut.
3. On References, read the counting line before uploading anything. That is the beat:
   *"six of your nine costs we can already price from your own invoices. The other three we
   will not guess at, and the row below says which file fixes them."* Four rows, and only
   the ones a leg is actually waiting on say NEEDED.
4. **Load the sample files** — or drag `door_charges.csv`, `port_and_ocean.csv` and
   `consolidation_quote.csv` in one at a time, in any order, to make the point that the
   engine identifies each file from its columns rather than from which box it went in.
   Watch the rows go green and the line change to *"All 9 costs priced."* **Clear** puts
   the step back to cold if you want to run the beat twice.
5. **Add the trailer tender** too. On Northgate the engine adopts it and the saving grows
   $47,710; on Calderwood it tests it and keeps their own collections, $7,095 dearer. Both
   outcomes get the *getting cargo to the warehouse* panel on Results, with both load counts
   and the two costs that moved — show whichever makes the point you need.
6. Walk the review decisions. This is the part no CSV importer does. Mention the mapping
   download: next run, this step is empty.
7. Build. Let the ticker run; it narrates what it found, including how many legs it could
   price and which charge codes arrived bundled.
8. On the results screen, lead with the provenance strip and the *"Why this saving is
   real"* card, not the headline dollar figure. Then the waterfall — origin cost going
   *up* is what makes the rest believable. Then the line under the tiles saying how many
   lanes the plan **will not run**, because it is the easiest thing in the demo to defend:
   a plan that cannot add a container to a lane is a different kind of claim from one that
   nets a gain across lanes it made worse. Then the lane verdicts: some lanes are not worth
   doing, and saying so is worth more than a uniformly positive answer.
9. If they push on an assumption, change it and rebuild. That is the whole reason the
   engine is real, and on Calderwood it is the demo: *sites may mix* takes it from 5.5% to
   7.9%, a three-day dwell takes it to 2.2%, and no rate changed in between. Both dials
   are folded away under **Operating choices** — the container limits are what the room
   argues about, so they are the only thing open when the step loads. The consolidation
   figures are **locked**, because
   they came off their own quote and a quoted rate is a fact rather than a setting; one
   switch — *"Let me enter or change these figures"* — opens all of them, and anything
   typed is recorded as theirs and outranks the quote, with the screen saying which.

   The move worth rehearsing: go back to step 2 before uploading the consolidation quote,
   and press on to Settings. Every service figure reads **"no price from you"**, and there
   is no build button. *"We could put our own number in here. We won't — this is the cost
   consolidating creates, so our figure would be carrying your saving."* That refusal sells
   the rest of the model better than any number on the results screen does.

## Not in this version

Post-build sliders that re-run on the results screen (the engine supports it; the UI
does not yet), any chat, connector tiles, hosting or auth, and an in-app spreadsheet
grid — the `.xlsx` download is the worksheet, and reinventing Excel is not the job.

Extending the charge register for a new client's source system is also out of scope for
this demo. Unknown codes are surfaced by the controls rather than silently classified.
