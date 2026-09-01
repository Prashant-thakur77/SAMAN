"""Row-level visibility policy — spec §0.9b.

A CPSE steward sees their own rows plus the shared golden layer. Raw per-CPSE
prices belonging to *other* CPSEs are for the registrar and auditor only;
a steward sees an anonymised aggregate instead — "market range ₹X–₹Y, n=4
CPSEs" — which is enough to act on without exposing a competitor's contract.

This is enforced in one place so that the dashboards and the Copilot cannot
diverge. §0.9b is explicit that the Copilot must not become a bypass for
row-level security, and the only way to be sure of that is for both to ask the
same function.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Roles allowed to see another CPSE's prices and valuations attributed.
UNRESTRICTED_ROLES = ("registrar", "auditor", "admin")


@dataclass(frozen=True)
class Scope:
    """What the current viewer may see."""

    role: str
    cpse_code: str | None

    @property
    def sees_all_prices(self) -> bool:
        return self.role in UNRESTRICTED_ROLES

    def owns(self, cpse_code: str | None) -> bool:
        return cpse_code is not None and cpse_code == self.cpse_code

    def as_dict(self) -> dict:
        return {
            "role": self.role,
            "cpse": self.cpse_code,
            "sees_attributed_prices": self.sees_all_prices,
            "note": (
                "Full per-CPSE prices and valuations."
                if self.sees_all_prices
                else "Other CPSEs' prices are shown as an anonymised range; "
                "your own are shown in full (§0.9b)."
            ),
        }


ANONYMOUS = Scope(role="viewer", cpse_code=None)


def scope_for(user) -> Scope:
    """Build a scope from the signed-in user, or the most restricted one."""
    if user is None:
        return ANONYMOUS
    return Scope(
        role=user.role,
        cpse_code=user.cpse.code if getattr(user, "cpse", None) else None,
    )


def redact_prices(rows: list[dict], scope: Scope, cpse_key: str = "cpse") -> list[dict]:
    """Drop other CPSEs' attributed prices for a restricted viewer.

    The row is kept — knowing that four CPSEs buy the same item is the whole
    point — but the price is replaced with a marker so the caller can render
    "withheld" rather than a misleading zero.
    """
    if scope.sees_all_prices:
        return rows
    out = []
    for row in rows:
        if scope.owns(row.get(cpse_key)):
            out.append(row)
            continue
        redacted = dict(row)
        for field in ("unit_price", "price", "value", "unit_value", "total_value"):
            if field in redacted:
                redacted[field] = None
        redacted["price_withheld"] = True
        out.append(redacted)
    return out


def price_band(prices: list[float]) -> dict | None:
    """The anonymised aggregate a steward sees instead of attributed prices."""
    clean = [p for p in prices if p is not None and p > 0]
    if not clean:
        return None
    return {
        "min": round(min(clean), 2),
        "max": round(max(clean), 2),
        "mean": round(sum(clean) / len(clean), 2),
        "n": len(clean),
        "label": f"market range ₹{min(clean):,.0f}–₹{max(clean):,.0f}, n={len(clean)} CPSEs",
    }
