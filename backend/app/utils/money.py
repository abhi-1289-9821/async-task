"""
utils/money.py
==============
Monetary formatting helpers for human-readable narratives and prompts.
Deterministic engine math always stays in integer cents (and Decimal).
"""

from typing import Optional


CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
}


def get_currency_symbol(currency: str = "USD") -> str:
    """Returns the symbol for the currency code ('$', '€', '£')."""
    return CURRENCY_SYMBOLS.get((currency or "USD").upper(), "$")


def format_money(cents: Optional[int], currency: str = "USD") -> str:
    """
    Formats integer cents into human-readable currency representation (e.g. €1,250.00).
    """
    if cents is None:
        return "N/A"
    curr = (currency or "USD").upper()
    sym = CURRENCY_SYMBOLS.get(curr, f"{curr} ")
    is_neg = cents < 0
    abs_cents = abs(cents)
    dollars = abs_cents // 100
    remainder = abs_cents % 100
    formatted_dollars = f"{dollars:,}.{remainder:02d}"
    if is_neg:
        return f"-{sym}{formatted_dollars}"
    return f"{sym}{formatted_dollars}"
