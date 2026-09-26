# Contracts invoice smoke fixtures

These PDFs are copied from the Ledgerfield invoice generator output and are kept
inside the Contracts agent so local playground smoke tests are self-contained.

Source generator:

```powershell
uv run --no-project --with jinja2 --with playwright python -m playwright install chromium
@'
from pathlib import Path
import sys
sys.path.insert(0, str(Path("modules/corpus/src").resolve()))
from ledgerfield.invoice_docs import generate_invoice_documents
generate_invoice_documents(Path("modules/corpus").resolve(), output="both")
'@ | uv run --no-project --with jinja2 --with playwright python -
```

Refresh this folder after regenerating corpus invoices:

```powershell
Copy-Item modules\corpus\data\invoices\pdf\*.pdf modules\agents\contracts\fixtures\invoices\ -Force
```

Set `CONTRACTS_LOCAL_DOCUMENT_KIND=invoice` to use
`sup-001-inv-sup-001-2026-10.pdf` by default, or set
`CONTRACTS_LOCAL_INVOICE_PDF_PATH` to another file in this folder.
