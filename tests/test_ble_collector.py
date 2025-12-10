"""Tests for BLE collector."""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from tscm.collectors.ble import (
    parse_hcitool_output,
    parse_ubertooth_output,
)
from tscm.config import TSCMConfig
from tscm.storage.store import SweepStore


@pytest.fixture
def ubertooth_sample_log():
    """Path to sample Ubertooth log file."""
    return Path(__file__).parent / "fixtures" / "ubertooth_sample.log"


@pytest.fixture
def hcitool_sample_log():
    """Path to sample hcitool output file."""
    return Path(__file__).parent / "fixtures" / "hcitool_sample.log"


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
        sweep_id="test_ble_sweep",
        client_name="test_client",
        site="test_site",
        room="test_room",
    )


class TestParseUbertoothOutput:
    """Test Ubertooth output parsing."""

    def test_parse_sample_log(self, ubertooth_sample_log):
        """Test parsing sample Ubertooth log."""
        with open(ubertooth_sample_log) as f:
            lines = f.readlines()
        
        events = parse_ubertooth_output(lines)
        
        # Should parse 3 BLE devices
        assert len(events) == 3

    def test_parse_device_with_all_fields(self, ubertooth_sample_log):
        """Test parsing device with all fields."""
        with open(ubertooth_sample_log) as f:
            lines = f.readlines()
        
        events = parse_ubertooth_output(lines)
        
        # Check first device
        first_device = events[0]
        assert first_device["mac_address"] == "5A:3B:C1:D2:E3:F4"
        assert first_device["signal_strength"] == -45.0
        assert first_device["frequency"] == 2402
        assert first_device["timestamp"] == datetime.fromtimestamp(1702216200, tz=datetime.now().astimezone().tzinfo)
        assert len(first_device["adv_data"]) > 0

    def test_parse_advertisement_data(self, ubertooth_sample_log):
        """Test parsing advertisement data."""
        with open(ubertooth_sample_log) as f:
            lines = f.readlines()
        
        events = parse_ubertooth_output(lines)
        
        # Check first device's advertisement data
        first_device = events[0]
        # Remove spaces from hex data
        expected_data = "1EFF060001092002 1A0B3C9E089F8721 5374 78C0A80164".replace(" ", "")
        assert first_device["adv_data"] == expected_data

    def test_parse_varying_rssi(self, ubertooth_sample_log):
        """Test parsing devices with varying RSSI values."""
        with open(ubertooth_sample_log) as f:
            lines = f.readlines()
        
        events = parse_ubertooth_output(lines)
        
        rssi_values = [e["signal_strength"] for e in events]
        assert len(rssi_values) == 3
        assert rssi_values[0] == -45.0
        assert rssi_values[1] == -52.0
        assert rssi_values[2] == -38.0

    def test_parse_without_delta_t(self, ubertooth_sample_log):
        """Test parsing line without delta_t field."""
        with open(ubertooth_sample_log) as f:
            lines = f.readlines()
        
        events = parse_ubertooth_output(lines)
        
        # Third device doesn't have delta_t
        third_device = events[2]
        assert third_device["mac_address"] == "6C:5D:E4:F3:02:16"

    def test_parse_empty_input(self):
        """Test parsing empty input."""
        events = parse_ubertooth_output([])
        assert len(events) == 0

    def test_parse_invalid_lines(self):
        """Test parsing with invalid lines mixed in."""
        lines = [
            "systime=1702216200 freq=2402 addr=5A:3B:C1:D2:E3:F4 rssi=-45",
            "1E FF 06 00",
            "invalid line here",
            "systime=1702216201 freq=2404 addr=5B:4C:D3:E2:F1:05 rssi=-52",
            "02 01 06",
        ]
        
        events = parse_ubertooth_output(lines)
        
        # Should still parse 2 valid devices
        assert len(events) == 2


class TestParseHcitoolOutput:
    """Test hcitool output parsing."""

    def test_parse_sample_log(self, hcitool_sample_log):
        """Test parsing sample hcitool log."""
        with open(hcitool_sample_log) as f:
            lines = f.readlines()
        
        events = parse_hcitool_output(lines)
        
        # Should parse 5 BLE devices
        assert len(events) == 5

    def test_parse_device_with_name(self, hcitool_sample_log):
        """Test parsing device with name."""
        with open(hcitool_sample_log) as f:
            lines = f.readlines()
        
        events = parse_hcitool_output(lines)
        
        # Check first device
        first_device = events[0]
        assert first_device["mac_address"] == "5A:3B:C1:D2:E3:F4"
        assert first_device["device_name"] == "Smart Watch"
        assert first_device["signal_strength"] is None  # hcitool doesn't provide RSSI

    def test_parse_unknown_device(self, hcitool_sample_log):
        """Test parsing device marked as (unknown)."""
        with open(hcitool_sample_log) as f:
            lines = f.readlines()
        
        events = parse_hcitool_output(lines)
        
        # Find unknown device
        unknown_device = None
        for e in events:
            if e["mac_address"] == "6C:5D:E4:F3:02:16":
                unknown_device = e
                break
        
        assert unknown_device is not None
        assert unknown_device["device_name"] is None

    def test_parse_device_name_with_spaces(self, hcitool_sample_log):
        """Test parsing device names with spaces."""
        with open(hcitool_sample_log) as f:
            lines = f.readlines()
        
        events = parse_hcitool_output(lines)
        
        # Find device with space in name
        smart_watch = None
        for e in events:
            if "Smart Watch" in (e["device_name"] or ""):
                smart_watch = e
                break
        
        assert smart_watch is not None
        assert smart_watch["device_name"] == "Smart Watch"

    def test_parse_mac_addresses(self, hcitool_sample_log):
        """Test parsing MAC addresses."""
        with open(hcitool_sample_log) as f:
            lines = f.readlines()
        
        events = parse_hcitool_output(lines)
        
        macs = [e["mac_address"] for e in events]
        assert "5A:3B:C1:D2:E3:F4" in macs
        assert "5B:4C:D3:E2:F1:05" in macs
        assert "7D:6E:F5:04:13:27" in macs

    def test_parse_empty_input(self):
        """Test parsing empty input."""
        events = parse_hcitool_output([])
        assert len(events) == 0

    def test_parse_invalid_lines(self):
        """Test parsing with invalid lines."""
        lines = [
            "5A:3B:C1:D2:E3:F4 Device Name",
            "invalid line",
            "5B:4C:D3:E2:F1:05 Another Device",
            "",
            "not a mac address",
        ]
        
        events = parse_hcitool_output(lines)
        
        # Should parse only valid lines
        assert len(events) == 2

    def test_mac_address_case_normalization(self):
        """Test MAC address normalization to uppercase."""
        lines = [
            "5a:3b:c1:d2:e3:f4 Device",
        ]
        
        events = parse_hcitool_output(lines)
        
        assert events[0]["mac_address"] == "5A:3B:C1:D2:E3:F4"
