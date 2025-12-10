"""Tests for rtl_power parser."""

from datetime import datetime
from pathlib import Path

import pytest

from tscm.collectors.rf_parser import RFEvent, RTLPowerParser


@pytest.fixture
def sample_csv_path():
    """Path to sample rtl_power CSV file."""
    return Path(__file__).parent / "fixtures" / "rtl_power_sample.csv"


@pytest.fixture
def parser():
    """Create a parser instance."""
    return RTLPowerParser(strict=False)


@pytest.fixture
def strict_parser():
    """Create a strict parser instance."""
    return RTLPowerParser(strict=True)


class TestRFEvent:
    """Test RFEvent dataclass."""

    def test_freq_bins(self):
        """Test frequency bin generation."""
        event = RFEvent(
            timestamp=datetime(2024, 12, 9, 14, 30, 0),
            freq_low_hz=100e6,
            freq_high_hz=101e6,
            freq_step_hz=500e3,
            samples=100,
            power_readings_db=[-45.0, -46.0],
        )

        bins = event.freq_bins
        assert len(bins) == 2
        assert bins[0] == (100e6, -45.0)
        assert bins[1] == (100.5e6, -46.0)

    def test_mean_power(self):
        """Test mean power calculation."""
        event = RFEvent(
            timestamp=datetime(2024, 12, 9, 14, 30, 0),
            freq_low_hz=100e6,
            freq_high_hz=101e6,
            freq_step_hz=500e3,
            samples=100,
            power_readings_db=[-40.0, -50.0, -45.0],
        )

        assert event.mean_power_db == -45.0

    def test_max_min_power(self):
        """Test max and min power."""
        event = RFEvent(
            timestamp=datetime(2024, 12, 9, 14, 30, 0),
            freq_low_hz=100e6,
            freq_high_hz=101e6,
            freq_step_hz=500e3,
            samples=100,
            power_readings_db=[-40.0, -50.0, -45.0],
        )

        assert event.max_power_db == -40.0
        assert event.min_power_db == -50.0

    def test_empty_readings(self):
        """Test behavior with empty power readings."""
        event = RFEvent(
            timestamp=datetime(2024, 12, 9, 14, 30, 0),
            freq_low_hz=100e6,
            freq_high_hz=101e6,
            freq_step_hz=500e3,
            samples=100,
            power_readings_db=[],
        )

        assert event.mean_power_db == 0.0
        assert event.max_power_db == float("-inf")
        assert event.min_power_db == float("inf")
        assert event.freq_bins == []


