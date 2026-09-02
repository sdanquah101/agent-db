"""Tests for the anchor manifest and the fetch/verify script.

No test here touches the network: downloads are exercised against a local
HTTP server serving a temporary directory.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import http.server
import json
import threading
from pathlib import Path

import pytest

from anchor import fetch
from anchor.manifest import DataKind, Dataset, Licence, Manifest, ManifestFile, Scale

REPO_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# The committed manifest
# --------------------------------------------------------------------------- #


def test_committed_manifest_validates():
    manifest = fetch.load_manifest()
    assert manifest.datasets, "manifest lists no datasets"
    assert manifest.schema_version == 1


def test_downloaded_files_are_redistributable():
    manifest = fetch.load_manifest()
    for dataset in manifest.datasets:
        assert dataset.licence.redistributable, dataset.id
        for file in dataset.files:
            assert str(file.url).startswith("https://"), file.url


def test_no_simulated_data_is_anchored():
    manifest = fetch.load_manifest()
    for dataset in manifest.datasets:
        for file in dataset.files:
            assert file.kind != DataKind.SIMULATED, f"{dataset.id}/{file.filename}"


def test_committed_raw_files_verify():
    """Files small enough to be committed must match the manifest byte for byte."""
    manifest = fetch.load_manifest()
    raw_root = REPO_ROOT / manifest.raw_root
    committed = {
        ("iowa-muscatine-wrrf", "README.txt"),
        ("iowa-muscatine-wrrf", "LABS-raw.csv"),
        ("iowa-muscatine-wrrf", "LABS-data-dictionary.csv"),
        ("iowa-muscatine-wrrf", "SCADA-data-dictionary.csv"),
    }
    seen = set()
    for dataset in manifest.datasets:
        for file in dataset.files:
            key = (dataset.id, file.filename)
            if key in committed:
                status = fetch.verify_file(dataset, file, raw_root)
                assert status.ok, status
                seen.add(key)
    assert seen == committed


def test_present_raw_files_verify():
    """Any raw file that happens to be on disk (e.g. after a fetch) must verify."""
    manifest = fetch.load_manifest()
    raw_root = REPO_ROOT / manifest.raw_root
    for dataset in manifest.datasets:
        for file in dataset.files:
            status = fetch.verify_file(dataset, file, raw_root)
            if status.present:
                assert status.ok, status


def test_not_fetched_entries_have_reasons():
    manifest = fetch.load_manifest()
    ids = [n.id for n in manifest.not_fetched]
    assert len(ids) == len(set(ids))
    for entry in manifest.not_fetched:
        assert len(entry.reason) > 20, entry.id


# --------------------------------------------------------------------------- #
# Schema guards
# --------------------------------------------------------------------------- #


def _file(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "filename": "a.csv",
        "url": "https://example.org/a.csv",
        "sha256": "0" * 64,
        "size_bytes": 1,
        "download_date": "2026-09-02",
        "kind": "measured",
        "description": "x",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "bad",
    [
        {"sha256": "abc"},
        {"sha256": "A" * 64},
        {"size_bytes": 0},
        {"filename": "sub/dir.csv"},
        {"kind": "guess"},
    ],
)
def test_manifest_file_rejects_bad_values(bad):
    with pytest.raises(ValueError):
        ManifestFile.model_validate(_file(**bad))


def test_manifest_rejects_duplicate_dataset_ids():
    dataset = {
        "id": "dup",
        "title": "t",
        "landing_url": "https://example.org",
        "creators": ["a"],
        "publisher": "p",
        "licence": {"name": "CC BY 4.0", "redistributable": True},
        "scale": "full",
        "plant": "p",
        "period": "p",
        "resolution": "r",
        "citation": "c",
        "files": [_file()],
    }
    with pytest.raises(ValueError, match="unique"):
        Manifest.model_validate(
            {"schema_version": 1, "generated": "2026-09-02", "datasets": [dataset, dataset]}
        )


# --------------------------------------------------------------------------- #
# verify / download against a local server
# --------------------------------------------------------------------------- #


@pytest.fixture
def local_server(tmp_path: Path):
    """Serve ``tmp_path / 'srv'`` over HTTP on an ephemeral port."""
    root = tmp_path / "srv"
    root.mkdir()
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(  # noqa: E731
        *a, directory=str(root), **k
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield root, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _dataset(url: str, payload: bytes, sha256: str | None = None) -> Dataset:
    return Dataset(
        id="local-test",
        title="t",
        landing_url="https://example.org",
        creators=["a"],
        publisher="p",
        licence=Licence(name="CC BY 4.0", redistributable=True),
        scale=Scale.LAB,
        plant="p",
        period="p",
        resolution="r",
        citation="c",
        files=[
            ManifestFile(
                filename="payload.bin",
                url=url,
                sha256=sha256 or hashlib.sha256(payload).hexdigest(),
                size_bytes=len(payload),
                download_date=dt.date(2026, 9, 2),
                kind=DataKind.MEASURED,
                description="d",
            )
        ],
    )


def test_download_then_verify_roundtrip(local_server, tmp_path: Path):
    root, base_url = local_server
    payload = b"biogas,ph\n1,7.2\n" * 1000
    (root / "payload.bin").write_bytes(payload)
    dataset = _dataset(f"{base_url}/payload.bin", payload)
    raw_root = tmp_path / "raw"

    before = fetch.verify_file(dataset, dataset.files[0], raw_root)
    assert not before.present

    status = fetch.download_file(dataset, dataset.files[0], raw_root)
    assert status.ok
    assert (raw_root / "local-test" / "payload.bin").read_bytes() == payload
    assert not (raw_root / "local-test" / "payload.bin.part").exists()

    again = fetch.verify_file(dataset, dataset.files[0], raw_root)
    assert again.ok


def test_download_rejects_checksum_mismatch(local_server, tmp_path: Path):
    root, base_url = local_server
    payload = b"hello"
    (root / "payload.bin").write_bytes(payload)
    dataset = _dataset(f"{base_url}/payload.bin", payload, sha256="1" * 64)
    raw_root = tmp_path / "raw"

    status = fetch.download_file(dataset, dataset.files[0], raw_root)
    assert not status.ok
    assert not status.sha256_ok
    assert not (raw_root / "local-test" / "payload.bin").exists(), "corrupt file kept"


def test_verify_detects_size_and_hash_mismatch(tmp_path: Path):
    payload = b"abc"
    dataset = _dataset("https://example.org/payload.bin", payload)
    raw_root = tmp_path / "raw"
    target = raw_root / "local-test" / "payload.bin"
    target.parent.mkdir(parents=True)

    target.write_bytes(b"abcd")
    status = fetch.verify_file(dataset, dataset.files[0], raw_root)
    assert status.present and not status.size_ok and not status.ok

    target.write_bytes(b"abd")
    status = fetch.verify_file(dataset, dataset.files[0], raw_root)
    assert status.present and status.size_ok and not status.sha256_ok


def test_cli_verify_only_never_downloads(local_server, tmp_path: Path):
    root, base_url = local_server
    payload = b"x" * 10
    (root / "payload.bin").write_bytes(payload)
    dataset = _dataset(f"{base_url}/payload.bin", payload)
    manifest = Manifest(
        schema_version=1, generated=dt.date(2026, 9, 2), raw_root="raw", datasets=[dataset]
    )
    manifest_dir = tmp_path / "anchor"
    manifest_dir.mkdir()
    manifest_path = manifest_dir / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest.model_dump(mode="json")), encoding="utf-8")

    assert fetch.main(["--manifest", str(manifest_path), "--verify"]) == 1
    assert not (tmp_path / "raw" / "local-test" / "payload.bin").exists()

    assert fetch.main(["--manifest", str(manifest_path)]) == 0
    assert (tmp_path / "raw" / "local-test" / "payload.bin").read_bytes() == payload
    assert fetch.main(["--manifest", str(manifest_path), "--verify"]) == 0
