"""Reproduce the anchor-data download from ``anchor/MANIFEST.json``.

Usage (from the repository root)::

    python -m anchor.fetch            # download anything missing, verify everything
    python -m anchor.fetch --verify   # verify only; never touch the network
    python -m anchor.fetch --dataset iowa-muscatine-wrrf

The script is pure I/O: it takes no seed, has no randomness, and its only side
effects are files written under ``anchor/raw/<dataset-id>/``. Every file is
checked against the SHA-256 and byte size recorded in the manifest; a mismatch
is reported and the process exits non-zero. Large files are streamed to a
temporary name and renamed only after the checksum matches, so an interrupted
run never leaves a corrupt file behind under its final name.

Proxies are honoured through the standard ``HTTPS_PROXY`` environment variable
(``urllib`` reads it), and TLS verification is never disabled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from anchor.manifest import Dataset, Manifest, ManifestFile

_REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = _REPO_ROOT / "anchor" / "MANIFEST.json"
_CHUNK = 1 << 20  # 1 MiB
_USER_AGENT = "ad-agentbench-anchor-fetch/0.1 (+https://github.com/sdanquah101/agent-db)"


@dataclass(frozen=True)
class FileStatus:
    """Outcome of verifying one manifest file on disk."""

    dataset_id: str
    filename: str
    path: Path
    present: bool
    sha256_ok: bool
    size_ok: bool

    @property
    def ok(self) -> bool:
        """True when the file is present and both checks pass."""
        return self.present and self.sha256_ok and self.size_ok


def load_manifest(path: Path = MANIFEST_PATH) -> Manifest:
    """Read and validate the manifest.

    Args:
        path: Location of ``MANIFEST.json``.

    Returns:
        The validated manifest.
    """
    with path.open(encoding="utf-8") as fh:
        return Manifest.model_validate(json.load(fh))


def sha256_of(path: Path) -> str:
    """Stream a file and return its lower-case hex SHA-256."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def target_path(dataset: Dataset, file: ManifestFile, raw_root: Path) -> Path:
    """Where a manifest file lives on disk."""
    return raw_root / dataset.id / file.filename


def verify_file(dataset: Dataset, file: ManifestFile, raw_root: Path) -> FileStatus:
    """Check one file against its manifest entry without touching the network."""
    path = target_path(dataset, file, raw_root)
    if not path.is_file():
        return FileStatus(dataset.id, file.filename, path, False, False, False)
    size_ok = path.stat().st_size == file.size_bytes
    sha_ok = size_ok and sha256_of(path) == file.sha256
    return FileStatus(dataset.id, file.filename, path, True, sha_ok, size_ok)


def download_file(dataset: Dataset, file: ManifestFile, raw_root: Path) -> FileStatus:
    """Fetch one file, verify it, and move it into place only if it verifies.

    Args:
        dataset: Owning dataset (gives the folder name).
        file: Manifest entry with URL, expected size and SHA-256.
        raw_root: Root directory for raw data.

    Returns:
        The verification status of the file after the attempt.
    """
    path = target_path(dataset, file, raw_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    request = urllib.request.Request(str(file.url), headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as out:
        shutil.copyfileobj(response, out, _CHUNK)
    size_ok = tmp.stat().st_size == file.size_bytes
    sha_ok = size_ok and sha256_of(tmp) == file.sha256
    if sha_ok:
        tmp.replace(path)
        return FileStatus(dataset.id, file.filename, path, True, True, True)
    tmp.unlink(missing_ok=True)
    return FileStatus(dataset.id, file.filename, path, False, sha_ok, size_ok)


def run(
    manifest: Manifest,
    raw_root: Path,
    *,
    verify_only: bool,
    dataset_ids: set[str] | None = None,
) -> list[FileStatus]:
    """Verify (and, unless ``verify_only``, download) every selected file.

    Args:
        manifest: Validated manifest.
        raw_root: Root directory for raw data.
        verify_only: If true, never download; just report.
        dataset_ids: Restrict to these dataset ids (``None`` = all).

    Returns:
        One status per selected manifest file.
    """
    statuses: list[FileStatus] = []
    for dataset in manifest.datasets:
        if dataset_ids is not None and dataset.id not in dataset_ids:
            continue
        for file in dataset.files:
            status = verify_file(dataset, file, raw_root)
            if not status.ok and not verify_only:
                status = download_file(dataset, file, raw_root)
            statuses.append(status)
    return statuses


def _format(status: FileStatus) -> str:
    if status.ok:
        state = "ok"
    elif not status.present:
        state = "MISSING"
    elif not status.size_ok:
        state = "SIZE MISMATCH"
    else:
        state = "SHA-256 MISMATCH"
    return f"{state:17s} {status.dataset_id}/{status.filename}"


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Returns:
        ``0`` when every selected file verifies, ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument(
        "--verify", action="store_true", help="verify files already on disk; do not download"
    )
    parser.add_argument(
        "--dataset", action="append", default=None, help="dataset id to process (repeatable)"
    )
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    raw_root = (args.manifest.parent.parent / manifest.raw_root).resolve()
    statuses = run(
        manifest,
        raw_root,
        verify_only=args.verify,
        dataset_ids=set(args.dataset) if args.dataset else None,
    )
    for status in statuses:
        print(_format(status))
    failed = [s for s in statuses if not s.ok]
    print(f"{len(statuses) - len(failed)}/{len(statuses)} files verified")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
