"""Rail router: look up a payout rail by name. Mandate config names rails; core logic never branches on them."""

from .base import Payee, Rail, RailError, RailResult, RailStatus
from .paypal import PayPalPayoutRail
from .simulated import SimulatedBillerRail, SimulatedMobileMoneyRail

_RAILS = {rail.name: rail for rail in (PayPalPayoutRail(), SimulatedBillerRail(), SimulatedMobileMoneyRail())}


def get_rail(name: str) -> Rail:
    try:
        return _RAILS[name]
    except KeyError:
        raise RailError(f"Unknown rail: {name}")


# Payee.rail -> rail name. LOCAL_MOBILE_MONEY uses the simulated rail until the Phase 4
# LocalMobileMoneyRail (real PayPal Payout to the provider + simulated last mile) replaces it.
_PAYEE_RAILS = {
    "PAYPAL_PAYOUT": "paypal_payouts",
    "LOCAL_MOBILE_MONEY": "mobile_money",
    "BILLER_SIM": "biller",
}


def for_payee(payee) -> Rail:
    try:
        return get_rail(_PAYEE_RAILS[payee.rail])
    except KeyError:
        raise RailError(f"No rail for payee rail {payee.rail}")


def available_rails():
    return {name: {"simulated": rail.simulated} for name, rail in _RAILS.items()}


__all__ = ["Payee", "Rail", "RailError", "RailResult", "RailStatus", "get_rail", "for_payee", "available_rails"]
