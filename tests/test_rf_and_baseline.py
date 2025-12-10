"""Tests for RF collection and baseline detection."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tscm.baseline import (
    compare_to_baseline,
    create_baseline,
    get_baseline_sweeps,
    store_anomalies,
)
from tscm.storage.store import SweepStore


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    store = SweepStore(db_path, enable_wal=True)
    yield store

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def sample_sweep(temp_db):
    """Create a sample sweep with RF events."""
    sweep_id = temp_db.create_sweep(
        sweep_id="test_sweep_001",
        client_name="test_client",
        site="test_site",
        room="test_room",
    )

    # Add some RF events
    events = []
    base_time = datetime.now(timezone.utc)

    # Normal background at 100 MHz: -50 dB
    for i in range(10):
        events.append({
            "event_type": "rf",
            "timestamp": base_time,
            "freq_hz": 100e6,
            "power_db": -50.0 + (i - 5) * 0.5,  # -52.5 to -47.5 dB
        })

    # Normal background at 200 MHz: -55 dB
    for i in range(10):
        events.append({
            "event_type": "rf",
            "timestamp": base_time,
            "freq_hz": 200e6,
            "power_db": -55.0 + (i - 5) * 0.3,
        })

    # Anomalous signal at 433 MHz: -30 dB (strong)
    events.append({
        "event_type": "rf",
        "timestamp": base_time,
        "freq_hz": 433e6,
        "power_db": -30.0,
    })

    temp_db.add_events_bulk(sweep_id, events)

    yield sweep_id, temp_db


class TestRFStorage:
    """Test RF event storage."""

    def test_create_sweep(self, temp_db):
        """Test creating a sweep."""
        sweep_id = temp_db.create_sweep(
            sweep_id="test_001",
            client_name="acme_corp",
            site="hq",
            room="boardroom",
        )

        assert sweep_id > 0

        # Retrieve sweep
        sweep = temp_db.get_sweep_by_id("test_001")
        assert sweep is not None
        assert sweep["client_name"] == "acme_corp"
        assert sweep["site"] == "hq"
        assert sweep["room"] == "boardroom"

    def test_add_rf_events(self, temp_db):
        """Test adding RF events."""
        sweep_id = temp_db.create_sweep(
            sweep_id="test_002",
            client_name="test",
        )

        # Add single event
        event_id = temp_db.add_event(
            sweep_db_id=sweep_id,
            event_type="rf",
            timestamp=datetime.now(timezone.utc),
            freq_hz=100e6,
            power_db=-45.5,
        )

        assert event_id > 0

        # Retrieve events
        events = temp_db.get_events(sweep_id, event_type="rf")
        assert len(events) == 1
        assert events[0]["freq_hz"] == 100e6
        assert events[0]["power_db"] == -45.5

    def test_add_events_bulk(self, temp_db):
        """Test bulk event insertion."""
        sweep_id = temp_db.create_sweep(
            sweep_id="test_003",
            client_name="test",
        )

        events = [
            {
                "event_type": "rf",
                "timestamp": datetime.now(timezone.utc),
                "freq_hz": 100e6 + i * 1e6,
                "power_db": -50.0 - i,
            }
            for i in range(100)
        ]

        count = temp_db.add_events_bulk(sweep_id, events)
        assert count == 100

        # Retrieve events
        stored_events = temp_db.get_events(sweep_id, event_type="rf", limit=200)
        assert len(stored_events) == 100


class TestAnomalyStorage:
    """Test anomaly storage."""

    def test_insert_anomaly(self, temp_db):
        """Test inserting an anomaly."""
        sweep_id = temp_db.create_sweep(
            sweep_id="test_004",
            client_name="test",
        )

        anomaly_id = temp_db.insert_anomaly(
            sweep_id=sweep_id,
            event_id=None,
            kind="freq_anomaly",
            score=0.85,
            metadata={"details": "Unusual signal detected"},
        )

        assert anomaly_id > 0

        # Retrieve anomalies
        anomalies = temp_db.get_anomalies(sweep_id)
        assert len(anomalies) == 1
        assert anomalies[0]["kind"] == "freq_anomaly"
        assert anomalies[0]["score"] == 0.85
        assert anomalies[0]["metadata"]["details"] == "Unusual signal detected"

    def test_get_anomalies_filtered(self, temp_db):
        """Test filtering anomalies."""
        sweep_id = temp_db.create_sweep(
            sweep_id="test_005",
            client_name="test",
        )

        # Add multiple anomalies
        temp_db.insert_anomaly(sweep_id, None, "type_a", 0.9)
        temp_db.insert_anomaly(sweep_id, None, "type_b", 0.7)
        temp_db.insert_anomaly(sweep_id, None, "type_a", 0.5)
        temp_db.insert_anomaly(sweep_id, None, "type_c", 0.3)

        # Filter by kind
        type_a_anomalies = temp_db.get_anomalies(sweep_id, kind="type_a")
        assert len(type_a_anomalies) == 2

        # Filter by score
        high_score = temp_db.get_anomalies(sweep_id, min_score=0.6)
        assert len(high_score) == 2


class TestBaseline:
    """Test baseline creation and comparison."""

    def test_create_baseline(self, sample_sweep):
        """Test baseline creation from sweeps."""
        sweep_id, store = sample_sweep

        baseline = create_baseline(store, [sweep_id], freq_bin_mhz=1.0)

        assert "frequencies" in baseline
        assert baseline["num_sweeps"] == 1
        assert baseline["freq_bin_mhz"] == 1.0

        # Check that we have statistics for known frequencies
        freqs = baseline["frequencies"]
        assert "100.0" in freqs or 100.0 in freqs
        assert "200.0" in freqs or 200.0 in freqs

    def test_baseline_statistics(self, sample_sweep):
        """Test baseline statistics calculation."""
        sweep_id, store = sample_sweep

        baseline = create_baseline(store, [sweep_id], freq_bin_mhz=1.0)

        # Check 100 MHz baseline (should have mean around -50 dB)
        freq_100 = baseline["frequencies"].get("100.0") or baseline["frequencies"].get(100.0)
        assert freq_100 is not None
        assert -52 < freq_100["mean_db"] < -48
        assert freq_100["stdev_db"] > 0
        assert freq_100["count"] == 10

    def test_compare_to_baseline_no_anomalies(self, sample_sweep):
        """Test comparison with no anomalies."""
        sweep_id, store = sample_sweep

        # Create baseline from same sweep
        baseline = create_baseline(store, [sweep_id], freq_bin_mhz=1.0)

        # Compare to itself (should find the anomalous 433 MHz signal)
        anomalies = compare_to_baseline(
            store,
            sweep_id,
            baseline,
            threshold_sigma=3.0,
            min_power_threshold_db=-80.0,
        )

        # Should detect the 433 MHz anomaly (unknown frequency)
        assert len(anomalies) > 0
        freq_433_anomalies = [a for a in anomalies if a["freq_hz"] == 433e6]
        assert len(freq_433_anomalies) > 0

    def test_store_anomalies(self, sample_sweep):
        """Test storing detected anomalies."""
        sweep_id, store = sample_sweep

        baseline = create_baseline(store, [sweep_id], freq_bin_mhz=1.0)
        anomalies = compare_to_baseline(store, sweep_id, baseline)

        # Store anomalies
        count = store_anomalies(store, sweep_id, anomalies)
        assert count == len(anomalies)

        # Retrieve from database
        stored = store.get_anomalies(sweep_id)
        assert len(stored) == count

    def test_get_baseline_sweeps(self, temp_db):
        """Test getting sweeps for baseline."""
        # Create multiple completed sweeps
        sweep_ids = []
        for i in range(5):
            sid = temp_db.create_sweep(
                sweep_id=f"baseline_sweep_{i}",
                client_name="baseline_client",
                site="baseline_site",
            )
            temp_db.update_sweep(sid, status="completed")
            sweep_ids.append(sid)

        # Get baseline sweeps
        result = get_baseline_sweeps(
            temp_db,
            client_name="baseline_client",
            site="baseline_site",
            days_back=30,
            min_sweeps=3,
        )

        assert len(result) == 5

    def test_baseline_save_load(self, sample_sweep, tmp_path):
        """Test saving and loading baseline."""
        from tscm.baseline import load_baseline

        sweep_id, store = sample_sweep

        baseline_file = tmp_path / "baseline.json"
        baseline = create_baseline(
            store, [sweep_id], freq_bin_mhz=1.0, output_path=baseline_file
        )

        assert baseline_file.exists()

        # Load baseline
        loaded = load_baseline(baseline_file)
        assert loaded["num_sweeps"] == baseline["num_sweeps"]
        assert loaded["freq_bin_mhz"] == baseline["freq_bin_mhz"]
        assert len(loaded["frequencies"]) == len(baseline["frequencies"])


class TestMultipleEventTypes:
    """Test storage of different event types."""

    def test_wifi_events(self, temp_db):
        """Test Wi-Fi event storage."""
        sweep_id = temp_db.create_sweep(
            sweep_id="wifi_test",
            client_name="test",
        )

        temp_db.add_event(
            sweep_db_id=sweep_id,
            event_type="wifi",
            timestamp=datetime.now(timezone.utc),
            mac_address="AA:BB:CC:DD:EE:FF",
            ssid="TestNetwork",
            signal_strength=-65.0,
        )

        events = temp_db.get_events(sweep_id, event_type="wifi")
        assert len(events) == 1
        assert events[0]["mac_address"] == "AA:BB:CC:DD:EE:FF"
        assert events[0]["ssid"] == "TestNetwork"

    def test_ble_events(self, temp_db):
        """Test BLE event storage."""
        sweep_id = temp_db.create_sweep(
            sweep_id="ble_test",
            client_name="test",
        )

        temp_db.add_event(
            sweep_db_id=sweep_id,
            event_type="ble",
            timestamp=datetime.now(timezone.utc),
            mac_address="11:22:33:44:55:66",
            signal_strength=-75.0,
        )

        events = temp_db.get_events(sweep_id, event_type="ble")
        assert len(events) == 1
        assert events[0]["mac_address"] == "11:22:33:44:55:66"

    def test_gsm_events(self, temp_db):
        """Test GSM event storage."""
        sweep_id = temp_db.create_sweep(
            sweep_id="gsm_test",
            client_name="test",
        )

        temp_db.add_event(
            sweep_db_id=sweep_id,
            event_type="gsm",
            timestamp=datetime.now(timezone.utc),
            mcc=310,
            mnc=260,
            lac=12345,
            cid=67890,
            arfcn=123,
        )

        events = temp_db.get_events(sweep_id, event_type="gsm")
        assert len(events) == 1
