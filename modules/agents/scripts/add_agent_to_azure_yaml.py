"""Append a new agent service block to azure.yaml.

Idempotent: refuses to append if a service with the same name already exists.
Inserts the new block immediately before the top-level `infra:` key, with the
same indentation style as the existing services.

Usage:
    python3 scripts/add_agent_to_azure_yaml.py <agent-name>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

AZURE_YAML = Path(__file__).resolve().parent.parent / "azure.yaml"


def _block(name: str) -> str:
    return (
        f"\n  {name}:\n"
        f"    project: ./agents/{name}\n"
        f"    host: azure.ai.agent\n"
        f"    language: docker\n"
        f"    docker:\n"
        f"      remoteBuild: true\n"
        f"    config:\n"
        f"      container:\n"
        f"        resources:\n"
        f'          cpu: "0.5"\n'
        f"          memory: 1Gi\n"
        f"      startupCommand: python main.py\n"
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: add_agent_to_azure_yaml.py <agent-name>", file=sys.stderr)
        return 2
    name = sys.argv[1]

    text = AZURE_YAML.read_text(encoding="utf-8")

    # Refuse if the service already exists
    if re.search(rf"^\s+{re.escape(name)}:\s*$", text, flags=re.MULTILINE):
        print(f"azure.yaml already has a service named '{name}' — nothing to do.")
        return 0

    # Insert the block right before the top-level `infra:` key
    new_text, n = re.subn(
        r"(^infra:\s*$)",
        _block(name) + r"\n\1",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if n != 1:
        # Fallback: append at end of file
        new_text = text.rstrip() + "\n" + _block(name) + "\n"

    AZURE_YAML.write_text(new_text, encoding="utf-8")
    print(f"Added service '{name}' to azure.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
