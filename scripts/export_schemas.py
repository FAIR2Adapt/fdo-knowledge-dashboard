"""Write listing/schema/search.schema.json and qa.schema.json from the pydantic models (listing/models.py).
    python scripts/export_schemas.py [--check]      # --check: exit 1 when a file differs from the models
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic.json_schema import models_json_schema

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from listing import models  # noqa: E402

FILES = {
    "search.schema.json": (models.SEARCH_MODELS, "fdo-knowledge-dashboard search and delivery contract, version 1",
                           "Additive to catalog/1 and record/1. States readiness (usable, not_usable) and delivery (public metadata, file access) only; scientific validity is out of scope and no field asserts it. Static and HTTP modes return the same members, the same order (title and type by folded text in code-point order, ties by the raw title; date newest first) and the same facet counts. Text lengths are Unicode code points."),
    "qa.schema.json": (models.QA_MODELS, "fdo-knowledge-dashboard question-answering and discovery contract, version 2 (provisional)",
                       "The dashboard sends a QaRequest and shows a QaResponse only with cited resources; the provider (T4.3) performs retrieval and generation. Version 2 adds bounded prior turns (history) and a client-chosen conversation_id; a provider that ignores both behaves as in version 1 (one-shot). Capabilities are declared before the first request (QaCapabilities); unknown is unsupported."),
}


def document(model_list: list, title: str, description: str) -> dict:
    _, schema = models_json_schema([(m, "validation") for m in model_list], ref_template="#/$defs/{model}")
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"https://fair2adapt.github.io/fdo-knowledge-dashboard/schema/{title.split()[1]}/{title.split()[-1].strip('()')}",
            "title": title, "description": description, "$defs": schema["$defs"]}


def render(name: str) -> str:
    model_list, title, description = FILES[name]
    return json.dumps(document(model_list, title, description), ensure_ascii=False, indent=1) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the JSON schemas from the models.")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for name in FILES:
        path = ROOT / "listing" / "schema" / name
        text = render(name)
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            path.write_text(text, encoding="utf-8")
            print(f"  {path.relative_to(ROOT)}")
    if stale:
        print("schemas differ from the models: " + ", ".join(stale) + " (run scripts/export_schemas.py)", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
