# ruff: noqa: E501 -- task-contract and clause text are hashed into the dataset; keep strings unwrapped.
"""Clause families for the contract-evidence-analyst benchmark.

Each family binds one invoice charge to verbatim sections of a real corpus
contract (``modules/corpus/data/contracts/source-markdown``). The billing
conditions, operational-record wording, and gap keywords are rule-derived by
hand from that clause text; the operational records themselves are synthetic.
Every label produced from these families is ``pending_human_review``.

Placeholders in record text are filled per scenario: ``{b}`` batch, ``{l}`` lot,
``{s}`` shipment, ``{po}`` purchase order, ``{r}`` receipt, ``{eco}`` change
order, ``{m}`` service month, ``{d0}``..``{d3}`` ascending dates\nbefore the invoice date ``{dinv}``; ``{d4}`` falls after it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Condition:
    id: str
    record: str
    ok: str
    kw: tuple[tuple[str, ...], ...]
    bad: str | None = None
    assertion: str | None = None


@dataclass(frozen=True)
class Overbill:
    charge: str
    amount: float
    why: str


@dataclass(frozen=True)
class Family:
    id: str
    supplier_id: str
    sections: tuple[str, ...]
    kind: str
    charge: str
    amount: float
    conditions: tuple[Condition, ...]
    distractor_sections: tuple[str, ...] = ()
    overbill: Overbill | None = None
    quality_status: bool = False
    policy_refs: tuple[tuple[str, str], ...] = field(default=())


QA = (("qa", "quality"), ("accept", "disposition", "release", "approv"))
RECEIPT = (("receipt", "received", "receiving"),)
PO_AUTH = (("purchase order", "po", "authoriz", "approv"),)

FAMILIES: tuple[Family, ...] = (
    # ---------------------------------------------------------------- sup-001
    Family(
        id="sup001-batch-release-fee",
        supplier_id="sup-001",
        sections=("2.2", "4"),
        kind="release_gate",
        charge="Batch release administration fee, ALLER-10 batch {b}",
        amount=4800.00,
        quality_status=True,
        policy_refs=(("quality-release-billability-policy", "2"),),
        conditions=(
            Condition(
                "qa",
                "Sponsor QA batch disposition record",
                "Batch {b}: sponsor QA disposition accepted on {d1}.",
                QA,
                bad="Batch {b}: sponsor QA disposition rejected on {d1}.",
                assertion="Batch {b} was accepted by sponsor QA on {d1}.",
            ),
            Condition(
                "batch-record",
                "Batch record completion log",
                "Batch {b}: executed batch record marked complete on {d0}.",
                (("batch record",), ("complet",)),
            ),
            Condition(
                "receipt",
                "Sponsor receipt record",
                "Receipt {r}: released quantity of batch {b} received into sponsor inventory on {d2}.",
                RECEIPT,
            ),
        ),
        distractor_sections=("3.1",),
        overbill=Overbill(
            "Batch release administration fee, ALLER-10 batch {b}",
            5200.00,
            "billed fee exceeds the contract fee of USD 4,800",
        ),
    ),
    Family(
        id="sup001-packaging-format",
        supplier_id="sup-001",
        sections=("3.2",),
        kind="authorization",
        charge="Blister packaging, ALLER-10, 120,000 units, batch {b}",
        amount=18600.00,
        conditions=(
            Condition(
                "packaging-auth",
                "Purchase order packaging line",
                "PO {po} line 3 identifies blister packaging for ALLER-10, 120,000 units.",
                (
                    ("purchase order", "po", "change authorization", "authoriz"),
                    ("packag", "blister", "format"),
                ),
                bad="PO {po} identifies standard bottle packaging only for ALLER-10; no blister format or change authorization is referenced.",
                assertion="Blister format was agreed by phone with the sponsor planner on {d0}.",
            ),
        ),
        distractor_sections=("2.3",),
    ),
    Family(
        id="sup001-moq-shortfall",
        supplier_id="sup-001",
        sections=("2.3",),
        kind="volume_minimum",
        charge="MOQ shortfall, ALLER-20, production month {m}: 140,000 tablets at USD 0.42",
        amount=58800.00,
        conditions=(
            Condition(
                "volume",
                "Sponsor-authorized released volume report",
                "ALLER-20 sponsor-authorized released volume for {m}: 610,000 tablets.",
                (("volume", "quantity"), ("released", "authorized", "report")),
                bad="ALLER-20 sponsor-authorized released volume for {m}: 812,000 tablets.",
            ),
            Condition(
                "forecast",
                "Sponsor forecast change notice",
                "Forecast reduction for ALLER-20 {m} issued 21 calendar days before scheduled production.",
                (("forecast",),),
                bad="Forecast reduction for ALLER-20 {m} issued 52 calendar days before scheduled production.",
                assertion="The sponsor reduced the ALLER-20 forecast late, inside the 30-day window.",
            ),
        ),
        distractor_sections=("3.2",),
    ),
    Family(
        id="sup001-material-escalation",
        supplier_id="sup-001",
        sections=("3.1",),
        kind="pass_through",
        charge="Film-coating material pass-through, batch {b}: 400 kg at USD 23.69/kg (5.3% above prior-year contract unit cost of USD 22.50/kg)",
        amount=9476.00,
        conditions=(
            Condition(
                "consumption",
                "Material consumption record",
                "Batch {b}: actual consumed film-coating material 400 kg.",
                (("consum", "usage", "used"),),
                bad="Batch {b}: actual consumed film-coating material 310 kg.",
            ),
            Condition(
                "escalation-approval",
                "Procurement escalation approval",
                "Written approval from the sponsor procurement lead dated {d0} for a 5.3% annual escalation on film-coating material.",
                (("escalat", "procurement", "price increase"), ("approv", "authoriz", "writ")),
                bad="Procurement log: no written approval for escalation above 3% has been issued for film-coating material this contract year.",
                assertion="The 5.3% escalation reflects market increases accepted by sponsor procurement.",
            ),
        ),
        distractor_sections=("2.2",),
    ),
    # ---------------------------------------------------------------- sup-002
    Family(
        id="sup002-release-testing-fee",
        supplier_id="sup-002",
        sections=("3",),
        kind="release_gate",
        charge="QA release testing fee, ALLER-INJ batch {b}",
        amount=7250.00,
        quality_status=True,
        policy_refs=(("quality-release-billability-policy", "2"),),
        conditions=(
            Condition(
                "release",
                "Sponsor QA release status record",
                "Batch {b}: sponsor QA release status `released` on {d1}.",
                QA,
                bad="Batch {b}: sponsor QA release status `pending` as of {d2}.",
                assertion="Batch {b} has been released by sponsor QA.",
            ),
            Condition(
                "billing-history",
                "Accounts payable billing history",
                "No prior invoice line for QA release testing of batch {b}.",
                (
                    (
                        "billing history",
                        "prior invoice",
                        "previously billed",
                        "duplicate",
                        "already billed",
                        "billed before",
                    ),
                ),
                bad="Invoice {prior_inv} line 2 already billed QA release testing for batch {b} on {d0}.",
            ),
        ),
        distractor_sections=("1",),
        overbill=Overbill(
            "QA release testing fee, ALLER-INJ batch {b}",
            8150.00,
            "billed fee exceeds the contract fee of USD 7,250 per released batch",
        ),
    ),
    Family(
        id="sup002-rework-labor",
        supplier_id="sup-002",
        sections=("2.2",),
        kind="authorization",
        charge="Approved rework labor, rejected ALLER-INJ batch {b}, 64 hours",
        amount=11520.00,
        conditions=(
            Condition(
                "rework-auth",
                "Sponsor quality lead rework authorization",
                "Written rework authorization for batch {b} signed by the sponsor quality lead on {d0}; rework started {d1}.",
                (("rework",), ("authoriz", "approv")),
                bad="Written rework authorization for batch {b} signed by the sponsor quality lead on {d2}; rework started {d1}.",
                assertion="The sponsor quality lead verbally approved rework of batch {b} before work began.",
            ),
            Condition(
                "labor-log",
                "Rework labor log",
                "Batch {b} rework labor log: 64 hours recorded between {d1} and {d2}.",
                (("labor", "hours", "timesheet"),),
                bad="Batch {b} rework labor log: 38 hours recorded between {d1} and {d2}.",
            ),
        ),
        distractor_sections=("3",),
    ),
    Family(
        id="sup002-deviation-investigation",
        supplier_id="sup-002",
        sections=("4",),
        kind="deviation",
        charge="Deviation investigation, DEV-{l}, ALLER-INJ batch {b}",
        amount=9400.00,
        quality_status=True,
        conditions=(
            Condition(
                "deviation-record",
                "Deviation record",
                "DEV-{l} for batch {b}: root cause assigned to sponsor-supplied stopper lot variability.",
                (("deviation",), ("record", "root cause", "report")),
                bad="DEV-{l} for batch {b}: root cause assigned to Northstar line-setup process error.",
            ),
            Condition(
                "quality-approval",
                "Sponsor quality approval of investigation charge",
                "Sponsor quality approval for DEV-{l} investigation charges dated {d1}.",
                (("quality",), ("approv", "authoriz")),
                assertion="Sponsor quality has approved the DEV-{l} investigation charge.",
            ),
        ),
        distractor_sections=("3",),
    ),
    # ---------------------------------------------------------------- sup-003
    Family(
        id="sup003-relabeling",
        supplier_id="sup-003",
        sections=("2",),
        kind="authorization",
        charge="Relabeling for Spanish market, ALLER-20 EU carton, label version 4.2",
        amount=14300.00,
        conditions=(
            Condition(
                "label-auth",
                "Sponsor label change authorization",
                "Label change authorization LCA-{l} identifies SKU ALLER-20 EU carton, market Spain, effective label version 4.2.",
                (("label",), ("authoriz", "approv", "change")),
                bad="Label change authorization LCA-{l} identifies SKU ALLER-10 EU carton, market Spain, effective label version 4.2.",
                assertion="The sponsor artwork team confirmed the Spanish relabel for ALLER-20.",
            ),
        ),
        distractor_sections=("3",),
    ),
    Family(
        id="sup003-serialized-units",
        supplier_id="sup-003",
        sections=("3",),
        kind="quantity_match",
        charge="Serialized-unit fee, shipment {s}: 48,000 units at USD 0.11",
        amount=5280.00,
        conditions=(
            Condition(
                "commissioned",
                "Serial number commissioning report",
                "Shipment {s}: 48,000 serial numbers commissioned.",
                (("serial", "commission"),),
            ),
            Condition(
                "receipt",
                "Sponsor receipt record",
                "Receipt {r}: 48,000 serialized units from shipment {s} received.",
                RECEIPT,
                bad="Receipt {r}: 45,600 serialized units from shipment {s} received.",
            ),
        ),
        distractor_sections=("4",),
    ),
    Family(
        id="sup003-premium-freight",
        supplier_id="sup-003",
        sections=("4",),
        kind="logistics_exception",
        charge="Premium freight surcharge, shipment {s}",
        amount=3900.00,
        conditions=(
            Condition(
                "lane-exception",
                "Purchase order lane exception",
                "PO {po} identifies shipment {s} with an approved premium-freight lane exception.",
                (
                    ("purchase order", "po", "lane", "exception"),
                    ("approv", "identif", "exception", "authoriz"),
                ),
                bad="PO {po} covers shipment {s} on the standard EU distribution lane; no lane exception is listed.",
                assertion="Premium freight for shipment {s} was requested by the sponsor distribution team.",
            ),
        ),
        distractor_sections=("2",),
    ),
    # ---------------------------------------------------------------- sup-004
    Family(
        id="sup004-expedited-release",
        supplier_id="sup-004",
        sections=("5",),
        kind="service_premium",
        charge="Expedited release fee, AUR-API-7 lot {l}",
        amount=12000.00,
        conditions=(
            Condition(
                "expedite-request",
                "Sponsor written expedite request",
                "Sponsor email dated {d0} requests expedited release of lot {l}.",
                (("expedit", "rush"), ("request", "writ", "approv")),
                assertion="The sponsor asked for lot {l} to be expedited.",
            ),
            Condition(
                "coa-timing",
                "Certificate of analysis delivery record",
                "CoA for lot {l} delivered {d1}, eight business days before the standard release date.",
                (("certificate", "coa"),),
                bad="CoA for lot {l} delivered {d1}, two business days before the standard release date.",
            ),
        ),
        distractor_sections=("4",),
        overbill=Overbill(
            "Expedited release fee, AUR-API-7 lot {l}",
            15000.00,
            "billed fee exceeds the contract expedited release fee of USD 12,000",
        ),
    ),
    Family(
        id="sup004-yield-true-up",
        supplier_id="sup-004",
        sections=("3",),
        kind="true_up",
        charge="Quarterly yield true-up, AUR-API-7, Q3: 1,150 g at USD 184.00",
        amount=211600.00,
        conditions=(
            Condition(
                "released-yield",
                "Certificate of analysis released yield summary",
                "Q3 lots: actual released yield 1,150 g per certificates of analysis and sponsor receipt.",
                (("yield",), ("released", "actual", "certificate", "coa")),
                bad="Q3 lots: actual released yield 980 g per certificates of analysis; supplier worksheet uses forecast yield 1,150 g.",
            ),
        ),
        distractor_sections=("5",),
    ),
    Family(
        id="sup004-raw-material-escalation",
        supplier_id="sup-004",
        sections=("4",),
        kind="pass_through",
        charge="Raw material pass-through, intermediate RM-7: 60 kg at USD 1,092/kg (5% above approved unit cost of USD 1,040/kg)",
        amount=65520.00,
        conditions=(
            Condition(
                "consumption",
                "Material consumption detail",
                "Lot {l}: actual consumed RM-7 quantity 60 kg.",
                (("consum", "usage", "used"),),
            ),
            Condition(
                "escalation-approval",
                "Procurement escalation approval",
                "Written procurement approval dated {d0} identifies RM-7, Meridian API Works, effective {d0}, for a 5% escalation.",
                (("escalat", "procurement"), ("approv", "authoriz", "writ")),
                bad="Procurement approval dated {d0} covers RM-4 only; no approval identifies RM-7.",
                assertion="Procurement agreed to the RM-7 increase in the quarterly business review.",
            ),
        ),
        distractor_sections=("5",),
    ),
    # ---------------------------------------------------------------- sup-005
    Family(
        id="sup005-release-testing",
        supplier_id="sup-005",
        sections=("2",),
        kind="release_gate",
        charge="Release testing package, ALLER batch {b}",
        amount=6400.00,
        conditions=(
            Condition(
                "protocol",
                "Approved testing protocol record",
                "Protocol TP-{l} assigned to batch {b} approved on {d0}.",
                (("protocol",), ("approv", "assign")),
                assertion="Testing protocol TP-{l} is approved.",
            ),
            Condition(
                "sample-receipt",
                "Sample receipt log",
                "Crescent sample receipt log: batch {b} samples logged on {d1}.",
                (("sample",), ("receipt", "log", "received")),
            ),
            Condition(
                "billing-history",
                "Accounts payable billing history",
                "No prior release testing package invoiced for batch {b}.",
                (
                    (
                        "billing history",
                        "prior invoice",
                        "previously billed",
                        "duplicate",
                        "already billed",
                        "billed before",
                    ),
                ),
                bad="Invoice {prior_inv} already billed a release testing package for batch {b}; no supplemental testing approval on file.",
            ),
        ),
        distractor_sections=("3",),
    ),
    Family(
        id="sup005-stability-pull",
        supplier_id="sup-005",
        sections=("3",),
        kind="schedule_window",
        charge="Stability pull, study STB-{l}, 12-month time point",
        amount=2100.00,
        conditions=(
            Condition(
                "pull-window",
                "Stability study schedule and pull record",
                "STB-{l} 12-month pull completed {d1}; schedule window {d0} to {d2}.",
                (("pull", "stability", "schedule", "window"),),
                bad="STB-{l} 12-month pull completed {d3}; schedule window {d0} to {d2}; no deviation window approved.",
                assertion="The 12-month pull for STB-{l} was completed on schedule.",
            ),
        ),
        distractor_sections=("5",),
    ),
    Family(
        id="sup005-method-validation",
        supplier_id="sup-005",
        sections=("4",),
        kind="milestone",
        charge="Method validation milestone, assay MV-{l}",
        amount=22500.00,
        conditions=(
            Condition(
                "protocol-acceptance",
                "Validation protocol acceptance",
                "Sponsor accepted validation protocol deliverable MV-{l}-P on {d0}.",
                (("protocol",), ("accept", "approv")),
                assertion="The MV-{l} validation protocol was accepted by the sponsor.",
            ),
            Condition(
                "report-acceptance",
                "Final validation report acceptance",
                "Sponsor accepted final validation report MV-{l}-R on {d2}.",
                (("report",), ("accept", "approv", "final")),
                bad="Final validation report MV-{l}-R status: draft under sponsor review as of {d2}.",
                assertion="The final MV-{l} report has been delivered and accepted.",
            ),
        ),
        distractor_sections=("3",),
    ),
    Family(
        id="sup005-duplicate-certificate",
        supplier_id="sup-005",
        sections=("5",),
        kind="included_service",
        charge="Duplicate certificate of analysis, batch {b}",
        amount=450.00,
        conditions=(
            Condition(
                "sponsor-request",
                "Sponsor reissue request",
                "Sponsor request dated {d2} for a duplicate CoA for batch {b}; final CoA was issued {d1}.",
                (("request",), ("sponsor", "duplicate", "reissue")),
                bad="Duplicate CoA for batch {b} generated by Crescent on {d1} at final issuance; no sponsor request on file.",
                assertion="The duplicate CoA was needed for the sponsor's records.",
            ),
        ),
        distractor_sections=("2",),
    ),
    # ---------------------------------------------------------------- sup-006
    Family(
        id="sup006-changeover",
        supplier_id="sup-006",
        sections=("3",),
        kind="included_service",
        charge="Product changeover, campaign CMP-{l}",
        amount=6800.00,
        conditions=(
            Condition(
                "changeover-log",
                "Changeover log",
                "Campaign CMP-{l}: changeover from ALLER-CAP 50 mg to a different product family (non-ALLER placebo capsule) on {d1}.",
                (("changeover", "change over"),),
                bad="Campaign CMP-{l}: changeover from ALLER-CAP 25 mg to ALLER-CAP 50 mg within the same campaign week on {d1}.",
                assertion="The changeover was required because of a product family change.",
            ),
        ),
        distractor_sections=("4",),
    ),
    Family(
        id="sup006-moq-aggregate",
        supplier_id="sup-006",
        sections=("2",),
        kind="volume_minimum",
        charge="MOQ shortfall, ALLER-CAP 25 mg, {m}: 120,000 capsules at USD 0.31",
        amount=37200.00,
        conditions=(
            Condition(
                "sku-volume",
                "Released volume by SKU",
                "ALLER-CAP 25 mg released in {m}: 380,000 capsules.",
                (("volume", "quantity", "released"), ("sku", "25 mg", "capsule")),
            ),
            Condition(
                "family-volume",
                "Aggregate family released volume",
                "ALLER-CAP family (25 mg + 50 mg) released in {m}: 760,000 capsules.",
                (("aggregate", "family", "combined", "total"),),
                bad="ALLER-CAP family (25 mg + 50 mg) released in {m}: 1,040,000 capsules.",
            ),
        ),
        distractor_sections=("3",),
    ),
    Family(
        id="sup006-cleaning-validation",
        supplier_id="sup-006",
        sections=("4",),
        kind="authorization",
        charge="Cleaning validation, protocol CV-{l}",
        amount=15800.00,
        conditions=(
            Condition(
                "cv-protocol",
                "Approved cleaning validation protocol",
                "Cleaning validation protocol CV-{l} approved by the sponsor on {d0}.",
                (("cleaning",), ("protocol", "validation"), ("approv",)),
                assertion="Cleaning validation protocol CV-{l} is approved.",
            ),
            Condition(
                "work-log",
                "Cleaning work log",
                "Work log: CV-{l} protocol-specific swab and rinse validation runs on {d1}, outside routine campaign cleaning.",
                (("work log", "cleaning log", "activity"),),
                bad="Work log: end-of-campaign routine cleaning on {d1}; no protocol-specific validation runs recorded.",
            ),
        ),
        distractor_sections=("3",),
    ),
    # ---------------------------------------------------------------- sup-007
    Family(
        id="sup007-storage-extension",
        supplier_id="sup-007",
        sections=("4",),
        kind="time_window",
        charge="Temperature-controlled storage after study close, protocol ALR-201, 12 pallets x 30 days",
        amount=5400.00,
        conditions=(
            Condition(
                "extension",
                "Sponsor written storage extension",
                "Sponsor written extension dated {d0} for protocol ALR-201, storage end date {d3}.",
                (("extension",),),
                bad="Sponsor written extension dated {d0} for protocol ALR-118 only; no extension for ALR-201.",
                assertion="The sponsor clinical team asked us to keep ALR-201 stock until further notice.",
            ),
            Condition(
                "occupancy",
                "Pallet occupancy log",
                "ALR-201: 12 pallets occupied for 30 days after the {d1} study close date.",
                (("pallet", "occupancy", "occupied"),),
            ),
        ),
        distractor_sections=("3",),
    ),
    Family(
        id="sup007-comparator-pass-through",
        supplier_id="sup-007",
        sections=("3",),
        kind="pass_through",
        charge="Comparator pass-through, lot {l}: acquisition cost USD 40,000 plus 2% handling",
        amount=40800.00,
        conditions=(
            Condition(
                "supplier-receipt",
                "Comparator supplier receipt",
                "Comparator supplier receipt for lot {l}: acquisition cost USD 40,000, quantity 800 packs.",
                (("receipt", "acquisition", "invoice from"),),
                bad="Comparator supplier receipt for lot {l}: acquisition cost USD 36,500, quantity 800 packs.",
            ),
            Condition(
                "study-auth",
                "Study authorization",
                "Study authorization SA-{l} for protocol ALR-201 covers comparator lot {l}, 800 packs.",
                (("study",), ("authoriz",)),
                assertion="Comparator sourcing for lot {l} was authorized for the study.",
            ),
        ),
        distractor_sections=("4",),
    ),
    Family(
        id="sup007-milestone",
        supplier_id="sup-007",
        sections=("5",),
        kind="milestone",
        charge="Study milestone: first-patient shipment readiness, protocol ALR-201",
        amount=18000.00,
        conditions=(
            Condition(
                "deliverable-approval",
                "Sponsor deliverable approval",
                "Sponsor approved first-patient shipment readiness deliverable for ALR-201 on {d1}.",
                (("approv", "accept"), ("deliverable", "readiness", "milestone")),
                bad="Sponsor approval of first-patient shipment readiness for ALR-201 dated {d4}; this invoice is dated {dinv}.",
                assertion="First-patient shipment readiness was achieved for ALR-201.",
            ),
        ),
        distractor_sections=("2",),
    ),
    # ---------------------------------------------------------------- sup-008
    Family(
        id="sup008-route-exception",
        supplier_id="sup-008",
        sections=("2",),
        kind="logistics_exception",
        charge="Alternate routing surcharge, shipment {s}",
        amount=2750.00,
        conditions=(
            Condition(
                "route-approval",
                "Sponsor logistics route exception approval",
                "Sponsor logistics lead approved route exception for shipment {s} on {d0}; pickup {d1}.",
                (("route", "routing", "exception"), ("approv", "authoriz")),
                bad="Sponsor logistics lead approved route exception for shipment {s} on {d2}; pickup {d1}.",
                assertion="The alternate route for shipment {s} was cleared with sponsor logistics.",
            ),
        ),
        distractor_sections=("4",),
    ),
    Family(
        id="sup008-excursion-handling",
        supplier_id="sup-008",
        sections=("3",),
        kind="event_record",
        charge="Temperature excursion handling fee, shipment {s}",
        amount=1850.00,
        conditions=(
            Condition(
                "excursion-record",
                "Temperature excursion record",
                "Shipment {s}: excursion 2-8 C range exceeded to 11.4 C for 47 minutes on {d1}; investigation disposition: product released after assessment.",
                (("excursion",), ("record", "temperature", "investigation")),
                bad="Shipment {s} monitoring log: alert raised on {d1}; temperature stayed between 2.6 C and 7.8 C (within accepted range).",
                assertion="Shipment {s} had a temperature excursion that required handling.",
            ),
        ),
        distractor_sections=("4",),
    ),
    Family(
        id="sup008-customs-brokerage",
        supplier_id="sup-008",
        sections=("4",),
        kind="duplicate_billing",
        charge="Customs brokerage, child shipment {s}, entry CE-{l}",
        amount=650.00,
        conditions=(
            Condition(
                "broker-of-record",
                "Customs entry record",
                "Customs entry CE-{l}: Valence listed as broker of record.",
                (("customs", "entry", "broker"),),
            ),
            Condition(
                "billing-history",
                "Accounts payable billing history",
                "No brokerage previously billed for customs entry CE-{l} on the master or child shipment.",
                (
                    (
                        "billing history",
                        "prior invoice",
                        "previously billed",
                        "duplicate",
                        "already billed",
                        "billed before",
                    ),
                ),
                bad="Invoice {prior_inv} billed brokerage for customs entry CE-{l} on master shipment M-{s}.",
            ),
        ),
        distractor_sections=("3",),
    ),
    # ---------------------------------------------------------------- sup-009
    Family(
        id="sup009-utilized-capacity",
        supplier_id="sup-009",
        sections=("2",),
        kind="quantity_match",
        charge="Utilized capacity above 12,000 hours, Q3: 640 hours at USD 118",
        amount=75520.00,
        conditions=(
            Condition(
                "run-logs",
                "Manufacturing run logs",
                "Q3 run logs total 12,640 utilized bioreactor hours.",
                (("run log", "run-log", "utilized hours", "hours"),),
                bad="Q3 run logs total 12,310 utilized bioreactor hours.",
            ),
            Condition(
                "batch-records",
                "Batch records index",
                "Q3 batch records BP-{b}-01 to BP-{b}-09 reference the logged runs.",
                (("batch record",),),
            ),
        ),
        distractor_sections=("4",),
        overbill=Overbill(
            "Utilized capacity above 12,000 hours, Q3: 640 hours at USD 132",
            84480.00,
            "billed hourly rate exceeds the contract rate of USD 118",
        ),
    ),
    Family(
        id="sup009-contamination-costs",
        supplier_id="sup-009",
        sections=("4",),
        kind="deviation",
        charge="Contamination investigation and restart, run BP-{b}",
        amount=48000.00,
        quality_status=True,
        conditions=(
            Condition(
                "root-cause",
                "Deviation root-cause record",
                "Deviation DV-{l} for run BP-{b}: root cause sponsor-supplied media lot contamination.",
                (("deviation", "root cause", "contamination"), ("record", "cause", "report")),
                bad="Deviation DV-{l} for run BP-{b}: root cause BluePeak sterile-filter installation error.",
            ),
            Condition(
                "quality-approval",
                "Sponsor quality approval",
                "Sponsor quality approval for DV-{l} investigation and restart charges dated {d2}.",
                (("quality",), ("approv", "authoriz")),
                assertion="Sponsor quality has signed off on the DV-{l} restart charges.",
            ),
        ),
        distractor_sections=("2",),
    ),
    Family(
        id="sup009-true-up",
        supplier_id="sup-009",
        sections=("3", "5"),
        kind="true_up",
        charge="Quarter-end capacity true-up, Q3",
        amount=42000.00,
        conditions=(
            Condition(
                "actual-hours",
                "True-up calculation worksheet",
                "Q3 worksheet uses actual utilized hours from run logs.",
                (("worksheet", "calculation", "actual", "true-up"),),
                bad="Q3 worksheet uses forecast hours (13,000) instead of actual run-log hours.",
            ),
            Condition(
                "prior-credit",
                "Prior credit ledger",
                "Unused capacity credit of USD 18,000 issued in August was applied before the Q3 true-up.",
                (("credit",),),
                bad="Unused capacity credit of USD 18,000 issued in August is not applied in the Q3 true-up.",
            ),
        ),
        distractor_sections=("4",),
    ),
    # ---------------------------------------------------------------- sup-010
    Family(
        id="sup010-assembly-units",
        supplier_id="sup-010",
        sections=("2",),
        kind="quantity_match",
        charge="Auto-injector assembly, build lot {l}: 20,000 accepted units at USD 2.40",
        amount=48000.00,
        conditions=(
            Condition(
                "final-inspection",
                "Final inspection result",
                "Build lot {l}: 20,000 units passed final inspection.",
                (("inspection",),),
                bad="Build lot {l}: 18,700 units passed final inspection; 1,300 units held for material review board disposition.",
            ),
            Condition(
                "receipt",
                "Sponsor receipt record",
                "Receipt {r}: 20,000 accepted units from build lot {l}.",
                RECEIPT,
            ),
        ),
        distractor_sections=("4",),
    ),
    Family(
        id="sup010-eco-labor",
        supplier_id="sup-010",
        sections=("4",),
        kind="authorization",
        charge="Engineering change labor, ECO {eco}, build lot {l}, 52 hours (not to exceed USD 9,000)",
        amount=8320.00,
        conditions=(
            Condition(
                "eco-approval",
                "Sponsor ECO approval",
                "Sponsor approved ECO {eco} on {d0}: affected component spring housing, effective build lot {l}, not-to-exceed USD 9,000.",
                (("eco", "engineering change"), ("approv",)),
                bad="Sponsor approved ECO {eco} on {d2}; Keystone ECO labor recorded {d1}.",
                assertion="ECO {eco} was approved by the sponsor engineering team.",
            ),
            Condition(
                "labor-record",
                "ECO labor record",
                "ECO {eco} labor: 52 hours recorded on {d1} for build lot {l}.",
                (("labor", "hours"),),
            ),
        ),
        distractor_sections=("3",),
    ),
    Family(
        id="sup010-scrap-allowance",
        supplier_id="sup-010",
        sections=("3",),
        kind="allowance",
        charge="Component scrap above 1.5% allowance, campaign {m}: 900 components",
        amount=3150.00,
        conditions=(
            Condition(
                "scrap-record",
                "Scrap record",
                "Campaign {m}: scrap 2.4% of 100,000 sponsor-issued components; scrap record cause: sponsor-caused component defect (supplier lot SC-{l} out of tolerance).",
                (("scrap",),),
                bad="Campaign {m}: scrap 2.4% of 100,000 sponsor-issued components; scrap record cause: Keystone press calibration drift.",
                assertion="Excess scrap in {m} came from defective sponsor components.",
            ),
        ),
        distractor_sections=("4",),
    ),
    # ---------------------------------------------------------------- sup-011
    Family(
        id="sup011-repeat-cycle",
        supplier_id="sup-011",
        sections=("2",),
        kind="repeat_service",
        charge="Repeat sterilization cycle, lot {l}",
        amount=5200.00,
        conditions=(
            Condition(
                "cycle-record",
                "Approved cycle record",
                "Cycle record CR-{b}: repeat cycle for lot {l} on {d1}.",
                (("cycle",), ("record",)),
            ),
            Condition(
                "repeat-cause",
                "Sponsor reprocessing approval",
                "Sponsor-approved reprocessing for lot {l} dated {d0} following a sponsor-requested load change.",
                (("reprocess", "load change", "repeat"), ("approv", "request", "sponsor")),
                bad="Repeat cycle for lot {l} caused by LumaSterile chamber pressure fault; no sponsor approval.",
                assertion="The repeat cycle on lot {l} was due to a sponsor load change.",
            ),
        ),
        distractor_sections=("3",),
    ),
    Family(
        id="sup011-bioburden-retest",
        supplier_id="sup-011",
        sections=("3",),
        kind="repeat_service",
        charge="Bioburden retest, lot {l}",
        amount=1200.00,
        conditions=(
            Condition(
                "retest-trigger",
                "Retest trigger record",
                "Original bioburden result for lot {l} invalidated due to sponsor-provided sample arriving above temperature limit.",
                (("retest", "trigger", "invalid", "sample"),),
                bad="Original bioburden result for lot {l} invalidated due to LumaSterile incubator failure; no sponsor retest approval.",
                assertion="The lot {l} retest was needed because of the sponsor's sample condition.",
            ),
        ),
        distractor_sections=("4",),
    ),
    Family(
        id="sup011-release-packet",
        supplier_id="sup-011",
        sections=("4",),
        kind="release_gate",
        charge="Final release packet fee, lot {l}",
        amount=900.00,
        quality_status=True,
        conditions=(
            Condition(
                "packet-status",
                "Release packet status",
                "Release packet RP-{l}: complete on {d1}.",
                (("packet",),),
                bad="Release packet RP-{l}: draft, missing environmental monitoring attachment.",
            ),
            Condition(
                "qa-acceptance",
                "Sponsor QA acceptance",
                "Sponsor QA accepted sterilization documentation for RP-{l} on {d2}.",
                QA,
                assertion="Sponsor QA has accepted packet RP-{l}.",
            ),
        ),
        distractor_sections=("3",),
    ),
    # ---------------------------------------------------------------- sup-012
    Family(
        id="sup012-deliverable-acceptance",
        supplier_id="sup-012",
        sections=("2",),
        kind="milestone",
        charge="Tech transfer package fee, deliverable TT-3",
        amount=36000.00,
        conditions=(
            Condition(
                "acceptance",
                "Sponsor deliverable acceptance",
                "Sponsor accepted deliverable TT-3 (tech transfer package) on {d1}.",
                (("accept", "approv"), ("deliverable", "tt-3", "package")),
                bad="Deliverable TT-3 status: internal review draft v0.7 with open sponsor comments.",
                assertion="Deliverable TT-3 has been accepted by the sponsor project lead.",
            ),
        ),
        distractor_sections=("3",),
    ),
    Family(
        id="sup012-gmp-batch-classification",
        supplier_id="sup-012",
        sections=("3",),
        kind="classification",
        charge="GMP validation batch, batch {b}",
        amount=125000.00,
        conditions=(
            Condition(
                "protocol-classification",
                "Approved protocol batch classification",
                "Approved protocol PV-{l} identifies batch {b} as a GMP validation batch.",
                (("protocol",), ("gmp", "classif", "identif", "validation batch")),
                bad="Approved protocol PV-{l} identifies batch {b} as an engineering batch.",
            ),
            Condition(
                "qa-acceptance",
                "Sponsor QA executed batch record acceptance",
                "Sponsor QA accepted the executed batch record for batch {b} on {d2}.",
                QA,
                assertion="QA has accepted the batch {b} executed record.",
            ),
        ),
        distractor_sections=("2",),
    ),
    Family(
        id="sup012-pv-milestone",
        supplier_id="sup-012",
        sections=("4",),
        kind="milestone",
        charge="Process validation milestone PV-M2",
        amount=54000.00,
        conditions=(
            Condition(
                "activity-complete",
                "Milestone activity completion record",
                "PV-M2 validation runs completed on {d1}.",
                (("complet",), ("activity", "milestone", "run")),
            ),
            Condition(
                "protocol-approval",
                "Sponsor validation protocol approval",
                "Sponsor approved validation protocol PV-{l} on {d0}.",
                (("protocol", "report"), ("approv", "accept")),
                assertion="The PV-{l} protocol was approved by the sponsor.",
            ),
            Condition(
                "engineering-status",
                "Prerequisite engineering batch status",
                "Engineering batches EB-1 and EB-2 status: complete and reviewed as of {d0}.",
                (("engineering batch", "prerequisite"),),
                bad="Engineering batch EB-2 status: in progress as of {d2}.",
            ),
        ),
        distractor_sections=("3",),
    ),
    # ---------------------------------------------------------------- sup-013
    Family(
        id="sup013-escalation-cap",
        supplier_id="sup-013",
        sections=("2",),
        kind="pass_through",
        charge="Excipient lot {l}: 2,000 kg at USD 8.61/kg (4.0% above the prior contract unit cost of USD 8.28/kg)",
        amount=17220.00,
        conditions=(
            Condition(
                "escalation-approval",
                "Procurement escalation approval",
                "Sponsor procurement lead approved a 4.0% escalation for this excipient in writing on {d0}; shipment {d1}.",
                (("escalat", "procurement", "price"), ("approv", "authoriz", "writ")),
                bad="Sponsor procurement lead approved a 4.0% escalation in writing on {d2}; lot {l} shipped {d1}.",
                assertion="Procurement accepted the 4.0% increase before shipment.",
            ),
        ),
        distractor_sections=("4",),
    ),
    Family(
        id="sup013-rush-order",
        supplier_id="sup-013",
        sections=("4",),
        kind="service_premium",
        charge="Rush-order fee, lot {l}",
        amount=2400.00,
        conditions=(
            Condition(
                "rush-approval",
                "Rush order authorization",
                "PO {po} identifies lot {l}, requested ship date {d1}, rush service level R2.",
                (("rush",), ("purchase order", "po", "approv", "authoriz")),
                bad="Lot {l} rush shipment initiated by Evergreen to recover its own production schedule; PO {po} lists standard service.",
                assertion="The sponsor needed lot {l} urgently.",
            ),
        ),
        distractor_sections=("5",),
    ),
    Family(
        id="sup013-material-surcharge",
        supplier_id="sup-013",
        sections=("3",),
        kind="pass_through",
        charge="Material surcharge, lot {l}: 2,000 kg x USD 0.40/kg",
        amount=800.00,
        conditions=(
            Condition(
                "market-event",
                "Sponsor-approved market event",
                "Sponsor approved raw material market event ME-{l} (lactose supply disruption) on {d0} at USD 0.40/kg.",
                (("market event", "surcharge", "market"), ("approv",)),
                bad="Surcharge basis per Evergreen worksheet: general freight and currency movement; no sponsor-approved market event.",
                assertion="The surcharge reflects a raw material market event.",
            ),
            Condition(
                "lot-quantity",
                "Lot quantity record",
                "Lot {l} affected quantity 2,000 kg per receipt {r}.",
                (("quantity", "lot"),),
            ),
        ),
        distractor_sections=("5",),
    ),
    # ---------------------------------------------------------------- sup-014
    Family(
        id="sup014-capacity-reservation",
        supplier_id="sup-014",
        sections=("3",),
        kind="time_window",
        charge="Regional capacity reservation, {m}",
        amount=64000.00,
        conditions=(
            Condition(
                "active-po",
                "Active purchase order",
                "PO {po} lists {m} as a reserved capacity month.",
                (("purchase order", "po"),),
                bad="PO {po} lists reserved capacity months that do not include {m}.",
            ),
            Condition(
                "cancellation",
                "Reservation cancellation record",
                "No cancellation of the {m} reservation on file.",
                (("cancel",),),
                bad="Sponsor cancelled the {m} reservation 60 calendar days before the first scheduled run.",
            ),
        ),
        distractor_sections=("5",),
    ),
    Family(
        id="sup014-volume-tier",
        supplier_id="sup-014",
        sections=("2",),
        kind="pricing_tier",
        charge="ALLER-10 production, {m}: 1,800,000 released tablets at USD 0.39",
        amount=702000.00,
        conditions=(
            Condition(
                "released-volume",
                "Monthly released volume report",
                "{m} released volume (all SKUs): 1,800,000 tablets.",
                (("volume", "released", "quantity"),),
                bad="{m} released volume (all SKUs): 2,150,000 tablets.",
            ),
        ),
        distractor_sections=("3",),
    ),
    Family(
        id="sup014-regional-packaging",
        supplier_id="sup-014",
        sections=("5",),
        kind="authorization",
        charge="Market-specific carton, ALLER-20 Mexico, batch {b}",
        amount=8700.00,
        conditions=(
            Condition(
                "packaging-approval",
                "Written sponsor packaging approval",
                "Written sponsor approval dated {d0} for ALLER-20 Mexico market-specific carton.",
                (("approv", "authoriz"), ("carton", "packag", "market")),
                assertion="Regional marketing confirmed the Mexico carton.",
            ),
        ),
        distractor_sections=("3",),
    ),
    # ---------------------------------------------------------------- sup-015
    Family(
        id="sup015-country-scope",
        supplier_id="sup-015",
        sections=("2",),
        kind="authorization",
        charge="Site addition packet, Colombia",
        amount=16500.00,
        conditions=(
            Condition(
                "work-order",
                "Approved regulatory work order",
                "Regulatory work order RWO-{l} lists Colombia; approved {d0}; work began {d1}.",
                (("work order",), ("country", "colombia", "list", "approv")),
                bad="Regulatory work order RWO-{l} lists Brazil and Chile; Colombia added by sponsor regulatory approval on {d2}; work began {d1}.",
                assertion="Colombia was always part of the agreed scope.",
            ),
        ),
        distractor_sections=("5",),
    ),
    Family(
        id="sup015-variation-filing",
        supplier_id="sup-015",
        sections=("3",),
        kind="milestone",
        charge="Variation submission milestone, Germany type II variation",
        amount=21000.00,
        conditions=(
            Condition(
                "filing-evidence",
                "Filing evidence",
                "Filing receipt identifies Germany, type II variation procedure, submission date {d1}.",
                (("filing", "filed", "submission"), ("evidence", "receipt", "date", "proof")),
                bad="Submission tracker: Germany type II variation package finalized {d1}; filing scheduled for {d4}.",
                assertion="The Germany variation was submitted on time.",
            ),
        ),
        distractor_sections=("5",),
    ),
    Family(
        id="sup015-rush-translation",
        supplier_id="sup-015",
        sections=("5",),
        kind="service_premium",
        charge="Rush translation premium, document set DS-{l} (German to Spanish)",
        amount=1950.00,
        conditions=(
            Condition(
                "rush-approval",
                "Written sponsor rush approval",
                "Written sponsor approval dated {d0} for rush translation of DS-{l}.",
                (("rush",), ("approv", "authoriz", "writ")),
                assertion="The sponsor asked for DS-{l} to be rushed.",
            ),
            Condition(
                "request-reason",
                "Translation request record",
                "DS-{l} translation request {d0}: new labeling text for Spain launch.",
                (("request", "reason", "correction"),),
                bad="DS-{l} translation request {d0}: sponsor-requested correction of prior Signal Ridge translation errors.",
            ),
        ),
        distractor_sections=("4",),
    ),
)
