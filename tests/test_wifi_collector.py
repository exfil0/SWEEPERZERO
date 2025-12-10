"""Tests for Wi-Fi collector."""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from tscm.collectors.wifi import parse_airodump_csv
from tscm.config import TSCMConfig
from tscm.storage.store import SweepStore


@pytest.fixture
def sample_airodump_csv():
    """Path to sample airodump-ng CSV file."""
    return Path(__file__).parent / "fixtures" / "airodump_sample.csv"


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
        sweep_id="test_wifi_sweep",
        client_name="test_client",
        site="test_site",
        room="test_room",
    )


class TestParseAirodumpCSV:
    """Test airodump-ng CSV parsing."""

    def test_parse_sample_csv(self, sample_airodump_csv, temp_store, sweep_id):
        """Test parsing sample airodump-ng CSV."""
        event_count = parse_airodump_csv(sample_airodump_csv, temp_store, sweep_id)
        
        # Should parse 5 APs + 4 clients = 9 events
        assert event_count == 9

    def test_parse_access_points(self, sample_airodump_csv, temp_store, sweep_id):
        """Test parsing access points from CSV."""
        parse_airodump_csv(sample_airodump_csv, temp_store, sweep_id)
        
        events = temp_store.get_events(sweep_id, event_type="wifi")
        
        # Find AP events (not clients)
        ap_events = [e for e in events if not e.get("metadata", {}).get("client")]
        
        assert len(ap_events) >= 5
        
        # Find the first AP by BSSID
        first_ap = None
        for e in ap_events:
            if e["mac_address"] == "AA:BB:CC:DD:EE:01":
                first_ap = e
                break
        
        assert first_ap is not None
        assert first_ap["ssid"] == "HomeNetwork"
        assert first_ap["signal_strength"] == -45.0
        assert first_ap["metadata"]["channel"] == "6"
        assert "WPA2" in first_ap["metadata"]["encryption"]

    def test_parse_hidden_ssid(self, sample_airodump_csv, temp_store, sweep_id):
        """Test parsing AP with hidden SSID."""
        parse_airodump_csv(sample_airodump_csv, temp_store, sweep_id)
        
        events = temp_store.get_events(sweep_id, event_type="wifi")
        
        # Find the hidden SSID AP (AA:BB:CC:DD:EE:04)
        hidden_ap = None
        for e in events:
            if e["mac_address"] == "AA:BB:CC:DD:EE:04":
                hidden_ap = e
                break
        
        assert hidden_ap is not None
        assert hidden_ap["ssid"] == "(hidden)"

    def test_parse_open_network(self, sample_airodump_csv, temp_store, sweep_id):
        """Test parsing open (no encryption) network."""
        parse_airodump_csv(sample_airodump_csv, temp_store, sweep_id)
        
        events = temp_store.get_events(sweep_id, event_type="wifi")
        
        # Find the open network (AA:BB:CC:DD:EE:04)
        open_ap = None
        for e in events:
            if e["mac_address"] == "AA:BB:CC:DD:EE:04":
                open_ap = e
                break
        
        assert open_ap is not None
        assert open_ap["metadata"]["encryption"] == "Open"

    def test_parse_clients(self, sample_airodump_csv, temp_store, sweep_id):
        """Test parsing client stations from CSV."""
        parse_airodump_csv(sample_airodump_csv, temp_store, sweep_id)
        
        events = temp_store.get_events(sweep_id, event_type="wifi")
        
        # Find client events
        client_events = [e for e in events if e.get("metadata", {}).get("client")]
        
        assert len(client_events) == 4
        
        # Find the first client by MAC
        first_client = None
        for e in client_events:
            if e["mac_address"] == "11:22:33:44:55:01":
                first_client = e
                break
        
        assert first_client is not None
        assert first_client["signal_strength"] == -42.0
        assert first_client["metadata"]["associated_bssid"] == "AA:BB:CC:DD:EE:01"

    def test_parse_probed_ssids(self, sample_airodump_csv, temp_store, sweep_id):
        """Test parsing client with probed SSIDs."""
        parse_airodump_csv(sample_airodump_csv, temp_store, sweep_id)
        
        events = temp_store.get_events(sweep_id, event_type="wifi")
        
        # Find client with probed SSIDs (11:22:33:44:55:04)
        probing_client = None
        for e in events:
            if e["mac_address"] == "11:22:33:44:55:04":
                probing_client = e
                break
        
        assert probing_client is not None
        assert probing_client["ssid"] == "HomeNetwork,Guest123"
        assert probing_client["metadata"]["associated_bssid"] == "(not associated)"

    def test_parse_timestamps(self, sample_airodump_csv, temp_store, sweep_id):
        """Test timestamp parsing."""
        parse_airodump_csv(sample_airodump_csv, temp_store, sweep_id)
        
        events = temp_store.get_events(sweep_id, event_type="wifi")
        
        # Find first AP
        first_ap = None
        for e in events:
            if e["mac_address"] == "AA:BB:CC:DD:EE:01":
                first_ap = e
                break
        
        assert first_ap is not None
        # Timestamp should be the "Last time seen" value
        assert first_ap["timestamp"] == datetime(2024, 12, 9, 14, 45, 0)
        assert first_ap["metadata"]["first_seen"] == "2024-12-09 14:30:00"

    def test_parse_invalid_csv(self, temp_store, sweep_id):
        """Test parsing invalid CSV file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("Invalid CSV content\n")
            csv_path = Path(f.name)
        
        try:
            event_count = parse_airodump_csv(csv_path, temp_store, sweep_id)
            # Should handle gracefully and return 0
            assert event_count == 0
        finally:
            csv_path.unlink()

    def test_parse_empty_csv(self, temp_store, sweep_id):
        """Test parsing empty CSV file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("")
            csv_path = Path(f.name)
        
        try:
            event_count = parse_airodump_csv(csv_path, temp_store, sweep_id)
            assert event_count == 0
        finally:
            csv_path.unlink()

    def test_parse_various_signal_strengths(self, sample_airodump_csv, temp_store, sweep_id):
        """Test parsing various signal strength values."""
        parse_airodump_csv(sample_airodump_csv, temp_store, sweep_id)
        
        events = temp_store.get_events(sweep_id, event_type="wifi")
        
        # Find APs and check signal strengths
        signal_strengths = []
        for e in events:
            if not e.get("metadata", {}).get("client") and e.get("signal_strength"):
                signal_strengths.append(e["signal_strength"])
        
        # Check we have various signal levels
        assert len(signal_strengths) >= 4
        assert min(signal_strengths) < -50  # Weak signals
        assert max(signal_strengths) > -60  # Strong signals

    def test_parse_5ghz_network(self, sample_airodump_csv, temp_store, sweep_id):
        """Test parsing 5GHz network (channel 36)."""
        parse_airodump_csv(sample_airodump_csv, temp_store, sweep_id)
        
        events = temp_store.get_events(sweep_id, event_type="wifi")
        
        # Find 5GHz network
        ghz5_network = None
        for e in events:
            if e["mac_address"] == "AA:BB:CC:DD:EE:05":
                ghz5_network = e
                break
        
        assert ghz5_network is not None
        assert ghz5_network["metadata"]["channel"] == "36"
        assert ghz5_network["ssid"] == "Enterprise_5G"
