"""The scenario registry.

One entry per invented client. Order is presentation order: the app lists them in this
sequence, and the sequence is a deliberate argument -- best case first, then the case
most prospects are actually in, then the hard one.

Everything a caller needs comes off the world module itself, so adding a fourth
scenario means writing a world and appending it here.
"""

from worlds import calderwood, meritt, northgate
import world as W

WORLDS = [northgate, calderwood, meritt]

for _w in WORLDS:
    W.check(_w)

BY_ID = {w.SCENARIO_ID: w for w in WORLDS}
DEFAULT_ID = WORLDS[0].SCENARIO_ID


def get(scenario_id):
    try:
        return BY_ID[scenario_id]
    except KeyError:
        raise KeyError(
            f"unknown scenario {scenario_id!r}; expected one of {sorted(BY_ID)}") from None


def registry_entry(world, **extra):
    """The row the app reads out of ``data/scenarios.json``.

    Deliberately descriptive rather than prescriptive: it says what the file *is*, and
    the References board works out what that means for pricing. Nothing here tells the
    interface which cards to expect or which legs will be red -- if it did, the board
    would be a script rather than a reading of the data.
    """
    return {
        "id": world.SCENARIO_ID,
        "name": world.CLIENT_COMPANY,
        "short": world.CLIENT_SHORT,
        "summary": world.SUMMARY,
        "origins": sorted(world.ORIGINS),
        "ports": sorted(world.PORTS),
        "sites": len(world.DELIVERY_SITES),
        "suppliers": len(world.SUPPLIERS),
        "billing": dict(world.BILLING),
        "has_ftl_quote": bool(world.FTL_QUOTE),
        **extra,
    }
