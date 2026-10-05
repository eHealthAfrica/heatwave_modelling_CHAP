"""Verify the frozen covariate dataset against its MANIFEST and the forecast.yaml anchor.

Read-only: files are only ever opened with "rb"; nothing is written or chmod-ed.

    python scripts/verify_frozen.py                  # full: outputs + all MANIFEST inputs (~3 GB, slow)
    python scripts/verify_frozen.py --outputs-only   # fast: frozen outputs and the forecast.yaml anchor

Exit codes: 0 all good, 1 mismatch/missing/bad key/unlisted file, 2 setup error.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from heatwave.config import settings  # noqa: E402
from heatwave.forecast.config import (  # noqa: E402
    FORECAST_CONFIG_PATH,
    DataConfig,
    load_forecast_config,
)
from heatwave.forecast.data import (  # noqa: E402
    PARQUET_NAME,
    FrozenDataError,
    frozen_dataset_dir,
    read_manifest,
    sha256_file,
)

log = logging.getLogger("verify_frozen")


class _Tally:
    def __init__(self) -> None:
        self.checked = 0
        self.mismatch = 0
        self.missing = 0
        self.bad = 0
        self.unlisted = 0

    def report(self, status: str, rel: str) -> None:
        print(f"{status} {rel}")
        if status == "MISMATCH":
            self.mismatch += 1
        elif status == "MISSING":
            self.missing += 1
        elif status == "BAD-KEY":
            self.bad += 1
        elif status == "UNLISTED":
            self.unlisted += 1


def _check_hash(tally: _Tally, path: Path, want: str, label: str) -> None:
    tally.checked += 1
    if not path.is_file():
        tally.report("MISSING", label)
        return
    got = sha256_file(path)
    tally.report("OK" if got == want else "MISMATCH", label)


def _note_writable(path: Path) -> None:
    if path.is_file() and os.access(path, os.W_OK):
        print(f"NOTE writable (expected read-only): {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", type=Path, default=settings.local_data_dir)
    parser.add_argument("--config", type=Path, default=FORECAST_CONFIG_PATH)
    parser.add_argument("--version", default=None)
    parser.add_argument("--expected-parquet-sha256", default=None)
    parser.add_argument("--outputs-only", action="store_true", help="skip the (slow) input hashing")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    try:
        cfg = load_forecast_config(args.config)
        data_cfg = DataConfig(
            args.version or cfg.data.version,
            cfg.data.frozen_subdir,
            args.expected_parquet_sha256 or cfg.data.expected_parquet_sha256,
        )
        data_root = Path(args.data_root).resolve()
        dataset_dir = frozen_dataset_dir(data_cfg, data_root)
        manifest = read_manifest(dataset_dir)
        if manifest.get("version") != data_cfg.version:
            raise FrozenDataError(f"MANIFEST version {manifest.get('version')!r} != {data_cfg.version!r}")
        outputs = manifest["outputs_sha256"]
        inputs = manifest.get("inputs_sha256", {})
        if not isinstance(outputs, dict) or not isinstance(inputs, dict):
            raise FrozenDataError("MANIFEST sha256 sections must be objects")
    except (ValueError, FrozenDataError, KeyError, OSError) as exc:
        print(f"verify_frozen: error: {exc}", file=sys.stderr)
        return 2

    tally = _Tally()

    # (a) outputs, (b) forecast.yaml anchor
    for name, want in sorted(outputs.items()):
        path = dataset_dir / name
        _check_hash(tally, path, want, name)
        _note_writable(path)
    if PARQUET_NAME in outputs and outputs[PARQUET_NAME] != data_cfg.expected_parquet_sha256:
        tally.report("MISMATCH", f"{PARQUET_NAME} vs forecast.yaml data.expected_parquet_sha256")
    elif PARQUET_NAME not in outputs:
        tally.report("MISSING", f"{PARQUET_NAME} entry in MANIFEST outputs_sha256")
    else:
        tally.checked += 1
        tally.report("OK", f"{PARQUET_NAME} vs forecast.yaml data.expected_parquet_sha256")

    if not args.outputs_only:
        root_resolved = data_root
        # (c) every inputs_sha256 key
        for i, (key, want) in enumerate(sorted(inputs.items()), 1):
            target = (data_root / key).resolve()
            if target != root_resolved and root_resolved not in target.parents:
                tally.report("BAD-KEY", key)
                continue
            _check_hash(tally, target, want, key)
            if i % 50 == 0:
                log.info("hashed %d/%d inputs", i, len(inputs))
        # (d) copied inputs
        inputs_dir = dataset_dir / "inputs"
        if inputs_dir.is_dir():
            for path in sorted(p for p in inputs_dir.rglob("*") if p.is_file()):
                rel = path.relative_to(inputs_dir).as_posix()
                if rel not in inputs:
                    tally.report("UNLISTED", f"inputs/{rel}")
                    continue
                _check_hash(tally, path, inputs[rel], f"inputs/{rel}")
                _note_writable(path)

    print(
        f"verify_frozen: {tally.checked} checked, {tally.mismatch} mismatches, "
        f"{tally.missing} missing, {tally.bad} bad keys"
        + (f", {tally.unlisted} unlisted" if tally.unlisted else "")
    )
    bad = tally.mismatch + tally.missing + tally.bad + tally.unlisted
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
