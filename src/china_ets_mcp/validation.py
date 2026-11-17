"""Argument validation shared by the MCP servers (full and lite).

Both servers call these helpers so that the checks cannot drift apart.
"""
from pathlib import Path

VALID_MARKETS = ("cea", "ccer")
VALID_FORMATS = ("csv", "xlsx")
DASHBOARD_SUFFIXES = (".html",)


def validate_market(market: str, allow_both: bool = False) -> str:
    """Return ``market`` if it is an accepted market name, else raise ValueError."""
    valid = (*VALID_MARKETS, "both") if allow_both else VALID_MARKETS
    if market not in valid:
        raise ValueError(f"market must be one of {valid}, got {market!r}")
    return market


def validate_format(fmt: str) -> str:
    """Return ``fmt`` if it is an accepted export format, else raise ValueError."""
    if fmt not in VALID_FORMATS:
        raise ValueError(f"format must be one of {VALID_FORMATS}, got {fmt!r}")
    return fmt


def validate_output_path(path: str, allowed_dir: Path, suffixes: tuple[str, ...] = DASHBOARD_SUFFIXES) -> Path:
    """Resolve ``path`` and require it to be inside ``allowed_dir`` with an allowed suffix.

    Containment is decided on resolved paths (``Path.is_relative_to``), not on string
    prefixes, so a sibling directory such as ``data_other`` is not accepted for ``data``.
    The suffix check keeps tools from overwriting existing data files (for example the
    database) that live inside the allowed directory.

    A ``:`` is not accepted anywhere below ``allowed_dir``: on Windows ``name:stream``
    addresses an NTFS alternate data stream, so ``china_ets.db:x.html`` would attach a
    hidden stream to the database file while still ending in ``.html``. Only the part
    below ``allowed_dir`` is looked at, so the drive letter of an absolute path is fine.

    Callers should write to the returned path, not to the original argument.
    """
    resolved = Path(path).resolve()
    allowed = Path(allowed_dir).resolve()
    if not resolved.is_relative_to(allowed):
        raise ValueError(f"Output path must be within {allowed}")
    relative = resolved.relative_to(allowed)
    if ":" in "".join(relative.parts):
        raise ValueError("Output path must not contain ':' below the allowed directory (alternate data stream)")
    if resolved.suffix.lower() not in suffixes:
        raise ValueError(f"Output file must have one of these extensions: {suffixes}")
    return resolved
