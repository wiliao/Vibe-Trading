"""FX conversion for portfolio valuation.

Rates are expressed as currency units per USD. Currency identity and rate
availability are deliberately separate: a valid ISO currency may still be
unrateable by the current production FX feed, in which case valuation fails
closed with the missing currency named.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from src.portfolio.compatibility import PortfolioContractError

Rates = Mapping[str, Decimal]

DISPLAY_RATE_CURRENCIES = frozenset({"USD", "CAD"})


def _validated_rate(pair: str, value: Decimal) -> Decimal:
    """Return a finite positive FX rate or fail closed naming its pair."""
    rate = Decimal(value)
    if not rate.is_finite() or rate <= 0:
        raise PortfolioContractError(f"invalid FX rate for {pair}: {value}")
    return rate


def build_rates(usd_cad: Decimal) -> dict[str, Decimal]:
    """Build the production rates map, anchored on one USD.

    The production feed rates one currency, Canadian dollars; both surviving
    valuation currencies (US USD, Canada CAD) therefore have a rate. Any other
    ISO-4217 currency a connector reports is still valid metadata but has no
    rate, so :func:`to_usd` fails that source closed instead of guessing.
    """
    return {
        "USD": Decimal("1"),
        "CAD": _validated_rate("USD/CAD", usd_cad),
    }


def to_usd(value: Decimal, currency: str, rates: Rates) -> Decimal:
    """Convert value into USD, failing closed when a rate is unavailable."""
    code = str(currency or "").upper()
    rate = rates.get(code)
    if rate is None:
        raise PortfolioContractError(
            f"portfolio FX conversion is not available for: {code}"
        )
    rate = _validated_rate(f"USD/{code}", rate)
    return value / rate


def from_usd(value_usd: Decimal, currency: str, rates: Rates) -> Decimal:
    """Convert a USD value into currency, failing closed on a rate gap."""
    code = str(currency or "").upper()
    rate = rates.get(code)
    if rate is None:
        raise PortfolioContractError(
            f"portfolio FX conversion is not available for: {code}"
        )
    rate = _validated_rate(f"USD/{code}", rate)
    return value_usd * rate


@dataclass(frozen=True)
class FxQuote:
    """One coherent reference-rate observation and its separate retrieval time."""

    rates: Rates
    fetched_at: str
    as_of: str | None = None
    source: str = "injected"

    def validated(self) -> FxQuote:
        """Reject a malformed USD base or a non-finite/non-positive rate."""
        rates = {code: _validated_rate(f"USD/{code}", value) for code, value in self.rates.items()}
        if rates.get("USD") != 1 or not {"CNY", "HKD"} <= rates.keys():
            raise PortfolioContractError("FX quote requires USD=1 and CNY/HKD rates")
        return FxQuote(rates, self.fetched_at, self.as_of, self.source)

    def to_dict(self) -> dict:
        """Serialize rates without losing decimal precision."""
        return {"rates": {k: str(v) for k, v in self.rates.items()},
                "fetched_at": self.fetched_at, "as_of": self.as_of, "source": self.source}
