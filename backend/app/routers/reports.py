"""The per-CPSE catalogue report: preview, send, and who has had one.

Who may ask for whose report is the one rule here. The ministry's roles
(registrar, admin, auditor) may read any CPSE's; a CPSE's own people
(steward, approver, engineer with a CPSE) only their own. Whoever asks, the
document is redacted as that CPSE's steward would see it (`reports`), so
the answer to "may the registrar send CPCL its report" is yes, and the
report still carries no other CPSE's price.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import reports
from ..auth import require_roles, require_user
from ..db import get_db
from ..models import Cpse, User
from ..visibility import UNRESTRICTED_ROLES, scope_for

router = APIRouter(prefix="/reports", tags=["reports"])

#: Roles that may read their own CPSE's report.
OWN_CPSE_ROLES = ("steward", "approver", "engineer")


class SendIn(BaseModel):
    to: list[str] | None = None


def _authorise(user: User, code: str) -> str:
    """The CPSE code the request may proceed with, or a plain 403."""
    code = code.upper()
    if user.role in UNRESTRICTED_ROLES:
        return code
    own = user.cpse.code if user.cpse else None
    if user.role in OWN_CPSE_ROLES and own == code:
        return code
    if user.role in OWN_CPSE_ROLES and own:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"You may only see {own}'s report. Another CPSE's is registrar and auditor scope.",
        )
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "A catalogue report is for the CPSE's own steward, or the registrar, admin and "
        f"auditor. You are signed in as {user.role}.",
    )


def _report_or_404(db: Session, user: User, code: str) -> dict:
    try:
        return reports.cpse_report(db, code, scope_for(user))
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("")
def list_reports(
    user: Annotated[User, Depends(require_user)],
    db: Session = Depends(get_db),
) -> dict:
    """Every CPSE, its contact address and when it last received a report.

    The ministry's roles see the whole list; a CPSE's own people see their
    own row, which is what the Home card needs.
    """
    listing = reports.listing(db)
    if user.role not in UNRESTRICTED_ROLES:
        own = user.cpse.code if user.cpse else None
        listing["cpses"] = [row for row in listing["cpses"] if row["code"] == own]
    return listing


@router.get("/cpse/{code}", response_model=None)
def cpse_report(
    code: str,
    user: Annotated[User, Depends(require_user)],
    format: str = Query(default="json", pattern="^(json|html)$"),
    db: Session = Depends(get_db),
) -> dict | HTMLResponse:
    """The report as JSON, or with `?format=html` the printable document."""
    code = _authorise(user, code)
    report = _report_or_404(db, user, code)
    if format == "html":
        return HTMLResponse(reports.render_html(report))
    return report


@router.post("/cpse/{code}/send")
def send_report(
    code: str,
    body: SendIn,
    user: Annotated[User, Depends(require_user)],
    db: Session = Depends(get_db),
) -> dict:
    """Deliver the report: by SMTP when configured, otherwise into the outbox.

    With no recipients in the body the CPSE's contact address is used; a CPSE
    without one is a 422 that says so, not a silent no-op.
    """
    code = _authorise(user, code)
    to = [addr for addr in (body.to or []) if addr and addr.strip()]
    if not to:
        cpse = db.execute(select(Cpse).where(Cpse.code == code)).scalar_one_or_none()
        if cpse is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown CPSE {code!r}.")
        if not cpse.contact_email:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{code} has no contact email. Set one under Administration, or name "
                "the recipients in the request.",
            )
        to = [cpse.contact_email]
    report = _report_or_404(db, user, code)
    html = reports.render_html(report)
    try:
        result = reports.deliver(report, html, to, db=db, user=user.email)
    except OSError as exc:
        # A relay that refuses or a disk that is full: say which, plainly.
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"The report could not be delivered: {exc}"
        ) from exc
    result["note"] = (
        f"Sent to {', '.join(to)} by SMTP."
        if result["mode"] == "smtp"
        else f"No SMTP relay is configured; the message was written to the outbox at "
        f"{result['path']}."
    )
    return result


@router.get("/rollup", response_model=None)
def rollup(
    user: Annotated[User, Depends(require_roles(*UNRESTRICTED_ROLES, "approver"))],
    format: str = Query(default="json", pattern="^(json|html)$"),
    db: Session = Depends(get_db),
) -> dict | HTMLResponse:
    """Every CPSE on one page for the reader above them; each company's
    money as a quarter among its peers, the estate's totals exact."""
    doc = reports.rollup(db, scope_for(user))
    if format == "html":
        return HTMLResponse(reports.render_rollup_html(doc))
    return doc
