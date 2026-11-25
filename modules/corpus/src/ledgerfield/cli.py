"""Command-line entry point for Ledgerfield tooling."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from .agent_surface import artifact_status, generate_all_artifacts
from .db import append_live_invoices, database_url, get_status, seed_database, to_pretty_json
from .docx_docs import generate_docx_documents
from .invoice_docs import generate_invoice_documents
from .paths import repo_root
from .waypoint_seed import generate_waypoint_seed


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ledgerfield",
        description="Generate demo documents and seed Postgres for the Ledgerfield corpus.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=repo_root(),
        help="Repository root. Defaults to the checkout containing this package.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "setup",
        help="Install local runtime assets used by artifact generation, including Playwright Chromium.",
    )

    subparsers.add_parser(
        "generate-all",
        help="Generate all local DOCX, invoice HTML, and invoice PDF artifacts.",
    )

    subparsers.add_parser(
        "doctor",
        help="Report source and generated artifact status for humans and agents.",
    )

    waypoint_seed_parser = subparsers.add_parser(
        "generate-waypoint-seed",
        help="Generate a Waypoint-compatible seed import payload.",
    )
    waypoint_seed_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path. Defaults to data/waypoint/waypoint-seed.json.",
    )

    docs_parser = subparsers.add_parser(
        "generate-invoices",
        help="Generate supplier-specific invoice HTML and PDFs.",
    )
    docs_parser.add_argument(
        "--format",
        choices=["html", "pdf", "both"],
        default="both",
        help="Generated output format. Defaults to both.",
    )
    docs_parser.add_argument(
        "--html-output",
        type=Path,
        default=None,
        help="HTML output folder. Defaults to data/invoices/html.",
    )
    docs_parser.add_argument(
        "--pdf-output",
        type=Path,
        default=None,
        help="PDF output folder. Defaults to data/invoices/pdf.",
    )

    docx_parser = subparsers.add_parser(
        "generate-docx",
        help="Generate contract and policy DOCX files from Markdown sources.",
    )
    docx_parser.add_argument(
        "--contracts-output",
        type=Path,
        default=None,
        help="Contracts DOCX output folder. Defaults to data/contracts/docx.",
    )
    docx_parser.add_argument(
        "--policies-output",
        type=Path,
        default=None,
        help="Policies DOCX output folder. Defaults to data/policies/docx.",
    )

    db_parser = subparsers.add_parser("db", help="Postgres database operations.")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)

    status_parser = db_subparsers.add_parser("status", help="Inspect seed status.")
    status_parser.add_argument("--dsn", default=None, help="Postgres connection string.")

    seed_parser = db_subparsers.add_parser("seed", help="Create schema and seed canonical data.")
    seed_parser.add_argument("--dsn", default=None, help="Postgres connection string.")
    seed_parser.add_argument(
        "--if-needed",
        action="store_true",
        help="Skip base seeding when suppliers and invoices already exist.",
    )
    seed_parser.add_argument(
        "--append-cycles",
        type=int,
        default=0,
        help="Append N live-looking invoice cycles after seeding.",
    )

    append_parser = db_subparsers.add_parser("append", help="Append live-looking invoice records.")
    append_parser.add_argument("--dsn", default=None, help="Postgres connection string.")
    append_parser.add_argument("--cycles", type=int, default=1, help="Number of cycles to append.")

    serve_parser = subparsers.add_parser("serve", help="Run the FastAPI preview/API server.")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to bind.")

    upload_parser = subparsers.add_parser(
        "upload-onelake",
        help="Upload the corpus (Files + Delta tables) into a Waypoint Fabric OneLake lakehouse.",
    )
    upload_parser.add_argument(
        "--workspace",
        default=os.environ.get("ONELAKE_WORKSPACE"),
        help="Fabric workspace name or GUID. Env: ONELAKE_WORKSPACE.",
    )
    upload_parser.add_argument(
        "--lakehouse",
        default=os.environ.get("ONELAKE_LAKEHOUSE"),
        help="Fabric lakehouse name (without the .Lakehouse suffix). Env: ONELAKE_LAKEHOUSE.",
    )
    upload_parser.add_argument(
        "--account-url",
        default=os.environ.get("ONELAKE_ACCOUNT_URL", "https://onelake.dfs.fabric.microsoft.com"),
        help="OneLake DFS endpoint. Env: ONELAKE_ACCOUNT_URL.",
    )
    upload_parser.add_argument(
        "--corpus-prefix",
        default=os.environ.get("ONELAKE_CORPUS_PREFIX", "Files/corpus"),
        help="Lakehouse path prefix for corpus documents. Env: ONELAKE_CORPUS_PREFIX.",
    )
    upload_parser.add_argument(
        "--files-only",
        action="store_true",
        help="Upload only the Files documents, skipping Delta tables.",
    )
    upload_parser.add_argument(
        "--tables-only",
        action="store_true",
        help="Write only the Delta tables, skipping Files documents.",
    )
    upload_parser.add_argument(
        "--skip-generate",
        action="store_true",
        help="Reuse existing generated artifacts instead of regenerating them first.",
    )

    kb_parser = subparsers.add_parser(
        "upload-contracts-kb",
        help="Sync contracts into the knowledge source; --append-only preserves existing evidence.",
    )
    kb_parser.add_argument(
        "--storage-account",
        default=os.environ.get("CONTRACTS_KB_STORAGE_ACCOUNT"),
        help="Storage account backing contracts-ks. Env: CONTRACTS_KB_STORAGE_ACCOUNT.",
    )
    kb_parser.add_argument(
        "--container",
        default=os.environ.get("CONTRACTS_KB_CONTAINER", "knowledge"),
        help="Blob container indexed by contracts-ks. Env: CONTRACTS_KB_CONTAINER.",
    )
    kb_parser.add_argument(
        "--prefix",
        default=os.environ.get("CONTRACTS_KB_PREFIX", "contracts"),
        help="Blob name prefix (virtual folder) for contract documents. Env: CONTRACTS_KB_PREFIX.",
    )
    kb_parser.add_argument(
        "--account-url",
        default=os.environ.get("CONTRACTS_KB_ACCOUNT_URL"),
        help="Full blob endpoint URL, overriding --storage-account. Env: CONTRACTS_KB_ACCOUNT_URL.",
    )
    kb_parser.add_argument(
        "--include-policies",
        action="store_true",
        help="Also upload policy source documents alongside contracts.",
    )
    kb_parser.add_argument(
        "--source-root", type=Path,
        help="Alternate canonical markdown root; requires --append-only.",
    )
    kb_parser.add_argument(
        "--include-operational", action="store_true",
        help="Include operational and invoice markdown, never scenario/answer metadata.",
    )
    kb_parser.add_argument(
        "--append-only", action="store_true",
        help="Never delete or overwrite blobs; identical existing documents are reused.",
    )
    kb_parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Regenerate contract DOCX before upload (markdown source is used as-is otherwise).",
    )
    kb_parser.add_argument(
        "--search-endpoint",
        default=os.environ.get("CONTRACTS_KB_SEARCH_ENDPOINT"),
        help="Azure AI Search endpoint to trigger a reindex. Env: CONTRACTS_KB_SEARCH_ENDPOINT.",
    )
    kb_parser.add_argument(
        "--indexer",
        default=os.environ.get("CONTRACTS_KB_INDEXER", "contracts-ks-indexer"),
        help=(
            "Search indexer name to run after upload (only runs when --search-endpoint "
            "is also set). Defaults to the deterministic contracts-ks-indexer. "
            "Env: CONTRACTS_KB_INDEXER."
        ),
    )
    kb_parser.add_argument(
        "--search-api-version",
        default=os.environ.get("CONTRACTS_KB_SEARCH_API_VERSION", "2024-07-01"),
        help="Azure AI Search REST API version for the indexer run.",
    )

    args = parser.parse_args()

    if args.command == "generate-invoices":
        generated = generate_invoice_documents(
            args.root,
            output=args.format,
            html_folder=args.html_output,
            pdf_folder=args.pdf_output,
        )
        for item in generated:
            outputs = []
            if item.html_path:
                outputs.append(f"html={item.html_path}")
            if item.pdf_path:
                outputs.append(f"pdf={item.pdf_path}")
            print(f"{item.invoice_id}: {', '.join(outputs)}")
        print(f"Generated {len(generated)} invoice document set(s).")
        return

    if args.command == "setup":
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
        print("Installed Playwright Chromium.")
        return

    if args.command == "generate-all":
        print(to_pretty_json(generate_all_artifacts(args.root)))
        return

    if args.command == "doctor":
        print(to_pretty_json(artifact_status(args.root)))
        return

    if args.command == "generate-waypoint-seed":
        print(to_pretty_json(generate_waypoint_seed(args.root, output_path=args.output)))
        return

    if args.command == "generate-docx":
        generated = generate_docx_documents(
            args.root,
            contracts_output=args.contracts_output,
            policies_output=args.policies_output,
        )
        for item in generated:
            print(f"{item.source_path}: docx={item.output_path}")
        print(f"Generated {len(generated)} DOCX document(s).")
        return

    if args.command == "db":
        dsn = database_url(args.dsn)
        if args.db_command == "status":
            print(to_pretty_json(get_status(dsn)))
            return
        if args.db_command == "seed":
            status = seed_database(
                dsn,
                args.root,
                if_needed=args.if_needed,
                append_cycles=args.append_cycles,
            )
            print(to_pretty_json(status))
            return
        if args.db_command == "append":
            appended = append_live_invoices(dsn, args.root, cycles=args.cycles)
            status = get_status(dsn)
            status["appended_invoices"] = appended
            print(to_pretty_json(status))
            return

    if args.command == "serve":
        import uvicorn

        uvicorn.run("ledgerfield.api:app", host=args.host, port=args.port, reload=True)
        return

    if args.command == "upload-onelake":
        if args.files_only and args.tables_only:
            parser.error("--files-only and --tables-only are mutually exclusive.")
        import logging

        from .onelake_upload import upload_corpus

        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        try:
            summary = upload_corpus(
                args.root,
                workspace=args.workspace,
                lakehouse=args.lakehouse,
                account_url=args.account_url,
                corpus_prefix=args.corpus_prefix,
                upload_files=not args.tables_only,
                write_tables=not args.files_only,
                regenerate=not args.skip_generate,
            )
        except Exception as error:
            print(f"OneLake upload failed: {error}", file=sys.stderr)
            raise SystemExit(1) from error
        print(to_pretty_json(summary))
        return

    if args.command == "upload-contracts-kb":
        import logging

        from .contracts_kb_upload import upload_contracts_kb

        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        try:
            summary = upload_contracts_kb(
                args.root,
                storage_account=args.storage_account,
                container=args.container,
                prefix=args.prefix,
                account_url=args.account_url,
                include_policies=args.include_policies,
                regenerate=args.regenerate,
                search_endpoint=args.search_endpoint,
                indexer=args.indexer,
                search_api_version=args.search_api_version,
                source_root=args.source_root,
                include_operational=args.include_operational,
                append_only=args.append_only,
            )
        except Exception as error:
            print(f"contracts-kb upload failed: {error}", file=sys.stderr)
            raise SystemExit(1) from error
        print(to_pretty_json(summary))
        return

    parser.error("Unknown command")


if __name__ == "__main__":
    main()
