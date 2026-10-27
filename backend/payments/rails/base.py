"""The common interface every money rail implements, real or simulated.

Only the policy engine (via the rail router) may call `pay`; nothing else moves money.
"""

from dataclasses import dataclass, field
from decimal import Decimal


class RailStatus:
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RailError(Exception):
    pass


@dataclass(frozen=True)
class Payee:
    name: str
    # Rail-specific address: PayPal email, mobile money wallet number, biller account number.
    identifier: str


@dataclass
class RailResult:
    rail: str
    reference: str  # our idempotency reference, echoed back
    external_id: str  # the rail's own id, used with status()
    status: str
    simulated: bool
    raw: dict = field(default_factory=dict)


class Rail:
    name = ""
    simulated = False

    def pay(self, payee: Payee, amount: Decimal, reference: str, currency: str = "USD") -> RailResult:
        raise NotImplementedError

    def status(self, external_id: str) -> RailResult:
        raise NotImplementedError


def validate_amount(amount) -> Decimal:
    amount = Decimal(amount)
    if amount <= 0:
        raise RailError("Amount must be positive")
    if amount != amount.quantize(Decimal("0.01")):
        raise RailError("Amount must have at most two decimal places")
    return amount
