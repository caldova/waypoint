"""Fixture data used until live Waypoint invoice/contract APIs exist."""

from __future__ import annotations


def latest_invoice_fixtures() -> list[dict[str, str]]:
    return [
        {
            "invoice_id": "INV-AR-1042",
            "supplier": "Aster Ridge",
            "amount": "$128,750",
            "status": "Needs review",
            "summary": "Release admin fee exceeds fixture policy threshold.",
        },
        {
            "invoice_id": "INV-NL-2207",
            "supplier": "Northline Labs",
            "amount": "$42,180",
            "status": "Ready",
            "summary": "Matched expected monthly assay services.",
        },
        {
            "invoice_id": "INV-VX-7714",
            "supplier": "VireoX",
            "amount": "$19,640",
            "status": "Missing evidence",
            "summary": "Pass-through materials need sponsor approval.",
        },
    ]
