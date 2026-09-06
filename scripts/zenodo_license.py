"""Set a custom licence on a published Zenodo record.

Zenodo derives a record's licence from GitHub's detected licence. GitHub
reports Elastic-2.0 as NOASSERTION, and Zenodo then falls back to
cc-by-4.0 on every archive it mints for this repo. Elastic-2.0 has no id in
Zenodo's licence vocabulary, so the fix is a custom rights object applied
through the InvenioRDM draft flow. Metadata only: DOI, version, and files
are untouched, and the edit is repeatable.

Requires ZENODO_TOKEN with the deposit:write and deposit:actions scopes.

Usage:
    python scripts/zenodo_license.py            # latest record under the concept DOI
    python scripts/zenodo_license.py 22449520   # a specific record id
    python scripts/zenodo_license.py --check    # report only, change nothing

Author: Eric G. Suchanek, PhD
License: Elastic-2.0
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API = "https://zenodo.org/api"
CONCEPT_RECID = "19742773"
RIGHTS = [
    {
        "title": {"en": "Elastic License 2.0"},
        "description": {"en": "Elastic-2.0"},
        "link": "https://www.elastic.co/licensing/elastic-license",
    }
]
RDM = "application/vnd.inveniordm.v1+json"


def call(
    method: str, path: str, body: dict | None = None, accept: str = "application/json"
) -> tuple[int, dict]:
    """Issue one authenticated request and return (status, parsed json)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {os.environ['ZENODO_TOKEN']}")
    req.add_header("Accept", accept)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        print(f"{method} {path} -> HTTP {e.code}\n{raw[:800]}", file=sys.stderr)
        sys.exit(1)


def latest_record_id() -> str:
    """Resolve the concept record to its newest version's id."""
    with urllib.request.urlopen(f"{API}/records/{CONCEPT_RECID}") as resp:
        return str(json.load(resp)["id"])


def current_rights(record_id: str) -> list[dict]:
    _, rec = call("GET", f"/records/{record_id}", accept=RDM)
    return rec.get("metadata", {}).get("rights", [])


def describe(rights: list[dict]) -> str:
    return ", ".join(r.get("id") or r.get("title", {}).get("en", "?") for r in rights) or "(none)"


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    ids = [a for a in argv if not a.startswith("--")]
    record_id = ids[0] if ids else latest_record_id()

    if "ZENODO_TOKEN" not in os.environ:
        print("ZENODO_TOKEN is not set", file=sys.stderr)
        return 1

    before = current_rights(record_id)
    print(f"record {record_id}: rights = {describe(before)}")
    if before == RIGHTS:
        print("already Elastic License 2.0; nothing to do")
        return 0
    if check_only:
        print("would set rights to Elastic License 2.0 (run without --check)")
        return 2

    status, _ = call("POST", f"/records/{record_id}/draft")
    print(f"draft opened -> {status}")
    _, draft = call("GET", f"/records/{record_id}/draft", accept=RDM)
    draft["metadata"]["rights"] = RIGHTS
    status, _ = call("PUT", f"/records/{record_id}/draft", body=draft, accept=RDM)
    print(f"draft updated -> {status}")
    status, _ = call("POST", f"/records/{record_id}/draft/actions/publish")
    print(f"published -> {status}")

    after = current_rights(record_id)
    print(f"record {record_id}: rights = {describe(after)}")
    return 0 if after == RIGHTS else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
