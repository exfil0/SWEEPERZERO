"""Tests for GSM collector."""

import tempfile
from pathlib import Path

import pytest

from tscm.collectors.gsm import (
    is_allowed_operator,
    parse_grgsm_scanner_output,
)
from tscm.config import TSCMConfig
from tscm.storage.store import SweepStore


@pytest.fixture
def grgsm_sample_log():
    """Path to sample grgsm_scanner log file."""
    return Path(__file__).parent / "fixtures" / "grgsm_sample.log"


@pytest.fixture
def temp_store():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    store = SweepStore(db_path, enable_wal=False)
    yield store
    
    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def sweep_id(temp_store):
    """Create a test sweep and return its ID."""
    return temp_store.create_sweep(
        sweep_id="test_gsm_sweep",
        client_name="test_client",
        site="test_site",
        room="test_room",
    )


class TestParseGrgsmScannerOutput:
    """Test grgsm_scanner output parsing."""

    def test_parse_sample_log(self, grgsm_sample_log):
        """Test parsing sample grgsm_scanner log."""
        with open(grgsm_sample_log) as f:
            lines = f.readlines()
        
        cells = parse_grgsm_scanner_output(lines)
        
        # Should parse 5 GSM cells
        assert len(cells) == 5

    def test_parse_cell_with_all_fields(self, grgsm_sample_log):
        """Test parsing cell with all fields."""
        with open(grgsm_sample_log) as f:
            lines = f.readlines()
        
        cells = parse_grgsm_scanner_output(lines)
        
        # Check first cell
        first_cell = cells[0]
        assert first_cell["arfcn"] == 123
        assert first_cell["frequency_mhz"] == 943.6
        assert first_cell["cid"] == 12345
        assert first_cell["lac"] == 1234
        assert first_cell["mcc"] == 310
        assert first_cell["mnc"] == 260
        assert first_cell["power_dbm"] == -65.0

    def test_parse_varying_power_levels(self, grgsm_sample_log):
        """Test parsing cells with varying power levels."""
        with open(grgsm_sample_log) as f:
            lines = f.readlines()
        
        cells = parse_grgsm_scanner_output(lines)
        
        power_levels = [c["power_dbm"] for c in cells]
        assert len(power_levels) == 5
        assert min(power_levels) == -72.0
        assert max(power_levels) == -55.0

    def test_parse_different_operators(self, grgsm_sample_log):
        """Test parsing cells from different operators."""
        with open(grgsm_sample_log) as f:
            lines = f.readlines()
        
        cells = parse_grgsm_scanner_output(lines)
        
        # Check for different MCC-MNC combinations
        operators = [(c["mcc"], c["mnc"]) for c in cells]
        assert (310, 260) in operators  # T-Mobile US
        assert (655, 7) in operators    # Cell C ZA
        assert (999, 99) in operators   # Invalid/rogue

    def test_parse_empty_input(self):
        """Test parsing empty input."""
        cells = parse_grgsm_scanner_output([])
        assert len(cells) == 0

    def test_parse_invalid_lines(self):
        """Test parsing with invalid lines."""
        lines = [
            "ARFCN: 123, Freq: 943.6MHz, CID: 12345, LAC: 1234, MCC: 310, MNC: 260, Pwr: -65dBm",
            "invalid line here",
            "ARFCN: 124, Freq: 943.8MHz, CID: 12346, LAC: 1234, MCC: 310, MNC: 260, Pwr: -68dBm",
            "",
            "not a valid cell",
        ]
        
        cells = parse_grgsm_scanner_output(lines)
        
        # Should parse only valid lines
        assert len(cells) == 2


class TestIsAllowedOperator:
    """Test operator filtering logic."""

    def test_allowed_operator_exact_match(self):
        """Test exact match for allowed operator."""
        allowed = ["310-260", "655-7"]
        assert is_allowed_operator(310, 260, allowed) is True
        assert is_allowed_operator(655, 7, allowed) is True

    def test_allowed_operator_with_leading_zero(self):
        """Test matching with leading zero in MNC."""
        allowed = ["310-260", "655-07"]
        assert is_allowed_operator(310, 260, allowed) is True
        assert is_allowed_operator(655, 7, allowed) is True

    def test_disallowed_operator(self):
        """Test disallowed operator."""
        allowed = ["310-260", "655-7"]
        assert is_allowed_operator(999, 99, allowed) is False
        assert is_allowed_operator(310, 410, allowed) is False

    def test_empty_allowed_list(self):
        """Test that empty allowed list allows all operators."""
        assert is_allowed_operator(310, 260, []) is True
        assert is_allowed_operator(999, 99, []) is True

    def test_multiple_allowed_operators(self):
        """Test multiple allowed operators."""
        allowed = ["310-260", "310-410", "655-1", "655-7", "655-10"]
        assert is_allowed_operator(310, 260, allowed) is True
        assert is_allowed_operator(310, 410, allowed) is True
        assert is_allowed_operator(655, 1, allowed) is True
        assert is_allowed_operator(655, 7, allowed) is True
        assert is_allowed_operator(655, 10, allowed) is True
        assert is_allowed_operator(999, 99, allowed) is False

    def test_format_variations(self):
        """Test different format variations of MCC-MNC."""
        # Test with single digit MNC
        allowed = ["655-1"]
        assert is_allowed_operator(655, 1, allowed) is True
        
        # Test with two digit MNC
        allowed = ["655-01"]
        assert is_allowed_operator(655, 1, allowed) is True
        
        # Test with three digit MNC
        allowed = ["310-260"]
        assert is_allowed_operator(310, 260, allowed) is True


class TestGSMCellValidation:
    """Test GSM cell validation and rogue detection."""

    def test_identify_rogue_cell(self, grgsm_sample_log):
        """Test identifying rogue cells."""
        with open(grgsm_sample_log) as f:
            lines = f.readlines()
        
        cells = parse_grgsm_scanner_output(lines)
        
        # Filter cells by allowed operators
        allowed = ["310-260", "655-7"]
        
        rogue_cells = []
        for cell in cells:
            if not is_allowed_operator(cell["mcc"], cell["mnc"], allowed):
                rogue_cells.append(cell)
        
        # Should identify the 999-99 cell as rogue
        assert len(rogue_cells) == 1
        assert rogue_cells[0]["mcc"] == 999
        assert rogue_cells[0]["mnc"] == 99

    def test_all_cells_allowed(self, grgsm_sample_log):
        """Test when all cells are from allowed operators."""
        with open(grgsm_sample_log) as f:
            lines = f.readlines()
        
        cells = parse_grgsm_scanner_output(lines)
        
        # Allow all operators found in sample
        allowed = ["310-260", "655-7", "999-99"]
        
        rogue_cells = []
        for cell in cells:
            if not is_allowed_operator(cell["mcc"], cell["mnc"], allowed):
                rogue_cells.append(cell)
        
        # No rogue cells should be found
        assert len(rogue_cells) == 0

    def test_all_cells_disallowed(self, grgsm_sample_log):
        """Test when all cells are from disallowed operators."""
        with open(grgsm_sample_log) as f:
            lines = f.readlines()
        
        cells = parse_grgsm_scanner_output(lines)
        
        # Allow only operators not in sample
        allowed = ["111-111", "222-222"]
        
        rogue_cells = []
        for cell in cells:
            if not is_allowed_operator(cell["mcc"], cell["mnc"], allowed):
                rogue_cells.append(cell)
        
        # All cells should be flagged as rogue
        assert len(rogue_cells) == 5
