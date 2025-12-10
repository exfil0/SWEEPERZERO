"""Parser for rtl_power CSV output format.

rtl_power outputs CSV lines with the following format:
date, time, Hz low, Hz high, Hz step, samples, dB, dB, dB, ...

Example:
2024-12-09, 14:30:00, 50000000, 51000000, 1000000.00, 100, -45.2, -46.3, -44.1, ...
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple


@dataclass
class RFEvent:
    """Represents a parsed RF power measurement event."""

    timestamp: datetime
    freq_low_hz: float
    freq_high_hz: float
    freq_step_hz: float
    samples: int
    power_readings_db: List[float]

    @property
    def freq_bins(self) -> List[Tuple[float, float]]:
        """Generate list of (frequency_hz, power_db) tuples."""
        bins = []
        current_freq = self.freq_low_hz
        for power_db in self.power_readings_db:
            bins.append((current_freq, power_db))
            current_freq += self.freq_step_hz
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


class RTLPowerParser:
    """Parser for rtl_power CSV output."""

    # Regex to match rtl_power CSV lines
    # Format: date, time, Hz low, Hz high, Hz step, samples, dB, dB, ...
    # Supports scientific notation (e.g., 5e7, 5.1e7)
    LINE_PATTERN = re.compile(
        r"^(\d{4}-\d{2}-\d{2}),\s*(\d{2}:\d{2}:\d{2}),\s*"
        r"(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?),\s*(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?),\s*(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?),\s*"
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

    def parse_line(self, line: str) -> Optional[RFEvent]:
        """
        Parse a single rtl_power CSV line.

        Args:
            line: CSV line from rtl_power output

        Returns:
            RFEvent if parsing succeeds, None if line should be skipped

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
            date_str, time_str, freq_low, freq_high, freq_step, samples, power_str = (
                match.groups()
            )

            # Parse timestamp
            timestamp_str = f"{date_str} {time_str}"
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

            # Parse frequencies and samples
            freq_low_hz = float(freq_low)
            freq_high_hz = float(freq_high)
            freq_step_hz = float(freq_step)
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
            return RFEvent(
                timestamp=timestamp,
                freq_low_hz=freq_low_hz,
                freq_high_hz=freq_high_hz,
                freq_step_hz=freq_step_hz,
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

    def parse_stream(self, lines) -> List[RFEvent]:
        """
        Parse multiple lines from an iterable.

        Args:
            lines: Iterable of rtl_power CSV lines

        Returns:
            List of successfully parsed RFEvent objects
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
