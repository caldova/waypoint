"""Markdown for an invoice review document, built from Caldova invoice records.

Facts (amounts, findings, lines, evidence) come straight from the API and are
laid out by code. The model reads ``review_inputs`` (facts plus FoundryIQ
contract/policy text) and writes the narrative: summary, recommendation, next
steps, and a per-finding analysis with clause quotes that are checked verbatim
against the retrieved text before they are rendered.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}
_ALERT_BY_RANK = {4: "CAUTION", 3: "CAUTION", 2: "WARNING", 1: "NOTE", 0: "NOTE"}
# Most consequential disposition wins the headline.
_DISPOSITIONS = (
    ("escalate", "Escalate before payment"),
    ("recover", "Recover before payment"),
    ("review", "Hold for review"),
    ("open", "Hold for review"),
)
_STOP_TERMS = {
    "about", "agreement", "also", "applicable", "billed", "charge", "contract",
    "cost", "costs", "from", "have", "including", "invoice", "line", "must",
    "only", "policies", "policy", "sponsor", "supplier", "that", "their", "there",
    "this", "under", "were", "when", "where", "which", "with", "within",
}  # fmt: skip
_MIN_CLAUSE_SCORE = 4
_MAX_QUOTE_CHARS = 700
_MIN_VERIFIED_QUOTE_CHARS = 20
_ACTIONABLE = {"open", "review", "recover", "escalate"}


def invoice_findings(
    detail: dict[str, Any], context: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Invoice findings, preferring the context bundle copy (it carries ``basis_summary``)."""
    source = (context or {}).get("invoice")
    if isinstance(source, dict) and isinstance(source.get("findings"), list):
        return [item for item in source["findings"] if isinstance(item, dict)]
    return [item for item in detail.get("findings") or [] if isinstance(item, dict)]


def _findings_known(detail: dict[str, Any], context: dict[str, Any] | None) -> bool:
    source = (context or {}).get("invoice")
    return isinstance(detail.get("findings"), list) or (
        isinstance(source, dict) and isinstance(source.get("findings"), list)
    )


def is_actionable(finding: dict[str, Any]) -> bool:
    """Approved or closed findings are history, not payment risk."""
    return _lower(finding.get("status")) in _ACTIONABLE


def money_at_risk(findings: list[dict[str, Any]]) -> Decimal:
    return sum(
        (
            _decimal(item.get("overpayment_amount"))
            for item in findings
            if is_actionable(item)
        ),
        Decimal(0),
    )


def document_chunks(document: dict[str, Any]) -> list[str]:
    """Retrieved text for a contract/policy, one entry per independent chunk."""
    chunks = document.get("text_chunks")
    if isinstance(chunks, list):
        return [chunk for chunk in chunks if isinstance(chunk, str) and chunk.strip()]
    text = document.get("text")
    return [text] if isinstance(text, str) and text.strip() else []


