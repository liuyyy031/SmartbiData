from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPTS = [
    "scan_raw_files.py",
    "extract_supply_records.py",
    "normalize_supply_records.py",
    "build_supply_candidates.py",
    "validate_supply_data.py",
]


def main() -> None:
    scripts_dir = Path(__file__).resolve().parent
    for script_name in SCRIPTS:
        script = scripts_dir / script_name
        print(f"==> {script_name}")
        completed = subprocess.run([sys.executable, str(script)], cwd=str(scripts_dir), check=False)
        if completed.returncode != 0:
            raise SystemExit(f"pipeline stopped: {script_name} exited with {completed.returncode}")
    print("pipeline_completed=true")


if __name__ == "__main__":
    main()
