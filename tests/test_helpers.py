"""Unit tests for pure helper functions in main.py.

Covers detect_content_type, _parse_version, and edge cases not
exercised by test_main_flow.py or test_version_detection.py.
"""

from __future__ import annotations

from deep_analysis_agent.main import _parse_version, detect_content_type

# --- detect_content_type ---


class TestDetectContentType:
    """Exercise the glob-based content_type resolver."""

    def test_match_log_dat(self) -> None:
        assert detect_content_type("Match_GameLog_12345.dat") == "match-log"

    def test_grouping_xml_decklist(self) -> None:
        assert detect_content_type("grouping 98765.xml") == "decklist"

    def test_unknown_extension(self) -> None:
        assert detect_content_type("random_file.txt") == "unknown"

    def test_unknown_empty_string(self) -> None:
        assert detect_content_type("") == "unknown"

    def test_match_log_requires_prefix(self) -> None:
        """A .dat file without the Match_GameLog_ prefix is unknown."""
        assert detect_content_type("SomeOther_12345.dat") == "unknown"

    def test_grouping_requires_space_and_id(self) -> None:
        """'grouping.xml' (no space + ID) is not a decklist."""
        assert detect_content_type("grouping.xml") == "unknown"

    def test_grouping_with_various_ids(self) -> None:
        assert detect_content_type("grouping 1.xml") == "decklist"
        assert detect_content_type("grouping 999999999.xml") == "decklist"

    def test_match_log_case_sensitive(self) -> None:
        """fnmatch is case-sensitive on non-Windows; match pattern is exact case."""
        # The glob "Match_GameLog_*.dat" should not match lowercase.
        result = detect_content_type("match_gamelog_12345.dat")
        assert result == "unknown"

    def test_grouping_case_sensitive(self) -> None:
        result = detect_content_type("Grouping 12345.xml")
        assert result == "unknown"

    def test_match_log_minimal_id(self) -> None:
        """Match_GameLog_ followed by a single char and .dat should match."""
        assert detect_content_type("Match_GameLog_0.dat") == "match-log"

    def test_dat_alone_is_unknown(self) -> None:
        assert detect_content_type("Match_GameLog_.dat") == "match-log"

    def test_grouping_with_spaces_in_id(self) -> None:
        """The glob 'grouping *.xml' matches anything after 'grouping '."""
        assert detect_content_type("grouping foo bar.xml") == "decklist"


# --- _parse_version ---


class TestParseVersion:
    """Exercise the dotted-version parser used for heartbeat floor checks."""

    def test_simple_three_part(self) -> None:
        assert _parse_version("0.6.0") == (0, 6, 0)

    def test_two_part(self) -> None:
        assert _parse_version("1.0") == (1, 0)

    def test_single_part(self) -> None:
        assert _parse_version("3") == (3,)

    def test_stops_at_non_numeric_suffix(self) -> None:
        """'1.2.3rc1' — the segment '3rc1' is not a pure int, so parsing stops at (1, 2)."""
        assert _parse_version("1.2.3rc1") == (1, 2)

    def test_hyphen_suffix_stops_at_non_numeric(self) -> None:
        """'0.6.0-rc1' — the segment '0-rc1' is not an int, so parsing stops at (0, 6)."""
        assert _parse_version("0.6.0-rc1") == (0, 6)

    def test_v_prefix_returns_empty(self) -> None:
        """A leading 'v' is not stripped — 'v0' is not an int, so the result is empty."""
        assert _parse_version("v0.6.0") == ()

    def test_garbage_returns_empty(self) -> None:
        """Completely non-numeric input produces an empty tuple."""
        assert _parse_version("not-a-version") == ()

    def test_empty_string_returns_empty(self) -> None:
        assert _parse_version("") == ()

    def test_whitespace_stripped(self) -> None:
        """Leading/trailing whitespace is stripped before splitting."""
        assert _parse_version("  1.2.3  ") == (1, 2, 3)

    def test_comparison_ordering(self) -> None:
        assert _parse_version("0.4.8") < _parse_version("0.5.0")
        assert _parse_version("0.5.0") == _parse_version("0.5.0")
        assert _parse_version("1.0.0") > _parse_version("0.99.99")

    def test_four_part_version(self) -> None:
        assert _parse_version("1.2.3.4") == (1, 2, 3, 4)

    def test_large_numbers(self) -> None:
        assert _parse_version("100.200.300") == (100, 200, 300)