def review_inputs(
    detail: dict[str, Any], context: dict[str, Any] | None
) -> dict[str, Any]:
    """What the model needs to write the review: facts plus contract/policy text."""
    context = context or {}
    invoice = (
        context.get("invoice") if isinstance(context.get("invoice"), dict) else detail
    )
    currency = str(detail.get("currency") or "USD")
    findings = invoice_findings(detail, context)
    known = _findings_known(detail, context)
    actionable = any(is_actionable(item) for item in findings) if known else None
    lines = [item for item in invoice.get("lines") or [] if isinstance(item, dict)]
    evidence = {
        str(item.get("id")): item
        for item in invoice.get("evidence") or []
        if isinstance(item, dict)
    }
    total = _decimal(detail.get("total_amount"))
    at_risk = money_at_risk(findings)
    documents: list[dict[str, Any]] = []
    for kind, key, name_key in (
        ("contract", "contract_documents", "title"),
        ("policy", "policies", "name"),
    ):
        for document in _by_id(context.get(key)).values():
            chunks = document_chunks(document)
            documents.append(
                {
                    "document_id": document.get("id"),
                    "kind": kind,
                    "title": document.get(name_key),
                    "effective_date": document.get("effective_date"),
                    "text": "\n\n[…]\n\n".join(chunks) if chunks else None,
                }
            )
    return {
        "invoice": {
            "invoice_number": detail.get("invoice_number") or detail.get("id"),
            "supplier": _dict(detail.get("supplier")).get("name")
            or detail.get("supplier_id"),
            "invoice_date": detail.get("invoice_date"),
            "due_date": detail.get("due_date"),
            "status": detail.get("status"),
            "total": _money(total, currency),
            "money_at_risk": _money(at_risk, currency),
            "share_at_risk": _percent(at_risk, total) if total else None,
            "review_area": _dict(detail.get("scenario")).get("name"),
        },
        "findings_known": known,
        "findings": [
            {
                "finding_id": finding.get("id"),
                "category": _dict(finding.get("metadata")).get("display_category")
                or _title(finding.get("category")),
                "severity": finding.get("severity"),
                "disposition": _disposition(finding.get("status")),
                "actionable": is_actionable(finding),
                "overpayment": _money(finding.get("overpayment_amount"), currency),
                "summary": finding.get("summary"),
                "basis": finding.get("basis_summary")
                or _dict(finding.get("metadata")).get("basis_summary"),
                "evidence": [
                    {
                        "label": _evidence_label(evidence[str(eid)]),
                        "excerpt": _squash(evidence[str(eid)].get("excerpt")),
                    }
                    for eid in finding.get("evidence_ids") or []
                    if str(eid) in evidence
                ],
                "contract_document_ids": finding.get("contract_document_ids") or [],
                "policy_ids": finding.get("policy_ids") or [],
            }
            for finding in findings
        ],
        "lines": [
            {
                "sku": line.get("sku"),
                "description": line.get("description"),
                "quantity": _quantity(line.get("quantity")),
                "unit_price": _money(line.get("unit_price"), currency),
                "amount": _money(line.get("amount"), currency),
                "review": _line_review(line, actionable) or None,
            }
            for line in lines
        ],
        "documents": documents,
        "cases": [
            {"title": case.get("title"), "status": case.get("status")}
            for case in context.get("cases") or []
            if isinstance(case, dict) and case.get("title")
        ],
    }