class TestRTLPowerParser:
    """Test RTLPowerParser."""

    def test_parse_valid_line(self, parser):
        """Test parsing a valid rtl_power line."""
        line = "2024-12-09, 14:30:00, 50000000, 51000000, 1000000.00, 100, -45.2, -46.3, -44.1"
        event = parser.parse_line(line)

        assert event is not None
        assert event.timestamp == datetime(2024, 12, 9, 14, 30, 0)
        assert event.freq_low_hz == 50e6
        assert event.freq_high_hz == 51e6
        assert event.freq_step_hz == 1e6
        assert event.samples == 100
        assert len(event.power_readings_db) == 3
        assert event.power_readings_db[0] == -45.2
        assert event.power_readings_db[1] == -46.3
        assert event.power_readings_db[2] == -44.1
        assert parser.lines_parsed == 1
        assert parser.lines_skipped == 0

    def test_parse_multiple_readings(self, parser):
        """Test parsing line with many power readings."""
        line = (
            "2024-12-09, 14:30:40, 433000000, 434000000, 100000.00, 200, "
            "-42.1, -41.8, -43.2, -42.5, -41.9, -42.0, -41.7, -42.8, -42.3, -41.6"
        )
        event = parser.parse_line(line)

        assert event is not None
        assert event.freq_low_hz == 433e6
        assert len(event.power_readings_db) == 10
        # Calculate expected mean: sum of values / count
        expected_mean = sum([-42.1, -41.8, -43.2, -42.5, -41.9, -42.0, -41.7, -42.8, -42.3, -41.6]) / 10
        assert event.mean_power_db == pytest.approx(expected_mean, rel=0.01)

    def test_parse_empty_line(self, parser):
        """Test parsing empty line."""
        event = parser.parse_line("")
        assert event is None
        assert parser.lines_skipped == 0  # Empty lines don't count as skipped

    def test_parse_comment_line(self, parser):
        """Test parsing comment line."""
        event = parser.parse_line("# This is a comment")
        assert event is None
        assert parser.lines_skipped == 0  # Comments don't count as skipped

    def test_parse_invalid_format(self, parser):
        """Test parsing invalid format (non-strict mode)."""
        line = "invalid, format, here"
        event = parser.parse_line(line)

        assert event is None
        assert parser.lines_skipped == 1
        assert len(parser.errors) == 1

    def test_parse_invalid_format_strict(self, strict_parser):
        """Test parsing invalid format (strict mode)."""
        line = "invalid, format, here"

        with pytest.raises(ValueError, match="does not match expected format"):
            strict_parser.parse_line(line)

    def test_parse_invalid_timestamp(self, parser):
        """Test parsing line with invalid timestamp."""
        line = "2024-13-99, 25:99:99, 50000000, 51000000, 1000000.00, 100, -45.2"
        event = parser.parse_line(line)

        assert event is None
        assert parser.lines_skipped == 1

    def test_parse_invalid_numbers(self, parser):
        """Test parsing line with invalid numbers."""
        line = "2024-12-09, 14:30:00, abc, def, ghi, jkl, -45.2"
        event = parser.parse_line(line)

        assert event is None
        assert parser.lines_skipped == 1

    def test_parse_no_power_readings(self, parser):
        """Test parsing line with no power readings."""
        line = "2024-12-09, 14:30:00, 50000000, 51000000, 1000000.00, 100"
        event = parser.parse_line(line)

        assert event is None
        assert parser.lines_skipped == 1

    def test_parse_stream_from_file(self, parser, sample_csv_path):
        """Test parsing stream from file."""
        with open(sample_csv_path) as f:
            events = parser.parse_stream(f)

        assert len(events) == 5
        assert parser.lines_parsed == 5
        assert parser.lines_skipped == 0

        # Verify first event
        first = events[0]
        assert first.timestamp == datetime(2024, 12, 9, 14, 30, 0)
        assert first.freq_low_hz == 50e6
        assert len(first.power_readings_db) == 3

        # Verify last event
        last = events[-1]
        assert last.freq_low_hz == 433e6
        assert len(last.power_readings_db) == 10

    def test_parse_stream_with_comments_and_blanks(self, parser):
        """Test parsing stream with comments and blank lines."""
        lines = [
            "# Comment line",
            "",
            "2024-12-09, 14:30:00, 50000000, 51000000, 1000000.00, 100, -45.2",
            "",
            "# Another comment",
            "2024-12-09, 14:30:10, 51000000, 52000000, 1000000.00, 100, -47.5",
        ]

        events = parser.parse_stream(lines)

        assert len(events) == 2
        assert parser.lines_parsed == 2
        assert parser.lines_skipped == 0

    def test_parse_stream_with_errors(self, parser):
        """Test parsing stream with some invalid lines."""
        lines = [
            "2024-12-09, 14:30:00, 50000000, 51000000, 1000000.00, 100, -45.2",
            "invalid line",
            "2024-12-09, 14:30:10, 51000000, 52000000, 1000000.00, 100, -47.5",
        ]

        events = parser.parse_stream(lines)

        assert len(events) == 2
        assert parser.lines_parsed == 2
        assert parser.lines_skipped == 1
        assert len(parser.errors) == 1

    def test_reset_stats(self, parser):
        """Test resetting parser statistics."""
        parser.parse_line("invalid")
        parser.parse_line(
            "2024-12-09, 14:30:00, 50000000, 51000000, 1000000.00, 100, -45.2"
        )

        assert parser.lines_parsed == 1
        assert parser.lines_skipped == 1
        assert len(parser.errors) > 0

        parser.reset_stats()

        assert parser.lines_parsed == 0
        assert parser.lines_skipped == 0
        assert len(parser.errors) == 0

    def test_whitespace_handling(self, parser):
        """Test handling of various whitespace in lines."""
        line = "  2024-12-09,   14:30:00,  50000000,  51000000,  1000000.00,  100,  -45.2  "
        event = parser.parse_line(line)

        assert event is not None
        assert event.freq_low_hz == 50e6

    def test_scientific_notation(self, parser):
        """Test parsing with scientific notation."""
        line = "2024-12-09, 14:30:00, 5e7, 5.1e7, 1e6, 100, -4.52e1, -4.63e1"
        event = parser.parse_line(line)

        assert event is not None
        assert event.freq_low_hz == 50e6
        assert event.freq_high_hz == 51e6
        assert event.freq_step_hz == 1e6
        assert event.power_readings_db[0] == -45.2

    def test_parse_with_partial_invalid_readings(self, parser):
        """Test parsing line where some power readings are invalid."""
        line = "2024-12-09, 14:30:00, 50000000, 51000000, 1000000.00, 100, -45.2, invalid, -46.3"
        event = parser.parse_line(line)

        # Should succeed and skip the invalid reading
        assert event is not None
        assert len(event.power_readings_db) == 2
        assert event.power_readings_db[0] == -45.2
        assert event.power_readings_db[1] == -46.3
