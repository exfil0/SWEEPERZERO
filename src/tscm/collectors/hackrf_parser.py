"""Parser for HackRF sweep output format.

hackrf_sweep outputs CSV lines with the following format:
date, time, hz_low, hz_high, hz_bin_width, num_samples, dB, dB, dB, ...

Example:
2024-12-09, 14:30:00, 25000000, 300000000, 1000000, 100, -45.2, -46.3, -44.1, ...

This differs from rtl_power in that hackrf_sweep has a bin_width field instead of hz_step,
and the frequency ranges are typically much wider.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple


@dataclass
class HackRFEvent:
    """Represents a parsed HackRF power measurement event."""

    timestamp: datetime
    freq_low_hz: float
    freq_high_hz: float
    bin_width_hz: float
    samples: int
    power_readings_db: List[float]

    @property
    def freq_bins(self) -> List[Tuple[float, float]]:
        """Generate list of (frequency_hz, power_db) tuples."""
        bins = []
        current_freq = self.freq_low_hz
        for power_db in self.power_readings_db:
            bins.append((current_freq, power_db))
            current_freq += self.bin_width_hz
        return bins

    @property
    def mean_power_db(self) -> float:
        """Calculate mean power across all readings."""
        if not self.power_readings_db:
            return 0.0
        return sum(self.power_readings_db) / len(self.power_readings_db)

    @property
    def max_power_db(self) -> float:
        """Get maximum power reading."""
        if not self.power_readings_db:
            return float("-inf")
        return max(self.power_readings_db)

    @property
    def min_power_db(self) -> float:
        """Get minimum power reading."""
        if not self.power_readings_db:
            return float("inf")
        return min(self.power_readings_db)


class HackRFParser:
    """Parser for hackrf_sweep CSV output."""

    # Regex to match hackrf_sweep CSV lines
    # Format: date, time, Hz low, Hz high, Hz bin_width, num_samples, dB, dB, ...
    # Supports scientific notation (e.g., 2.5e7, 3.0e8)
    LINE_PATTERN = re.compile(
        r"^(\d{4}-\d{2}-\d{2}),\s*(\d{2}:\d{2}:\d{2}),\s*"
        r"(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?),\s*(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?),\s*"
        r"(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?),\s*"
        r"(\d+),\s*(.+)$"
    )

    def __init__(self, strict: bool = False):
        """
        Initialize parser.

        Args:
            strict: If True, raise exceptions on parse errors. If False, skip bad lines.
        """
        self.strict = strict
        self.lines_parsed = 0
        self.lines_skipped = 0
        self.errors: List[str] = []

    def parse_line(self, line: str) -> Optional[HackRFEvent]:
        """
        Parse a single hackrf_sweep CSV line.

        Args:
            line: CSV line from hackrf_sweep output

        Returns:
            HackRFEvent if parsing succeeds, None if line should be skipped

        Raises:
            ValueError: If strict=True and line cannot be parsed
        """
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            return None

        match = self.LINE_PATTERN.match(line)
        if not match:
            self.lines_skipped += 1
            error_msg = f"Line does not match expected format: {line[:100]}"
            self.errors.append(error_msg)
            if self.strict:
                raise ValueError(error_msg)
            return None

        try:
            date_str, time_str, freq_low, freq_high, bin_width, samples, power_str = (
                match.groups()
            )

            # Parse timestamp
            timestamp_str = f"{date_str} {time_str}"
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

            # Parse frequencies and samples
            freq_low_hz = float(freq_low)
            freq_high_hz = float(freq_high)
            bin_width_hz = float(bin_width)
            num_samples = int(samples)

            # Parse power readings (remaining CSV fields)
            power_readings = []
            for power_field in power_str.split(","):
                power_field = power_field.strip()
                if power_field:
                    try:
                        power_readings.append(float(power_field))
                    except ValueError:
                        # Skip invalid power readings
                        continue

            if not power_readings:
                self.lines_skipped += 1
                error_msg = f"No valid power readings in line: {line[:100]}"
                self.errors.append(error_msg)
                if self.strict:
                    raise ValueError(error_msg)
                return None

            self.lines_parsed += 1
            return HackRFEvent(
                timestamp=timestamp,
                freq_low_hz=freq_low_hz,
                freq_high_hz=freq_high_hz,
                bin_width_hz=bin_width_hz,
                samples=num_samples,
                power_readings_db=power_readings,
            )

        except (ValueError, IndexError) as e:
            self.lines_skipped += 1
            error_msg = f"Error parsing line: {e} - {line[:100]}"
            self.errors.append(error_msg)
            if self.strict:
                raise ValueError(error_msg) from e
            return None

    def parse_stream(self, lines) -> List[HackRFEvent]:
        """
        Parse multiple lines from an iterable.

        Args:
            lines: Iterable of hackrf_sweep CSV lines

        Returns:
            List of successfully parsed HackRFEvent objects
        """
        events = []
        for line in lines:
            event = self.parse_line(line)
            if event is not None:
                events.append(event)
        return events

    def reset_stats(self):
        """Reset parsing statistics."""
        self.lines_parsed = 0
        self.lines_skipped = 0
        self.errors.clear()
