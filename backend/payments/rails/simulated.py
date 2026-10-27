"""SIMULATED rails: same interface and pending -> succeeded flow as a real integration.

No public sandbox exists for paying into local mobile money wallets or local billers, so these
stand in for future partner integrations. Every result carries simulated=True so the UI can show
the "simulated rail" tag.

The external id encodes the creation time, so status() is stateless and works across workers.
"""

import time
import uuid
from decimal import Decimal

from .base import Payee, Rail, RailError, RailResult, RailStatus, validate_amount


class SimulatedRail(Rail):
    simulated = True
    prefix = "SIM"
    # Seconds a payment stays "pending" before it settles, like a real rail.
    settle_seconds = 5

    def __init__(self, clock=time.time):
        self.clock = clock

    def pay(self, payee: Payee, amount: Decimal, reference: str, currency: str = "USD") -> RailResult:
        amount = validate_amount(amount)
        if not payee.identifier:
            raise RailError(f"{self.name}: payee identifier is required")
        external_id = f"{self.prefix}-{int(self.clock())}-{uuid.uuid4().hex[:10]}"
        return RailResult(
            rail=self.name,
            reference=reference,
            external_id=external_id,
            status=RailStatus.PENDING,
            simulated=True,
            raw={"payee": payee.name, "account": payee.identifier, "amount": str(amount), "currency": currency},
        )

    def status(self, external_id: str) -> RailResult:
        try:
            prefix, created, _ = external_id.split("-", 2)
            created = int(created)
        except ValueError:
            raise RailError(f"{self.name}: unknown reference {external_id}")
        if prefix != self.prefix:
            raise RailError(f"{self.name}: unknown reference {external_id}")
        settled = self.clock() - created >= self.settle_seconds
        return RailResult(
            rail=self.name,
            reference="",
            external_id=external_id,
            status=RailStatus.SUCCEEDED if settled else RailStatus.PENDING,
            simulated=True,
        )


class SimulatedBillerRail(SimulatedRail):
    """Airtime top-ups, local medical aid premiums, funeral cover premiums."""

    name = "biller"
    prefix = "SIMBILL"


class SimulatedMobileMoneyRail(SimulatedRail):
    """Capped cash allowance into a family member's local mobile money wallet."""

    name = "mobile_money"
    prefix = "SIMMOMO"
