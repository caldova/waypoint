"""Build versioned evidence-only reference candidates for contract-policy RFT.

The historical labels phrase claims and summaries as finance directives
("Dispute ...", "Request ..."), which conflicts with the agent's evidence-only
contract. This module derives v3 candidates without editing the originals:

* claims paraphrase the cited contract/policy section text in neutral terms;
* `unsupported` names specific evidence that is not visible in the prompt;
* summaries describe the evidence direction and reserve the payment decision;
* `supports` labels are carried over unchanged and flagged for domain review
  where the historical direction looks inconsistent.

Every row is synthetic, `pending_human_review`, and keeps its historical label
under `metadata.historical_reference`. Train/validation also receive coverage
rows (distractor context, supported approval evidence, missing evidence);
eval and challenge only receive the label transform so they stay held out.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

EVIDENCE_ONLY_VERSION = "contract-policy-evidence-only-v3"
LABEL_SOURCE = "synthetic_evidence_only_reference_v3"
REVIEW_STATUS = "pending_human_review"
CONFIDENCE = 0.86
RESERVED = "The payment decision remains reserved to the controller."

SOURCE_FILES = {
    "train": "contract-policy-expert-train.jsonl",
    "validation": "contract-policy-expert-validation.jsonl",
    "eval": "contract-policy-expert-eval.jsonl",
    "challenge": "contract-policy-expert-challenge-candidates.jsonl",
}
COVERAGE_SPLITS = ("train", "validation")
RECON_4 = "invoice-reconciliation-policy.md#4-minimum-evidence-for-approval"

EVIDENCE_ONLY_SCHEMA_PROMPT = (
    "\n\nReturn exactly this JSON object shape and no other top-level keys: "
    '{"agent":"contract-policy-expert","plane":"foundryiq","invoice_id":"<invoice_id>",'
    '"output_type":"expert_evidence","evidence":[{"claim":"<neutral claim grounded in the '
    'cited section>","supports":"approve|recover|escalate|review|unknown",'
    '"source_ref":"<exact retrieved_context source_ref>",'
    '"classification":"standard|confidential|ip_sensitive|restricted","confidence":0.0}],'
    '"unsupported":["<specific missing or unverified evidence>"],'
    '"summary":"<neutral evidence summary for controller review>",'
    '"correlation":{"waypoint_invoice_id":"<invoice_id>","waypoint_run_id":"unknown"}}. '
    "Each evidence row must use exact source_ref values from retrieved_context. "
    "supports describes the direction of the cited evidence for controller review, not a "
    "finance action: approve means the cited evidence satisfies the billability condition; "
    "recover means the evidence indicates the line is not billable as billed; escalate means "
    "the policy routes the condition to escalation; review means support depends on facts "
    "that need controller verification; unknown means the evidence is insufficient. "
    "List each specific missing or unverified fact in unsupported; use an empty array only "
    "when retrieved_context and the supplied facts contain all evidence needed. Describe "
    "evidence only: do not instruct anyone to pay, dispute, hold, request, recover, or "
    "escalate, and do not claim that any action was taken. " + RESERVED
)

POLICY_CLAIMS = {
    RECON_4: (
        "An invoice line may be approved only when the billed item can be tied to an "
        "authorized source document."
    ),
    "quality-release-billability-policy.md#3-pending-batches": (
        "Pending batches are not billable for completed production, release testing, or "
        "release administration fees until release or a contract-defined milestone."
    ),
    "invoice-dispute-and-recovery-procedure.md#2-dispute-packet": (
        "A dispute packet lists the disputed amount, the contract clause or policy basis, "
        "and supporting operational evidence."
    ),
    "invoice-reconciliation-policy.md#2-required-reconciliation": (
        "The reconciliation policy checks supplier invoices against contract terms, "
        "purchase orders, and the applicable operational records."
    ),
    "invoice-dispute-and-recovery-procedure.md#3-supplier-response": (
        "The supplier response procedure cites the controlling contract term and explains "
        "the variance for the invoice line."
    ),
    "invoice-dispute-and-recovery-procedure.md#6-escalation": (
        "The escalation procedure lists quality status conflicts and potential compliance "
        "impact among dispute escalation triggers."
    ),
    "quality-release-billability-policy.md#6-required-evidence": (
        "Quality-related invoice lines reference batch ID, release status, release date, "
        "test record, or sponsor approval as applicable."
    ),
    "invoice-dispute-and-recovery-procedure.md#5-withholding-disputed-amounts": (
        "The procedure permits withholding disputed amounts while undisputed amounts follow "
        "payment terms."
    ),
}
LEAKAGE_CLAIMS = {
    "scn-cmo-004-yield-true-up": (
        "Invalid true-up and wrong volume are listed payment leakage categories."
    ),
    "scn-cmo-008-duplicate-brokerage": "Duplicate billing is a listed payment leakage category.",
    "scn-cmo-012-engineering-as-gmp": "Wrong rate is a listed payment leakage category.",
}

APPROVE_GAP = (
    "No contracted rate for this line is visible in the retrieved sections, so the billed "
    "amount is unverified."
)
DEFAULT_UNCERTAINTY = (
    "The evidence direction relies on the invoice line description; the contents of the "
    "listed support references are not visible."
)

# Supports are historical labels; support_review_flag marks rows whose recover
# direction rests only on the invoice description while analogous rows use review.
SPECS: dict[str, dict[str, Any]] = {
    "scn-cmo-001-packaging-authorization": {
        "claim": (
            "Blister packaging is billable only when the purchase order or written change "
            "authorization identifies the packaging format."
        ),
        "gap": (
            "The contents of packaging order PKG-AR-BLISTER-1026 are not visible, so a purchase "
            "order or change authorization identifying blister packaging is unverified."
        ),
        "summary": (
            "Section 3.2 conditions blister packaging charges on a purchase order or written "
            "change authorization naming the format, and no such authorization is visible, so "
            "the evidence does not show the surcharge as billable."
        ),
        "uncertainty": (
            "The invoice lists packaging order PKG-AR-BLISTER-1026, whose contents are not "
            "visible; the historical recover direction needs review if that order authorizes "
            "blister packaging."
        ),
        "flag": True,
        "approve": {
            "description": "Blister packaging surcharge for ALLER-20 monthly production",
            "reference": "PKG-SYN-001",
            "support_references": ["Purchase order PO-SYN-AR-001"],
            "facts": [
                "Purchase order PO-SYN-AR-001 identifies blister packaging as the packaging "
                "format for ALLER-20 monthly production."
            ],
            "condition": (
                "Purchase order PO-SYN-AR-001 identifies blister packaging, meeting the "
                "packaging authorization condition"
            ),
        },
    },
    "scn-cmo-002-pending-batch": {
        "claim": (
            "Batches with pending release status may not be invoiced for batch manufacturing, "
            "QA release, or line clearance fees."
        ),
        "gap": (
            "Batch release certificate NFF-REL-1026 contents are not visible, so the release "
            "status of lot NS-1026-02 beyond the pending description is unverified."
        ),
        "summary": (
            "The quality agreement bars invoicing pending batches for manufacturing, QA release, "
            "or line clearance fees, and the line describes lot NS-1026-02 as pending QA, so the "
            "charge is not supported as billed."
        ),
        "uncertainty": (
            "Pending status comes from the line description; the release certificate contents "
            "are not visible."
        ),
        "flag": True,
        "missing": {
            "description": "Batch manufacturing and QA release fee for lot NS-SYN-002",
            "facts": ["The release status of lot NS-SYN-002 was not supplied."],
            "gap": "The release status of lot NS-SYN-002 was not supplied.",
            "rule": (
                "Pending batches may not be invoiced for manufacturing or QA release fees"
            ),
        },
    },
    "scn-cmo-003-premium-logistics": {
        "claim": (
            "Premium freight is billable only when the purchase order identifies the shipment "
            "ID and the approved lane exception."
        ),
        "gap": (
            "No purchase order identifying shipment SHIP-HP-1026-ALT and an approved lane "
            "exception was supplied."
        ),
        "summary": (
            "Premium freight requires a purchase order naming the shipment ID and approved lane "
            "exception; the line states no lane exception approval and none is visible, so "
            "billability depends on facts needing controller verification."
        ),
        "approve": {
            "description": "Premium freight surcharge for EU lane shipment SHIP-HP-1026-SYN",
            "reference": "SHIP-HP-1026-SYN",
            "support_references": ["Purchase order PO-SYN-HP-003"],
            "facts": [
                "Purchase order PO-SYN-HP-003 identifies shipment SHIP-HP-1026-SYN and approved "
                "lane exception LX-SYN-003."
            ],
            "condition": (
                "Purchase order PO-SYN-HP-003 identifies the shipment ID and an approved lane "
                "exception, meeting the logistics charge condition"
            ),
        },
        "missing": {
            "description": "Premium freight surcharge for EU lane shipment SHIP-HP-SYN-003",
            "facts": ["No purchase order for shipment SHIP-HP-SYN-003 was supplied."],
            "gap": (
                "A purchase order identifying shipment SHIP-HP-SYN-003 and an approved lane "
                "exception was not supplied."
            ),
            "rule": (
                "Premium freight requires a purchase order naming the shipment ID and lane "
                "exception"
            ),
        },
    },
    "scn-cmo-004-yield-true-up": {
        "claim": "Quarterly yield true-ups must use actual released lot yield, not forecast yield.",
        "gap": (
            "Lot yield worksheet YLD-MAW-1026 contents are not visible, so the actual released "
            "lot yield for the true-up is unknown."
        ),
        "summary": (
            "The supply agreement requires yield true-ups to use actual released lot yield; the "
            "line states a forecast basis and actual yield is not visible, so the variance needs "
            "controller verification."
        ),
        "missing": {
            "description": "Quarterly yield true-up adjustment",
            "facts": ["The yield basis used for the true-up was not supplied."],
            "gap": (
                "The yield basis and actual released lot yield for the true-up were not "
                "supplied."
            ),
            "rule": "Yield true-ups must use actual released lot yield",
        },
    },
    "scn-cmo-005-early-stability-pull": {
        "claim": (
            "Stability pulls are billable only within the study schedule window or a "
            "sponsor-approved deviation window, and early pulls are not separately billable."
        ),
        "gap": (
            "Stability pull schedule STAB-CGL-Q4 contents are not visible, so the schedule "
            "window and any sponsor-approved deviation window are unverified."
        ),
        "summary": (
            "Stability pulls are billable only within the schedule or an approved deviation "
            "window, and the line describes a pull before the approved window, so the evidence "
            "indicates the charge is not separately billable."
        ),
        "uncertainty": (
            "Early timing comes from the line description; the schedule contents are not "
            "visible."
        ),
        "flag": True,
        "approve": {
            "description": "Stability pull completed within the approved study schedule window",
            "reference": "STAB-SYN-005",
            "support_references": ["Stability pull schedule STAB-SYN-005"],
            "facts": [
                "The stability pull was completed on 2026-10-14, inside the 2026-10-10 to "
                "2026-10-20 window stated in schedule STAB-SYN-005."
            ],
            "condition": (
                "The stated pull date falls inside the stated schedule window, meeting the "
                "stability window condition"
            ),
        },
        "missing": {
            "description": "Stability pull charge for study STAB-SYN-005",
            "facts": ["The pull date and the approved schedule window were not supplied."],
            "gap": "The pull date and the approved schedule window were not supplied.",
            "rule": "Stability pulls are billable only within the schedule or deviation window",
        },
    },
    "scn-cmo-006-same-family-changeover": {
        "claim": (
            "Changeover between ALLER-CAP capsule strengths in the same campaign week is "
            "included in the unit production price."
        ),
        "gap": (
            "Campaign worksheet SDM-CW-1026 contents are not visible, so the campaign week of "
            "both ALLER-CAP strength runs is unverified."
        ),
        "summary": (
            "Same-family ALLER-CAP strength changeovers within one campaign week are included in "
            "the unit price, and the line describes that changeover, so the separate fee is not "
            "supported as billed."
        ),
        "approve": {
            "description": "Changeover fee between ALLER-CAP and ALLER-TAB product families",
            "reference": "CHG-SYN-006",
            "support_references": ["Campaign worksheet CW-SYN-006"],
            "facts": [
                "The changeover moved production from the ALLER-CAP capsule family to the "
                "ALLER-TAB tablet family, a different product family."
            ],
            "condition": (
                "The stated changeover is between different product families, meeting the "
                "changeover billability condition"
            ),
        },
        "missing": {
            "description": "Changeover fee between two ALLER-CAP products",
            "facts": [
                "Whether the changeover crossed product families or active ingredients, and its "
                "campaign week, was not supplied."
            ],
            "gap": (
                "The product families, active ingredients, and campaign week of the changeover "
                "were not supplied."
            ),
            "rule": "Changeover is billable only between product families or active ingredients",
        },
    },
    "scn-cmo-007-storage-after-close": {
        "claim": (
            "Storage after study close is billable only with a written sponsor extension "
            "identifying the protocol and storage end date."
        ),
        "gap": (
            "No written sponsor extension identifying protocol OCS-244 and a storage end date "
            "was supplied, and the study close date is not visible."
        ),
        "summary": (
            "Storage after study close needs a written sponsor extension naming the protocol and "
            "end date; none is visible, so the post-close storage days depend on facts needing "
            "controller verification."
        ),
        "approve": {
            "description": (
                "Temperature-controlled storage days after study close under a sponsor extension"
            ),
            "reference": "STOR-SYN-007",
            "support_references": ["Sponsor extension EXT-SYN-007"],
            "facts": [
                "Written sponsor extension EXT-SYN-007 identifies protocol OCS-244 and a storage "
                "end date of 2026-11-30; billed storage days end before that date."
            ],
            "condition": (
                "Written extension EXT-SYN-007 identifies the protocol and storage end date, "
                "meeting the post-close storage condition"
            ),
        },
        "missing": {
            "description": "Temperature-controlled storage days for protocol OCS-244",
            "facts": ["The study close date and any written sponsor extension were not supplied."],
            "gap": (
                "The study close date and any written sponsor extension naming the protocol and "
                "storage end date were not supplied."
            ),
            "rule": "Storage after study close needs a written sponsor extension",
        },
    },
    "scn-cmo-008-duplicate-brokerage": {
        "claim": (
            "Customs brokerage is billable once per shipment and may not be billed on both "
            "master and child records for the same customs entry."
        ),
        "gap": (
            "The customs entry records are not visible, so whether the master and child "
            "brokerage charges share one customs entry is unverified."
        ),
        "summary": (
            "Brokerage is billable once per shipment, and the line describes brokerage on both "
            "master and child records, so the evidence indicates duplicate billing if both "
            "records share one customs entry."
        ),
        "approve": {
            "description": (
                "Customs brokerage for a single shipment with Valence as broker of record"
            ),
            "reference": "CUST-SYN-008",
            "support_references": ["Customs entry CE-SYN-008"],
            "facts": [
                "Valence acted as broker of record for customs entry CE-SYN-008, and brokerage "
                "is billed once, on the master shipment record only."
            ],
            "condition": (
                "The stated facts show one brokerage charge per shipment with Valence as broker "
                "of record, meeting the brokerage condition"
            ),
        },
        "missing": {
            "description": "Customs brokerage for shipment VCL-SYN-008",
            "facts": [
                "Whether another brokerage charge exists for the same customs entry was not "
                "supplied."
            ],
            "gap": (
                "The customs entry and whether brokerage was billed on another record for that "
                "entry were not supplied."
            ),
            "rule": "Brokerage is billable once per shipment and customs entry",
        },
    },
    "scn-cmo-009-supplier-caused-investigation": {
        "claim": (
            "Investigation charges are not billable when contamination is caused by BluePeak "
            "process error, and sponsor-material causes require sponsor quality approval."
        ),
        "gap": (
            "Deviation cost packet DEV-BPB-1026 contents are not visible, so the root cause of "
            "the contamination is unverified."
        ),
        "summary": (
            "BluePeak-caused contamination costs are not billable, the line cites a "
            "supplier-caused deviation, and quality status conflicts are listed escalation "
            "triggers, so the evidence routes this line to escalation."
        ),
        "missing": {
            "description": "Contamination investigation charge for deviation DEV-SYN-009",
            "facts": [
                "The root cause of the deviation and any sponsor quality approval were not "
                "supplied."
            ],
            "gap": "The deviation root cause and any sponsor quality approval were not supplied.",
            "rule": "Investigation charges depend on the contamination root cause",
        },
    },
    "scn-cmo-010-scrap-allowance": {
        "claim": (
            "Component scrap above 1.5% is billable only when the scrap record shows a "
            "sponsor-caused defect or sponsor-approved process change."
        ),
        "gap": (
            "Scrap record and ECO packet ECO-KDA-771 contents are not visible, so a "
            "sponsor-caused defect or sponsor-approved process change is unverified."
        ),
        "summary": (
            "Scrap above 1.5% needs a sponsor-caused defect or approved process change in the "
            "scrap record; that record is not visible, so the excess scrap charge depends on "
            "facts needing controller verification."
        ),
        "approve": {
            "description": "Component scrap above 1.5% with a sponsor-caused component defect",
            "reference": "SCRAP-SYN-010",
            "support_references": ["Scrap record SCR-SYN-010"],
            "facts": [
                "Scrap record SCR-SYN-010 attributes the excess scrap to a sponsor-caused "
                "component defect."
            ],
            "condition": (
                "Scrap record SCR-SYN-010 attributes the excess scrap to a sponsor-caused "
                "defect, meeting the scrap allowance condition"
            ),
        },
        "missing": {
            "description": "Component scrap charge above the 1.5% allowance",
            "facts": ["The scrap record and the cause of the excess scrap were not supplied."],
            "gap": "The scrap record and the cause of the excess scrap were not supplied.",
            "rule": "Scrap above 1.5% needs a sponsor-caused defect or approved process change",
        },
    },
    "scn-cmo-011-release-packet-before-qa": {
        "claim": (
            "Release packet fees may be invoiced only after the packet is complete and sponsor "
            "QA accepts the sterilization documentation."
        ),
        "gap": (
            "Sponsor QA acceptance of release packet RP-LSS-1026 is not shown in the supplied "
            "evidence."
        ),
        "summary": (
            "Release packet fees are invoiceable only after sponsor QA accepts the sterilization "
            "documentation, and the line states billing preceded that acceptance, so the fee is "
            "not supported as billed."
        ),
        "uncertainty": "QA acceptance timing comes from the line description only.",
        "flag": True,
        "approve": {
            "description": "Release packet fee after sponsor QA acceptance",
            "reference": "REL-SYN-011",
            "support_references": ["Release packet RP-SYN-011"],
            "facts": [
                "Release packet RP-SYN-011 is complete, and sponsor QA accepted the "
                "sterilization documentation on 2026-10-20."
            ],
            "condition": (
                "The stated facts show a complete packet with sponsor QA acceptance, meeting the "
                "release packet condition"
            ),
        },
        "missing": {
            "description": "Release packet fee for packet RP-SYN-011",
            "facts": ["The packet completion status and sponsor QA acceptance were not supplied."],
            "gap": "The packet completion status and sponsor QA acceptance were not supplied.",
            "rule": "Release packet fees need a complete packet and sponsor QA acceptance",
        },
    },
    "scn-cmo-012-engineering-as-gmp": {
        "claim": (
            "Engineering batches may be invoiced at the GMP validation rate only when the "
            "approved protocol identifies GMP validation and sponsor QA accepts the executed "
            "record."
        ),
        "gap": (
            "Protocol PPD-PROT-1026 and sponsor QA acceptance of batch report EBR-PPD-1026 are "
            "not visible, so GMP validation classification is unverified."
        ),
        "summary": (
            "The GMP validation rate applies only when the protocol identifies GMP validation "
            "and sponsor QA accepts the record; neither is visible, so the rate classification "
            "needs controller verification."
        ),
        "approve": {
            "description": "GMP validation batch fee under an approved validation protocol",
            "reference": "VAL-SYN-012",
            "support_references": ["Approved protocol PROT-SYN-012"],
            "facts": [
                "Approved protocol PROT-SYN-012 identifies the batch as a GMP validation batch, "
                "and sponsor QA accepted the executed batch record."
            ],
            "condition": (
                "The approved protocol identifies GMP validation and sponsor QA accepted the "
                "record, meeting the GMP classification condition"
            ),
        },
        "missing": {
            "description": "Batch invoiced at the GMP validation batch rate",
            "facts": [
                "The approved protocol classification and sponsor QA acceptance of the batch "
                "record were not supplied."
            ],
            "gap": (
                "The approved protocol classification and sponsor QA acceptance of the batch "
                "record were not supplied."
            ),
            "rule": "The GMP rate needs protocol classification and sponsor QA acceptance",
        },
    },
    "scn-cmo-013-escalation-cap": {
        "claim": (
            "Material price escalation above 2.5% requires written sponsor procurement lead "
            "approval before shipment."
        ),
        "gap": (
            "No written sponsor procurement lead approval of the escalation dated before "
            "shipment was supplied."
        ),
        "summary": (
            "Escalation above the 2.5% cap requires written procurement lead approval before "
            "shipment, and none is visible, so the excess escalation is not supported as billed."
        ),
        "uncertainty": (
            "The excess-over-cap characterization comes from the line description; the "
            "escalation percentage is not computed from visible records."
        ),
        "flag": True,
    },
    "scn-cmo-014-outdated-forecast": {
        "claim": (
            "Volume true-ups compare forecast to actual released volume for the same month and "
            "SKU, and superseded prior-month forecasts may not be reused."
        ),
        "gap": (
            "True-up worksheet CTU-ARM-1026 and forecast snapshot FS-ARM-1026 contents are not "
            "visible, so the forecast and actual released volumes used are unverified."
        ),
        "summary": (
            "Volume true-ups must use actual released volume and current forecasts; the line "
            "states an outdated forecast basis, so the true-up amount depends on facts needing "
            "controller verification."
        ),
    },
    "scn-cmo-015-unapproved-country": {
        "claim": (
            "Variation submission fees are billable only for countries listed in the approved "
            "regulatory work order."
        ),
        "gap": (
            "Country scope matrix SRR-CSM-1026 contents are not visible, and no sponsor "
            "regulatory approval for the added country before work began was supplied."
        ),
        "summary": (
            "Variation submission fees are billable only for countries in the approved work "
            "order, and the line describes a country not listed, so the fee is not supported as "
            "billed."
        ),
        "uncertainty": (
            "The unlisted-country characterization comes from the line description; the scope "
            "matrix contents are not visible."
        ),
        "flag": True,
    },
}

CHALLENGE_SUMMARIES = {
    "synthetic-challenge:included-quality-documentation": (
        "Standard certificates of analysis are included in unit cost, and the line bills a "
        "standard certificate separately, so the charge is not supported as billed."
    ),
    "synthetic-challenge:rush-authorization-not-provided": (
        "Rush-order fees need a purchase order or written sponsor approval naming the lot, ship "
        "date, and rush service level; none was supplied, so billability needs controller "
        "verification."
    ),
    "synthetic-challenge:regional-volume-tier-matched": (
        "The cited volume tier supports the invoiced USD 0.36 rate for the stated released "
        "volume, and the line can be tied to the price tier section."
    ),
    "synthetic-challenge:capacity-timely-cancellation": (
        "A reservation charge is not billable when the sponsor cancels at least 45 days before "
        "the first run, and the stated cancellation came 50 days before, so the charge is not "
        "supported as billed."
    ),
    "synthetic-challenge:regulatory-filing-not-provided": (
        "Variation milestones are invoiceable only after filing with evidence naming country, "
        "procedure, and submission date; that evidence was not provided, so billability needs "
        "controller verification."
    ),
    "synthetic-challenge:translation-correction-rush-premium": (
        "Rush translation premiums may not apply to sponsor-requested corrections of prior "
        "Signal Ridge errors, and the line bills that premium on such a correction, so it is "
        "not supported as billed."
    ),
}


def build_evidence_only_v3(*, dataset_dir: Path, out_dir: Path) -> dict[str, Any]:
    """Write v3 candidate source splits; refuse to overwrite edited review data."""
    rendered = render_evidence_only_v3(dataset_dir)
    for name, content in rendered.items():
        path = out_dir / name
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise ValueError(f"refusing to overwrite existing evidence-only data: {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    return {
        "out_dir": str(out_dir),
        "version": EVIDENCE_ONLY_VERSION,
        "review_status": REVIEW_STATUS,
        "files": {
            name: hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
            for name in sorted(rendered)
        },
        "manifest": json.loads(rendered["manifest.json"]),
    }


def verify_evidence_only_v3(*, dataset_dir: Path, out_dir: Path) -> list[str]:
    """Return mismatches between committed v3 files and a fresh deterministic rebuild."""
    errors = []
    for name, content in render_evidence_only_v3(dataset_dir).items():
        path = out_dir / name
        if not path.is_file():
            errors.append(f"missing evidence-only file: {path}")
        elif path.read_text(encoding="utf-8") != content:
            errors.append(f"evidence-only file differs from rebuild: {path}")
    return errors


def render_evidence_only_v3(dataset_dir: Path) -> dict[str, str]:
    rendered: dict[str, str] = {}
    manifest: dict[str, Any] = {
        "version": EVIDENCE_ONLY_VERSION,
        "label_source": LABEL_SOURCE,
        "review_status": REVIEW_STATUS,
        "note": (
            "Synthetic evidence-only reference candidates derived from the historical labels. "
            "Not human-reviewed ground truth; supports labels are carried over unchanged."
        ),
        "splits": {},
    }
    recon_4 = _find_section(dataset_dir, RECON_4)
    for split, filename in SOURCE_FILES.items():
        source = dataset_dir / filename
        source_text = source.read_text(encoding="utf-8")
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        source_rows = [json.loads(line) for line in source_text.splitlines() if line.strip()]
        rows = [_transform(row, split, filename, source_sha) for row in source_rows]
        if split in COVERAGE_SPLITS:
            rows.extend(_coverage_rows(rows, recon_4))
        content = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
        rendered[f"{split}.jsonl"] = content
        kinds: dict[str, int] = {}
        for row in rows:
            kind = row["metadata"]["evidence_only_reference"]["coverage_kind"]
            kinds[kind] = kinds.get(kind, 0) + 1
        manifest["splits"][split] = {
            "path": f"{split}.jsonl",
            "rows": len(rows),
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "source_path": filename,
            "source_sha256": source_sha,
            "coverage_kinds": dict(sorted(kinds.items())),
            "support_review_flags": sum(
                row["metadata"]["evidence_only_reference"]["support_review_flag"] for row in rows
            ),
        }
    rendered["manifest.json"] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    return rendered


def _transform(
    row: dict[str, Any], split: str, filename: str, source_sha: str
) -> dict[str, Any]:
    new = copy.deepcopy(row)
    metadata = new["metadata"]
    scenario = metadata["scenario_id"]
    expected = new["expected_output_json"]
    ground_truth = new["ground_truth"]
    if split == "challenge":
        summary = CHALLENGE_SUMMARIES[scenario]
        spec: dict[str, Any] = {
            "uncertainty": (
                "Facts are fictional counterfactuals; the direction follows the stated facts and "
                "the cited clause."
            ),
        }
    else:
        spec = SPECS[scenario]
        summary = spec["summary"]
        for evidence in expected["evidence"]:
            evidence["claim"] = _claim_for(evidence["source_ref"], scenario, spec)
        expected["unsupported"] = [spec["gap"]]
    expected["summary"] = f"{summary} {RESERVED}"
    new["expected"] = {"text": json.dumps(expected, sort_keys=True)}
    historical = {
        "label_source": metadata.get("label_source"),
        "review_status": metadata.get("review_status"),
        "recommended_action": ground_truth.pop("recommended_action", None),
        "decision_state": ground_truth.pop("decision_state", None),
        "issue_category": ground_truth.pop("issue_category", None),
    }
    ground_truth["reference_summary"] = expected["summary"]
    new["messages"] = _with_v3_developer(new["messages"])
    metadata["label_source"] = LABEL_SOURCE
    metadata["review_status"] = REVIEW_STATUS
    metadata["historical_reference"] = {k: v for k, v in historical.items() if v is not None}
    metadata["evidence_only_reference"] = {
        "version": EVIDENCE_ONLY_VERSION,
        "coverage_kind": "label_transform",
        "source_path": f"modules/evals/datasets/contract-policy-expert/{filename}",
        "source_sha256": source_sha,
        "source_row_id": row["id"],
        "derivation": (
            "Claims paraphrase the cited section text; unsupported names evidence not visible "
            "in the prompt; the summary describes the evidence direction without directives; "
            "supports is carried over from the historical label."
        ),
        "uncertainty": spec.get("uncertainty", DEFAULT_UNCERTAINTY),
        "support_review_flag": bool(spec.get("flag", False)),
    }
    return new


def _claim_for(source_ref: str, scenario: str, spec: dict[str, Any]) -> str:
    if "/contracts/" in source_ref:
        return spec["claim"]
    key = source_ref.split("/")[-1]
    if key == "invoice-reconciliation-policy.md#5-payment-leakage-categories":
        return LEAKAGE_CLAIMS[scenario]
    return POLICY_CLAIMS[key]


def _with_v3_developer(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for message in messages:
        if message.get("role") == "developer":
            message = {**message, "content": message["content"] + EVIDENCE_ONLY_SCHEMA_PROMPT}
        result.append(message)
    return result


def _find_section(dataset_dir: Path, suffix: str) -> dict[str, Any]:
    for filename in SOURCE_FILES.values():
        for line in (dataset_dir / filename).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            for section in json.loads(line)["retrieved_context"]["contract_policy_sections"]:
                if section["source_ref"].endswith(suffix):
                    return copy.deepcopy(section)
    raise ValueError(f"no retrieved section ends with {suffix}")


def _coverage_rows(rows: list[dict[str, Any]], recon_4: dict[str, Any]) -> list[dict[str, Any]]:
    bases = [
        row for row in rows if row["metadata"].get("prompt_variant") == "standard-evidence"
    ]
    contract_sections = {
        base["metadata"]["scenario_id"]: next(
            section
            for section in base["retrieved_context"]["contract_policy_sections"]
            if "/contracts/" in section["source_ref"]
        )
        for base in bases
    }
    scenarios = list(contract_sections)
    distractors, approves, missing = [], [], []
    for index, base in enumerate(bases):
        scenario = base["metadata"]["scenario_id"]
        other = scenarios[(index + 1) % len(scenarios)]
        distractors.append(_distractor_row(base, contract_sections[other]))
        spec = SPECS[scenario]
        if "approve" in spec:
            approves.append(
                _synthetic_row(base, spec, spec["approve"], "approve", contract_sections[scenario],
                               recon_4)
            )
        if "missing" in spec:
            missing.append(
                _synthetic_row(base, spec, spec["missing"], "review", contract_sections[scenario],
                               None)
            )
    return distractors + approves + missing


def _distractor_row(base: dict[str, Any], section: dict[str, Any]) -> dict[str, Any]:
    row = copy.deepcopy(base)
    row["id"] = row["id"].rsplit(":", 1)[0] + ":distractor-context"
    row["metadata"]["prompt_variant"] = "distractor-context"
    row["metadata"]["prompt_variant_focus"] = "unrelated retrieved contract section"
    row["retrieved_context"]["contract_policy_sections"].append(copy.deepcopy(section))
    _edit_payload(row, lambda payload: payload["retrieved_context"].append(copy.deepcopy(section)))
    reference = row["metadata"]["evidence_only_reference"]
    reference["coverage_kind"] = "distractor_context"
    reference["derivation"] = (
        f"Copy of {base['id']} with another supplier's contract section "
        f"({section['source_ref'].split('/')[-1]}) appended as an uncited distractor; the "
        "expected answer is unchanged."
    )
    return row


def _synthetic_row(
    base: dict[str, Any],
    spec: dict[str, Any],
    coverage: dict[str, Any],
    support: str,
    contract_section: dict[str, Any],
    approval_section: dict[str, Any] | None,
) -> dict[str, Any]:
    row = copy.deepcopy(base)
    metadata = row["metadata"]
    suffix = "SYNA" if support == "approve" else "SYNG"
    kind = "synthetic-approve" if support == "approve" else "synthetic-missing-evidence"
    invoice_id = f"{metadata['invoice_id']}-{suffix}"
    line_id = f"{metadata['line_id']}-{suffix}"
    scenario = f"{metadata['scenario_id']}:{kind}"
    sections = copy.deepcopy(row["retrieved_context"]["contract_policy_sections"])
    cited = [contract_section]
    if approval_section is not None:
        cited.append(approval_section)
        if all(section["source_ref"] != approval_section["source_ref"] for section in sections):
            sections.append(copy.deepcopy(approval_section))
    else:
        cited.append(
            next(
                section for section in sections
                if section["source_ref"] in row["ground_truth"]["acceptable_citations"]
                and "/contracts/" not in section["source_ref"]
            )
        )

    def edit(payload: dict[str, Any]) -> None:
        payload["invoice"]["invoice_id"] = invoice_id
        payload["invoice"].setdefault("document_metadata", {})["support_references"] = list(
            coverage.get("support_references", [])
        )
        line = payload["line"]
        line.update(
            line_id=line_id,
            description=coverage["description"],
            reference_id=coverage.get("reference", f"REF-{suffix}"),
        )
        for key in ("expected_decision_state", "issue_category", "scenario_id"):
            line.pop(key, None)
        payload.pop("scenario_hint", None)
        payload["hypothetical_facts"] = list(coverage["facts"])
        payload["retrieved_context"] = copy.deepcopy(sections)

    _edit_payload(row, edit)
    if support == "approve":
        claims = [spec["claim"], POLICY_CLAIMS[RECON_4]]
        gap = APPROVE_GAP
        summary = (
            f"{coverage['condition']}, and the line can be tied to that authorized source "
            "document; the billed amount is unverified because no rate is visible."
        )
    else:
        claims = [spec["claim"], _claim_for(cited[1]["source_ref"], metadata["scenario_id"], spec)]
        gap = coverage["gap"]
        summary = (
            f"{coverage['rule']}; the decisive fact was not supplied, so billability depends on "
            "facts needing controller verification."
        )
    expected = row["expected_output_json"]
    expected["invoice_id"] = invoice_id
    expected["correlation"]["waypoint_invoice_id"] = invoice_id
    expected["evidence"] = [
        {
            "claim": claim,
            "supports": support,
            "source_ref": section["source_ref"],
            "classification": section["classification"],
            "confidence": CONFIDENCE,
        }
        for claim, section in zip(claims, cited, strict=True)
    ]
    expected["unsupported"] = [gap]
    expected["summary"] = f"{summary} {RESERVED}"
    row["expected"] = {"text": json.dumps(expected, sort_keys=True)}
    row["ground_truth"] = {
        "acceptable_citations": [section["source_ref"] for section in cited],
        "evidence_refs": [
            {"document": section["document"], "section": section["section"]} for section in cited
        ],
        "expected_supports": support,
        "reference_summary": expected["summary"],
    }
    row["retrieved_context"]["contract_policy_sections"] = sections
    row["id"] = f"ledgerfield:{scenario}:{line_id}:{kind}"
    metadata.update(
        invoice_id=invoice_id,
        line_id=line_id,
        scenario_id=scenario,
        prompt_variant=kind,
        prompt_variant_focus=(
            "supported approval evidence" if support == "approve" else "missing decisive evidence"
        ),
        historical_reference={"derived_from_row_id": base["id"], "historical_label": None},
    )
    metadata["evidence_only_reference"].update(
        coverage_kind=(
            "supported_approval_evidence" if support == "approve" else "missing_evidence"
        ),
        derivation=(
            "Fictional counterfactual built from the scenario's cited contract clause; "
            "hypothetical_facts state the decisive fact "
            + ("as satisfying the clause" if support == "approve" else "as not supplied")
            + f". Supports {support} follows from those stated facts only."
        ),
        uncertainty=(
            "Fictional facts; no historical label exists. The billed rate is not covered by "
            "any retrieved section."
            if support == "approve"
            else "Fictional facts; no historical label exists."
        ),
        support_review_flag=False,
    )
    return row


def _edit_payload(row: dict[str, Any], edit: Any) -> None:
    for message in row["messages"]:
        if message.get("role") == "user":
            payload = json.loads(message["content"])
            edit(payload)
            message["content"] = json.dumps(payload, indent=2)
