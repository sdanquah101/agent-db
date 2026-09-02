"""Schema for ``anchor/MANIFEST.json``.

The manifest is the single source of truth for which open real-plant files the
anchor layer (proposal §8) uses, where they came from, under which licence, and
what their bytes must hash to. ``anchor/fetch.py`` reproduces the download from
it and verifies checksums; nothing else in the repository should hard-code a
dataset URL.

Two kinds of record are kept:

* :class:`ManifestFile` — a file that was actually downloaded, with its SHA-256,
  size and download date. Only files whose licence permits redistribution are
  listed here.
* :class:`NotFetched` — a candidate that was identified and characterised but
  deliberately *not* downloaded (no open licence, simulated rather than
  measured, not deposited anywhere, …), with the reason. These exist so the
  evaluation of §8 is auditable from the manifest alone.
"""

from __future__ import annotations

import datetime as _dt
import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class DataKind(StrEnum):
    """What a file physically contains."""

    MEASURED = "measured"
    """Measurements from a real (full-, pilot- or small-scale) digester."""

    CODE = "code"
    """Source code / notebooks that accompany a measured dataset."""

    SIMULATED = "simulated"
    """Model output (for example the BSM2 influent). Never an anchor."""


class Scale(StrEnum):
    """Digester scale, as stated by the data provider."""

    FULL = "full"
    PILOT = "pilot"
    SMALL = "small"  # household / farm-scale ≤ ~10 m³
    LAB = "lab"
    NOT_APPLICABLE = "n/a"


class Licence(BaseModel):
    """A machine-readable licence statement.

    ``redistributable`` records our reading of the licence; the manifest test
    refuses any downloaded file whose licence is not redistributable.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Exact licence name as stated by the provider.")
    url: HttpUrl | None = Field(default=None, description="Canonical licence URL.")
    redistributable: bool = Field(
        description="Whether the licence permits us to redistribute the bytes."
    )


class ManifestFile(BaseModel):
    """One downloaded file."""

    model_config = ConfigDict(frozen=True)

    filename: str = Field(description="Name under anchor/raw/<dataset-id>/.")
    url: HttpUrl = Field(description="Exact URL the bytes were fetched from.")
    sha256: str = Field(description="Lower-case hex SHA-256 of the file.")
    size_bytes: int = Field(gt=0, description="Size in bytes.")
    download_date: _dt.date = Field(description="UTC date the file was fetched.")
    kind: DataKind = Field(description="Measured data, code, or simulated data.")
    description: str = Field(description="What the file holds, in one sentence.")

    @field_validator("sha256")
    @classmethod
    def _check_hex(cls, value: str) -> str:
        if not _SHA256_RE.match(value):
            msg = "sha256 must be 64 lower-case hex characters"
            raise ValueError(msg)
        return value

    @field_validator("filename")
    @classmethod
    def _check_filename(cls, value: str) -> str:
        if "/" in value or value in {"", ".", ".."}:
            msg = "filename must be a plain file name without path separators"
            raise ValueError(msg)
        return value


class Dataset(BaseModel):
    """A dataset that was downloaded (one or more files)."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", description="Folder name.")
    title: str
    landing_url: HttpUrl = Field(description="Human landing page (record page).")
    doi: str | None = Field(default=None, description="DOI of the dataset record.")
    creators: list[str]
    publisher: str
    licence: Licence
    scale: Scale
    plant: str = Field(description="Plant type, feedstock, volume, temperature.")
    period: str = Field(description="Calendar span covered by the measurements.")
    resolution: str = Field(description="Sampling resolution per variable group.")
    citation: str = Field(description="How the provider asks to be cited.")
    files: list[ManifestFile] = Field(min_length=1)


class NotFetched(BaseModel):
    """A candidate that was characterised but not downloaded."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str
    url: HttpUrl
    doi: str | None = None
    licence: str = Field(description="Exact licence name, or 'unknown'.")
    kind: DataKind
    scale: Scale
    reason: str = Field(description="Why it was not downloaded.")


class Manifest(BaseModel):
    """Root object of ``anchor/MANIFEST.json``."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = Field(ge=1)
    generated: _dt.date
    raw_root: str = Field(
        default="anchor/raw", description="Directory, relative to repo root, that holds files."
    )
    datasets: list[Dataset]
    not_fetched: list[NotFetched] = Field(default_factory=list)

    @field_validator("datasets")
    @classmethod
    def _unique_ids(cls, value: list[Dataset]) -> list[Dataset]:
        ids = [d.id for d in value]
        if len(ids) != len(set(ids)):
            msg = "dataset ids must be unique"
            raise ValueError(msg)
        return value
