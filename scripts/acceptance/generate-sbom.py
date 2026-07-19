"""Generate a deterministic CycloneDX 1.6 SBOM from committed lock files."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs" / "verification" / "release" / "sbom.cdx.json"


def npm_components() -> set[tuple[str, str, str]]:
    text = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    entries: set[tuple[str, str, str]] = set()
    pattern = re.compile(r"^  (?:'([^']+)'|([^:\s][^:]*)):\s*$", re.MULTILINE)
    for match in pattern.finditer(text):
        value = match.group(1) or match.group(2)
        if value.startswith((".", "/")) or "@" not in value:
            continue
        name, version = value.rsplit("@", 1)
        version = version.split("(", 1)[0]
        if name and re.match(r"^\d", version):
            purl_name = quote(name, safe="@/")
            entries.add((name, version, f"pkg:npm/{purl_name}@{version}"))
    return entries


def python_components() -> set[tuple[str, str, str]]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    return {
        (package["name"], package["version"], f"pkg:pypi/{package['name']}@{package['version']}")
        for package in lock.get("package", [])
        if "name" in package and "version" in package
    }


def main() -> None:
    components = [
        {"bom-ref": purl, "name": name, "purl": purl, "type": "library", "version": version}
        for name, version, purl in sorted(npm_components() | python_components())
    ]
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    document = {
        "$schema": "https://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "components": components,
        "metadata": {
            "component": {
                "name": package["name"],
                "type": "application",
                "version": package["version"],
            },
            "tools": {
                "components": [{"name": "generate-sbom.py", "type": "application", "version": "1"}]
            },
        },
        "serialNumber": "urn:uuid:2fce83f2-d01d-5d7d-b0be-1cc23e3df3a7",
        "specVersion": "1.6",
        "version": 1,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"SBOM_COMPONENTS={len(components)}")
    print(f"SBOM_OUTPUT={OUTPUT.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
