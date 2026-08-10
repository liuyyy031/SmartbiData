#!/usr/bin/env python3
"""Print a read-only boundary inspection summary."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from standardize_boundary import BoundaryValidationError, inspect_boundary, load_boundary


def main() -> int:
    path = Path(__file__).resolve().parents[1] / "data/boundary/raw/广西壮族自治区_县.geojson"
    try:
        print(json.dumps(inspect_boundary(load_boundary(path)), ensure_ascii=False, indent=2))
        return 0
    except (FileNotFoundError, BoundaryValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
