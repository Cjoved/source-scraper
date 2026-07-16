"""Map short farmer/agent crop labels to OpenSTAT PSA commodity names.

Qdrant price filters use exact KEYWORD match on ``commodity``. PSA labels are
long (e.g. ``Palay [Paddy] Fancy...``), while the agent historically passed
``Palay`` / ``Corn`` — which matched zero rows.
"""

from __future__ import annotations

# Exact ``Commodity`` values from openstat_table.csv (Cereals group).
_PALAY_COMMODITIES: tuple[str, ...] = (
    "Palay [Paddy] Fancy, dry (conv. to 14% mc)",
    "Palay [Paddy] Other Variety, dry (conv. to 14% mc)",
)

_MILLED_RICE_COMMODITIES: tuple[str, ...] = (
    "RICE, WELL-MILLED, 1 KG",
    "RICE, REGULAR-MILLED, 1 KG",
    "RICE, SPECIAL, 1 KG",
)

_CORN_COMMODITIES: tuple[str, ...] = (
    "Corngrain [Maize] White, matured",
    "Corngrain [Maize] Yellow, matured",
    "Green Corn (Maize, green), White",
    "Green Corn (Maize, green), Yellow",
    "CORN GRITS, CORN NATIVE, 1 KG",
    "CORN GRITS, LOOSE, 1 KG",
    "CORN GRITS, WHITE, #10, 1 KG",
    "CORN GRITS, WHITE, #12, 1 KG",
    "CORN GRITS, WHITE, 1 KG",
    "CORN GRITS, YELLOW, 1 KG",
    "WHOLE CORN GRAIN, YELLOW, 1 KG",
    "WHOLE CORN ON THE COB, NATIVE, 1 KG",
    "WHOLE CORN ON THE COB, SWEET CORN, 1 KG",
    "WHOLE CORN ON THE COB, WHITE, 1 KG",
    "WHOLE CORN ON THE COB, YELLOW, 1 KG",
)

# Lowercase alias → one or more exact PSA commodity strings.
_COMMODITY_ALIASES: dict[str, tuple[str, ...]] = {
    "palay": _PALAY_COMMODITIES,
    "paddy": _PALAY_COMMODITIES,
    "rice": _PALAY_COMMODITIES + _MILLED_RICE_COMMODITIES,
    "bigas": _MILLED_RICE_COMMODITIES,
    "corn": _CORN_COMMODITIES,
    "mais": _CORN_COMMODITIES,
    "maize": _CORN_COMMODITIES,
}


def resolve_commodity_match_values(commodity: str) -> list[str]:
    """Return exact commodity strings to match in Qdrant.

    Short aliases expand to the known PSA labels. Anything else is treated as
    an exact commodity name (API callers can pass the full PSA string).
    """
    raw = commodity.strip()
    if not raw:
        return []
    expanded = _COMMODITY_ALIASES.get(raw.lower())
    if expanded:
        return list(expanded)
    return [raw]
