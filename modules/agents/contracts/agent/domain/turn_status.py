"""Turn-scoped progress status that tools can update while the model works."""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Awaitable, Callable, Iterator
from contextvars import ContextVar

logger = logging.getLogger(__name__)

StatusReporter = Callable[[str], Awaitable[None]]

_reporter: ContextVar[StatusReporter | None] = ContextVar(
    "contracts_status_reporter", default=None
)

_INVOICE_ID = re.compile(r"\bINV-[A-Za-z0-9][A-Za-z0-9_-]*", re.IGNORECASE)


@contextlib.contextmanager
def status_reporter(report: StatusReporter) -> Iterator[None]:
    token = _reporter.set(report)
    try:
        yield
    finally:
        _reporter.reset(token)


async def report_status(text: str) -> None:
    """Best-effort status update; never fails the tool that calls it."""
    report = _reporter.get()
    if report is None:
        return
    try:
        await report(text)
    except Exception:
        logger.debug("status update failed", exc_info=True)


def checking_invoice(invoice_id: str) -> str:
    return f"Checking {invoice_id}..."


def creating_review_document(invoice_id: str) -> str:
    return f"Creating Review Document for {invoice_id}..."


CHECKING_INVOICES = "Checking Invoices..."
CHECKING_CONTRACTS = "Checking Contracts..."
_WANTS_DOCUMENT = re.compile(
    r"\b(review|report)\s+doc|\b(create|draft|make|write|generate|prepare)\b"
    r".*\b(review|report|document|doc)\b"
)
_NEGATED = re.compile(r"\b(don'?t|do not|no need|without)\b")


def initial_status(text: str) -> str:
    """Best first guess from the prompt; tools refine it once they run."""
    lowered = (text or "").lower()
    match = _INVOICE_ID.search(text or "")
    if match:
        invoice_id = match.group(0).upper()
        if _WANTS_DOCUMENT.search(lowered) and not _NEGATED.search(lowered):
            return creating_review_document(invoice_id)
        return checking_invoice(invoice_id)
    if "invoice" in lowered:
        return CHECKING_INVOICES
    return CHECKING_CONTRACTS