def verify_analyses(
    analyses: Any, detail: dict[str, Any], context: dict[str, Any] | None
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Keep model-written finding analyses; drop clause quotes not found verbatim.

    Returns ``(by_finding_id, dropped)`` where each kept entry is
    ``{"analysis": str, "clauses": [{"document_id", "title", "section", "quote"}]}``.
    """
    context = context or {}
    finding_ids = {str(item.get("id")) for item in invoice_findings(detail, context)}
    documents = {
        **{
            key: (doc, "title")
            for key, doc in _by_id(context.get("contract_documents")).items()
        },
        **{key: (doc, "name") for key, doc in _by_id(context.get("policies")).items()},
    }
    kept: dict[str, dict[str, Any]] = {}
    dropped: list[dict[str, Any]] = []
    for item in analyses if isinstance(analyses, list) else []:
        if not isinstance(item, dict):
            continue
        finding_id = str(item.get("finding_id") or "").strip()
        if finding_id not in finding_ids:
            dropped.append({"finding_id": finding_id, "reason": "unknown_finding_id"})
            continue
        entry = kept.setdefault(finding_id, {"analysis": "", "clauses": []})
        analysis = str(item.get("analysis") or "").strip()
        if analysis:
            entry["analysis"] = analysis
        clauses = item.get("clauses")
        for clause in clauses if isinstance(clauses, list) else []:
            if not isinstance(clause, dict):
                continue
            document_id = str(clause.get("document_id") or "").strip()
            quote = str(clause.get("quote") or "").strip()
            found = documents.get(document_id)
            section = (
                _locate_quote(quote, document_chunks(found[0]))
                if found is not None
                else None
            )
            reason = (
                "unknown_document_id"
                if found is None
                else "quote_too_short"
                if len(_normalize_quote(quote)) < _MIN_VERIFIED_QUOTE_CHARS
                else "quote_not_in_retrieved_text"
                if section is None
                else ""
            )
            if reason:
                dropped.append(
                    {
                        "finding_id": finding_id,
                        "document_id": document_id,
                        "reason": reason,
                    }
                )
                continue
            document, name_key = found
            entry["clauses"].append(
                {
                    "document_id": document_id,
                    "title": document.get(name_key),
                    # Label from the source heading, never the model's claim.
                    "section": section,
                    "quote": quote,
                }
            )
    return kept, dropped


def _normalize_quote(text: str) -> str:
    text = (
        text.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    text = re.sub(r"(?m)^\s*(?:>|[-*+]|\d+\.)\s+", " ", text)
    text = re.sub(r"[*_`#]", "", text)
    return " ".join(text.split()).lower()


def _locate_quote(quote: str, chunks: list[str]) -> str | None:
    """Return the heading of the section holding the quote ("" if unheaded), else None.

    Every ellipsis-separated part must appear, in order, within one section of one chunk.
    """
    parts = [
        _normalize_quote(part) for part in re.split(r"\.\.\.|…|\[…\]|\[\.\.\.\]", quote)
    ]
    parts = [part for part in parts if part]
    if not parts:
        return None
    for chunk in chunks:
        candidates = [(h, f"{h}\n{b}") for h, b in _sections(chunk)] + [("", chunk)]
        for heading, text in candidates:
            haystack = _normalize_quote(text)
            position = 0
            for part in parts:
                position = haystack.find(part, position)
                if position < 0:
                    break
                position += len(part)
            else:
                return heading
    return None


def _prose(text: Any) -> str:
    """Model-written prose as plain paragraphs: no headings, tables, quotes, lists, or links."""
    paragraphs = []
    for block in re.split(r"\n\s*\n", str(text or "").strip()):
        lines = []
        for line in block.splitlines():
            line = re.sub(
                r"^\s*(?:#{1,6}\s+|>+\s*|\|+\s*|[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+)",
                "",
                line,
            )
            line = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", line)
            line = re.sub(r"<[^>]+>", "", line).replace("|", "/")
            if line.strip() and not re.fullmatch(r"[\s\-*_=:|/]+", line):
                lines.append(line.strip())
        if lines:
            paragraphs.append(" ".join(lines))
    return "\n\n".join(paragraphs)


def build_invoice_review_markdown(
    detail: dict[str, Any],
    context: dict[str, Any] | None,
    *,
    summary: str,
    recommendation: str,
    prepared_on: str,
    next_steps: list[str] | None = None,
    analyses: dict[str, dict[str, Any]] | None = None,
) -> str:
    context = context or {}
    analyses = analyses or {}
    # The context bundle's invoice copy has classification-filtered evidence.
    invoice = (
        context.get("invoice") if isinstance(context.get("invoice"), dict) else detail
    )
    currency = str(detail.get("currency") or "USD")
    supplier = _dict(detail.get("supplier"))
    number = str(detail.get("invoice_number") or detail.get("id") or "")
    findings = invoice_findings(detail, context)
    lines = [item for item in invoice.get("lines") or [] if isinstance(item, dict)]
    evidence = {
        str(item.get("id")): item
        for item in invoice.get("evidence") or []
        if isinstance(item, dict)
    }
    contracts = _by_id(context.get("contract_documents"))
    policies = _by_id(context.get("policies"))
    total = _decimal(detail.get("total_amount"))
    at_risk = money_at_risk(findings)

    out = [f"# Invoice review: {number}", ""]
    byline = [f"**{supplier.get('name') or detail.get('supplier_id') or 'Supplier'}**"]
    if detail.get("invoice_date"):
        byline.append(f"Invoiced {_date(detail['invoice_date'])}")
    if detail.get("due_date"):
        byline.append(f"Due {_date(detail['due_date'])}")
    out += [
        " · ".join(byline),
        "",
        f"*Prepared {_date(prepared_on)} by the Caldova Contracts agent.*",
        "",
    ]
    out += _headline(
        findings, total, at_risk, currency, known=_findings_known(detail, context)
    )
    out += _at_a_glance(detail, findings, total, at_risk, currency)

    out += ["## Summary", "", _prose(summary) or "_No summary provided._", ""]
    out += [
        "## Recommendation",
        "",
        _prose(recommendation) or "_No recommendation provided._",
        "",
    ]
    steps = [
        " ".join(_prose(step).split()) for step in next_steps or [] if _prose(step)
    ]
    if steps:
        out += ["### Next steps", ""]
        out += [f"- [ ] {step}" for step in steps]
        out.append("")

    out += ["## Findings", ""]
    if not findings:
        out += [
            (
                "No findings on file; nothing in Caldova records blocks payment."
                if _findings_known(detail, context)
                else "Findings were not returned by Caldova records; confirm before paying."
            ),
            "",
        ]
    actionable: bool | None = (
        any(is_actionable(item) for item in findings)
        if _findings_known(detail, context)
        else None
    )
    flagged = [line for line in lines if _line_review(line, actionable) == "Flagged"]
    for index, finding in enumerate(findings, start=1):
        out += _finding_section(
            index,
            finding,
            currency=currency,
            flagged_lines=flagged
            if len(findings) == 1 and is_actionable(finding)
            else [],
            contracts=contracts,
            policies=policies,
            evidence=evidence,
            analysis=analyses.get(str(finding.get("id"))),
        )

    if lines:
        out += _lines_table(lines, total, currency, actionable)
    out += _sources(contracts, policies, context)
    out += _sign_off()
    out += [
        "---",
        "",
        (
            "*Figures, findings, and evidence come from Caldova records. Contract "
            "and policy passages, where shown, are quoted verbatim from the Caldova "
            "contract knowledge base. The summary, analysis, recommendation, and next "
            "steps were drafted by the Contracts agent and need reviewer confirmation.*"
        ),
        "",
    ]
    return "\n".join(out)


def _headline(
    findings: list[dict[str, Any]],
    total: Decimal,
    at_risk: Decimal,
    currency: str,
    *,
    known: bool,
) -> list[str]:
    if not known:
        return [
            "> [!WARNING]",
            "> **Findings unavailable.** Payment status could not be determined.",
            "",
        ]
    open_items = [item for item in findings if is_actionable(item)]
    if not open_items:
        cleared = (
            f" {len(findings)} finding{'s' if len(findings) != 1 else ''} resolved."
            if findings
            else " No findings on this invoice."
        )
        return ["> [!TIP]", f"> **Clear to pay.**{cleared}", ""]
    findings = open_items
    rank = max(_SEVERITY_RANK.get(_lower(item.get("severity")), 0) for item in findings)
    statuses = {_lower(item.get("status")) for item in findings}
    verdict = next(
        (label for status, label in _DISPOSITIONS if status in statuses),
        "Review before payment",
    )
    count = f"{len(findings)} finding{'s' if len(findings) != 1 else ''}"
    share = (
        f" ({_percent(at_risk, total)} of {_money(total, currency)})" if total else ""
    )
    severity = _severity_label(rank)
    return [
        f"> [!{_ALERT_BY_RANK[rank]}]",
        (
            f"> **{verdict}.** {_money(at_risk, currency)}{share} is at risk across "
            f"{count}; highest severity {severity}."
        ),
        "",
    ]


def _at_a_glance(
    detail: dict[str, Any],
    findings: list[dict[str, Any]],
    total: Decimal,
    at_risk: Decimal,
    currency: str,
) -> list[str]:
    scenario = _dict(detail.get("scenario"))
    rows = [
        ("Invoice total", _money(total, currency)),
        ("Money at risk", _money(at_risk, currency)),
        ("Share at risk", _percent(at_risk, total) if total else ""),
        ("Findings", str(len(findings))),
        ("Invoice status", _title(detail.get("status"))),
        ("Review area", scenario.get("name")),
    ]
    out = ["## At a glance", "", "| | |", "| --- | ---: |"]
    out += [f"| {label} | {_cell(value)} |" for label, value in rows if value]
    return [*out, ""]


def _finding_section(
    index: int,
    finding: dict[str, Any],
    *,
    currency: str,
    flagged_lines: list[dict[str, Any]],
    contracts: dict[str, dict[str, Any]],
    policies: dict[str, dict[str, Any]],
    evidence: dict[str, dict[str, Any]],
    analysis: dict[str, Any] | None = None,
) -> list[str]:
    metadata = _dict(finding.get("metadata"))
    category = metadata.get("display_category") or _title(finding.get("category"))
    severity = _title(finding.get("severity"))
    out = [
        f"### {index}. {category}",
        "",
        str(finding.get("summary") or "").strip(),
        "",
        "| Severity | Disposition | Overpayment |",
        "| --- | --- | ---: |",
        "| "
        + " | ".join(
            _cell(value)
            for value in (
                severity or "Unrated",
                _disposition(finding.get("status")),
                _money(finding.get("overpayment_amount"), currency),
            )
        )
        + " |",
        "",
    ]
    for line in flagged_lines:
        out += [
            (
                f"**Disputed line:** {_cell(line.get('sku'))} · {_cell(line.get('description'))} "
                f"· {_money(line.get('amount'), currency)}"
            ),
            "",
        ]
    basis = finding.get("basis_summary") or metadata.get("basis_summary")
    if basis:
        out += [f"**Basis:** {str(basis).strip()}", ""]
    written = _prose(analysis.get("analysis")) if analysis else ""
    if written:
        out += [written, ""]
    if analysis and analysis.get("clauses"):
        for clause in analysis["clauses"]:
            label = (
                "What the contract says"
                if clause["document_id"] in contracts
                else ("What policy requires")
            )
            section = re.sub(r"[*_`]", "", clause["section"])
            where = f", {section}" if section else ""
            out += [
                f"**{label}:** *{clause['title']}{where}*",
                "",
                *_blockquote(clause["quote"]),
                "",
            ]
    elif written:
        # The agent judged this finding; keyword-matched clauses would mask a grounding gap.
        out += ["*No contract or policy passage was quoted for this finding.*", ""]
    else:
        out += _matched_clauses(finding, basis, metadata, contracts, policies)

    items = [
        evidence[str(eid)]
        for eid in finding.get("evidence_ids") or []
        if str(eid) in evidence
    ]
    if items:
        labels = [_evidence_label(item) for item in items]
        out += [f"**Evidence on file:** {'; '.join(labels)}.", ""]
        summary = _squash(finding.get("summary"))
        for item in items:
            excerpt = _squash(item.get("excerpt"))
            if excerpt and summary not in excerpt:
                out += [f"> *{_evidence_label(item)}:* {excerpt}", ""]
    return out


def _blockquote(text: str) -> list[str]:
    return [f"> {line}" if line.strip() else ">" for line in text.strip().split("\n")]


def _matched_clauses(
    finding: dict[str, Any],
    basis: Any,
    metadata: dict[str, Any],
    contracts: dict[str, dict[str, Any]],
    policies: dict[str, dict[str, Any]],
) -> list[str]:
    """Keyword-matched clauses, used when the model supplied no verified quotes."""
    query = " ".join(
        str(value or "")
        for value in (
            finding.get("summary"),
            basis,
            finding.get("category"),
            metadata.get("display_category"),
        )
    )
    out: list[str] = []
    for label, documents, ids, name_key in (
        (
            "What the contract says",
            contracts,
            finding.get("contract_document_ids"),
            "title",
        ),
        ("What policy requires", policies, finding.get("policy_ids"), "name"),
    ):
        for document_id in ids or []:
            document = documents.get(str(document_id))
            if not document:
                continue
            chunks = document_chunks(document)
            clause = _best_clause(chunks, query, document.get(name_key))
            if clause:
                heading, body = clause
                out += [
                    f"**{label}:** *{document.get(name_key)}, {heading}*",
                    "",
                    *_blockquote(body),
                    "",
                ]
            elif documents is contracts and chunks:
                out += [
                    (
                        f"**{label}:** No clause in *{document.get(name_key)}* "
                        "closely matches this charge."
                    ),
                    "",
                ]
    return out


def _lines_table(
    lines: list[dict[str, Any]], total: Decimal, currency: str, actionable: bool | None
) -> list[str]:
    out = [
        "## Invoice lines",
        "",
        "| # | SKU | Description | PO | Qty | Unit price | Amount | Review |",
        "| ---: | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for index, line in enumerate(lines, start=1):
        review = _line_review(line, actionable)
        out.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    index,
                    line.get("sku"),
                    line.get("description"),
                    line.get("purchase_order"),
                    _quantity(line.get("quantity")),
                    _money(line.get("unit_price"), currency),
                    _money(line.get("amount"), currency),
                    f"**{review}**" if review == "Flagged" else review,
                )
            )
            + " |"
        )
    out += [f"| | | **Total** | | | | **{_money(total, currency)}** | |", ""]
    return out


def _sources(
    contracts: dict[str, dict[str, Any]],
    policies: dict[str, dict[str, Any]],
    context: dict[str, Any],
) -> list[str]:
    out: list[str] = []
    for document in contracts.values():
        effective = (
            f", effective {_date(document['effective_date'])}"
            if document.get("effective_date")
            else ""
        )
        out.append(f"- **Contract:** {document.get('title')}{effective}")
    for policy in policies.values():
        out.append(f"- **Policy:** {policy.get('name')}")
    for case in context.get("cases") or []:
        if isinstance(case, dict) and case.get("title"):
            status = f" ({_title(case.get('status'))})" if case.get("status") else ""
            out.append(f"- **Case:** {case['title']}{status}")
    withheld = len(context.get("redactions") or [])
    if withheld:
        out.append(
            f"- {withheld} evidence item{'s' if withheld != 1 else ''} withheld "
            "from this document by classification."
        )
    return ["## Sources", "", *out, ""] if out else []


def _sign_off() -> list[str]:
    return [
        "## Reviewer sign-off",
        "",
        "| Role | Name | Decision | Date |",
        "| --- | --- | --- | --- |",
        "| Reviewer |  | Approve · Hold · Recover · Escalate |  |",
        "| Approver |  | Approve · Hold · Recover · Escalate |  |",
        "",
    ]


def _best_clause(
    chunks: list[str], query: str, document_name: Any
) -> tuple[str, str] | None:
    """Pick the document section that best matches the finding, if any matches well."""
    wanted = _terms(query) - _terms(str(document_name or ""))
    best: tuple[int, str, str] | None = None
    # Chunks may arrive out of order, so sections never span a chunk boundary.
    for chunk in chunks:
        for heading, body in _sections(chunk):
            score = 3 * len(wanted & _terms(heading)) + len(wanted & _terms(body))
            if score >= _MIN_CLAUSE_SCORE and (best is None or score > best[0]):
                best = (score, heading, body)
    if best is None:
        return None
    _, heading, body = best
    numbered = re.match(r"^(\d+(?:\.\d+)*)\.?\s+(.*)$", heading)
    label = f"§{numbered.group(1)} {numbered.group(2)}" if numbered else heading
    return label, _trim(body)


def _sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading: str | None = None
    body: list[str] = []
    for raw in text.splitlines():
        match = re.match(r"^#{2,4}\s+(.*)$", raw.strip())
        if match:
            if heading is not None:
                sections.append((heading, "\n".join(body).strip()))
            heading, body = match.group(1).strip(), []
        elif heading is not None:
            body.append(raw.rstrip())
    if heading is not None:
        sections.append((heading, "\n".join(body).strip()))
    return [(h, b) for h, b in sections if b]


def _terms(text: str) -> set[str]:
    return {
        _stem(word)
        for word in re.findall(r"[a-z]+", text.lower())
        if len(word) >= 4 and word not in _STOP_TERMS
    }


def _stem(word: str) -> str:
    # A fixed prefix is crude but consistent across inflections
    # (escalated/escalation, contamination/contaminated).
    return word[:6]


def _trim(body: str) -> str:
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", body) if p.strip()]
    kept: list[str] = []
    for para in paragraphs:
        if sum(len(p) for p in kept) + len(para) > _MAX_QUOTE_CHARS and kept:
            break
        kept.append(para)
    joined = "\n\n".join(kept)
    if len(joined) > _MAX_QUOTE_CHARS:
        cut = joined[:_MAX_QUOTE_CHARS]
        joined = cut[: cut.rfind(". ") + 1] if ". " in cut else cut.rstrip() + "…"
    return joined


def _line_review(line: dict[str, Any], actionable: bool | None) -> str:
    metadata = _dict(line.get("metadata"))
    if metadata.get("line_role") == "decision_line":
        # decision_line marks the line a decision is about, adverse or not.
        if actionable is None:
            return ""
        return "Flagged" if actionable else "Cleared"
    if metadata.get("reconciliation_state") == "matched":
        return "Matched"
    return ""


def _evidence_label(item: dict[str, Any]) -> str:
    label = _dict(item.get("metadata")).get("source_label") or str(
        item.get("evidence_type") or item.get("title") or "evidence"
    ).replace("_", " ")
    return str(label)[:1].upper() + str(label)[1:]


def _disposition(status: Any) -> str:
    return {
        "escalate": "Escalate",
        "recover": "Recover overpayment",
        "review": "Hold for review",
        "open": "Hold for review",
        "approved": "Cleared",
        "closed": "Closed",
    }.get(_lower(status), _title(status))


def _severity_label(rank: int) -> str:
    return {4: "Critical", 3: "High", 2: "Medium", 1: "Low"}.get(rank, "Unrated")


def _by_id(items: Any) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id")): item
        for item in items or []
        if isinstance(item, dict) and item.get("id")
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _title(value: Any) -> str:
    return str(value or "").replace("_", " ").strip().capitalize()


def _squash(value: Any) -> str:
    return " ".join(str(value or "").split())


def _cell(value: Any) -> str:
    return " ".join(str(value if value is not None else "").replace("|", "\\|").split())


def _date(value: Any) -> str:
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value)
    return f"{parsed:%b} {parsed.day}, {parsed.year}"


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value)) if value not in (None, "") else Decimal(0)
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _quantity(value: Any) -> str:
    amount = _decimal(value)
    return f"{amount:,.0f}" if amount == amount.to_integral() else f"{amount:,}"


def _percent(part: Decimal, whole: Decimal) -> str:
    return f"{(part / whole * 100):.1f}%" if whole else ""


def _money(value: Any, currency: str) -> str:
    amount = _decimal(value)
    if currency.upper() == "USD":
        return f"${amount:,.2f}"
    return f"{amount:,.2f} {currency.upper()}"
