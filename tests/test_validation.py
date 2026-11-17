"""Unit tests for the argument validation shared by both MCP servers."""
import os

import pytest

from china_ets_mcp.validation import validate_format, validate_market, validate_output_path


# --- market -----------------------------------------------------------------

@pytest.mark.parametrize("market", ["cea", "ccer"])
def test_market_accepts_known_names(market):
    assert validate_market(market) == market


def test_market_both_is_accepted_only_when_allowed():
    assert validate_market("both", allow_both=True) == "both"


@pytest.mark.parametrize("market", ["both", "../../x", "CEA", "", "cea ", "cea/../x", "a\\b"])
def test_rejects_unknown_market(market):
    with pytest.raises(ValueError, match="market must be one of"):
        validate_market(market)


def test_rejects_unknown_market_even_when_both_is_allowed():
    with pytest.raises(ValueError, match="market must be one of"):
        validate_market("../../x", allow_both=True)


# --- format -----------------------------------------------------------------

@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_format_accepts_known_names(fmt):
    assert validate_format(fmt) == fmt


@pytest.mark.parametrize("fmt", ["evil", "CSV", "", "csv/../x", "json"])
def test_rejects_unknown_format(fmt):
    with pytest.raises(ValueError, match="format must be one of"):
        validate_format(fmt)


# --- output path --------------------------------------------------------------

def test_output_path_inside_allowed_dir_is_accepted(tmp_path):
    allowed = tmp_path / "data"
    got = validate_output_path(str(allowed / "dashboard.html"), allowed)
    assert got == (allowed / "dashboard.html").resolve()


def test_output_path_in_subdirectory_is_accepted(tmp_path):
    allowed = tmp_path / "data"
    got = validate_output_path(str(allowed / "reports" / "a.html"), allowed)
    assert got == (allowed / "reports" / "a.html").resolve()


def test_html_suffix_is_case_insensitive(tmp_path):
    allowed = tmp_path / "data"
    assert validate_output_path(str(allowed / "A.HTML"), allowed).name == "A.HTML"


def test_rejects_absolute_path_outside_allowed_dir(tmp_path):
    allowed = tmp_path / "data"
    with pytest.raises(ValueError, match="Output path must be within"):
        validate_output_path(str(tmp_path / "outside" / "a.html"), allowed)


def test_rejects_sibling_directory_sharing_the_name_prefix(tmp_path):
    allowed = tmp_path / "data"
    with pytest.raises(ValueError, match="Output path must be within"):
        validate_output_path(str(tmp_path / "data_evil" / "a.html"), allowed)


def test_rejects_parent_traversal_that_leaves_allowed_dir(tmp_path):
    allowed = tmp_path / "data"
    with pytest.raises(ValueError, match="Output path must be within"):
        validate_output_path(str(allowed / ".." / "outside" / "a.html"), allowed)


def test_rejects_alternate_data_stream_name(tmp_path):
    allowed = tmp_path / "data"
    with pytest.raises(ValueError, match="alternate data stream"):
        validate_output_path(str(allowed / "china_ets.db:x.html"), allowed)


def test_rejects_colon_in_a_subdirectory_name(tmp_path):
    allowed = tmp_path / "data"
    with pytest.raises(ValueError, match="alternate data stream"):
        validate_output_path(str(allowed / "reports:x" / "a.html"), allowed)


@pytest.mark.skipif(os.name != "nt", reason="drive letters exist only on Windows")
def test_drive_letter_colon_is_not_rejected(tmp_path):
    allowed = tmp_path / "data"
    got = validate_output_path(str(allowed / "a.html"), allowed)
    assert got.drive.endswith(":")  # the absolute path really does contain a ':'
    assert got == (allowed / "a.html").resolve()


def test_colon_above_the_allowed_directory_is_ignored(tmp_path):
    allowed = tmp_path / "odd:parent" / "data"
    got = validate_output_path(str(allowed / "a.html"), allowed)
    assert got.name == "a.html"


@pytest.mark.parametrize("name", ["china_ets.db", "dashboard.htm", "dashboard", "notes.json", "x.html.exe"])
def test_rejects_other_file_types_inside_allowed_dir(tmp_path, name):
    allowed = tmp_path / "data"
    with pytest.raises(ValueError, match="extensions"):
        validate_output_path(str(allowed / name), allowed)
