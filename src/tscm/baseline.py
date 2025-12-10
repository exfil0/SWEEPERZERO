"""Baseline and anomaly detection module.

Provides baseline creation and comparison for RF sweeps to detect anomalies.
"""

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tscm.storage.store import SweepStore


def create_baseline(
    store: SweepStore,
    sweep_ids: List[int],
    freq_bin_mhz: float = 1.0,
    output_path: Optional[Path] = None,
) -> Dict:
    """
    Create RF baseline from multiple sweeps.

    Aggregates RF events from multiple sweeps to establish normal
    RF environment characteristics (mean and stddev per frequency).

    Args:
        store: Storage instance
        sweep_ids: List of sweep database IDs to include in baseline
        freq_bin_mhz: Frequency binning resolution in MHz
        output_path: Optional path to save baseline JSON

    Returns:
        Baseline dictionary with frequency statistics
    """
    print(f"Creating baseline from {len(sweep_ids)} sweeps...")

    freq_bins: Dict[float, List[float]] = {}

    # Collect RF events from all sweeps
    for sweep_id in sweep_ids:
        events = store.get_events(sweep_id, event_type="rf", limit=100000)

        for event in events:
            if event["freq_hz"] is None or event["power_db"] is None:
                continue

            # Bin frequency
            freq_mhz = event["freq_hz"] / 1e6
            freq_bin = round(freq_mhz / freq_bin_mhz) * freq_bin_mhz

            if freq_bin not in freq_bins:
                freq_bins[freq_bin] = []

            freq_bins[freq_bin].append(event["power_db"])

    # Calculate statistics per frequency bin
    baseline = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "num_sweeps": len(sweep_ids),
        "freq_bin_mhz": freq_bin_mhz,
        "frequencies": {},
    }

    for freq_bin, power_values in freq_bins.items():
        if len(power_values) < 2:
            continue  # Need at least 2 samples for statistics

        baseline["frequencies"][freq_bin] = {
            "mean_db": statistics.mean(power_values),
            "stdev_db": statistics.stdev(power_values),
            "min_db": min(power_values),
            "max_db": max(power_values),
            "count": len(power_values),
        }

    print(f"Baseline created with {len(baseline['frequencies'])} frequency bins")

    # Save to file if requested
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(baseline, f, indent=2)
        print(f"Baseline saved to {output_path}")

    return baseline


def load_baseline(baseline_path: Path) -> Dict:
    """
    Load baseline from JSON file.

    Args:
        baseline_path: Path to baseline JSON file

    Returns:
        Baseline dictionary
    """
    with open(baseline_path) as f:
        return json.load(f)


def compare_to_baseline(
    store: SweepStore,
    sweep_id: int,
    baseline: Dict,
    threshold_sigma: float = 3.0,
    min_power_threshold_db: float = -80.0,
) -> List[Dict]:
    """
    Compare sweep to baseline and detect anomalies.

    Identifies RF signals that deviate significantly from baseline.

    Args:
        store: Storage instance
        sweep_id: Database ID of sweep to compare
        baseline: Baseline dictionary from create_baseline()
        threshold_sigma: Number of standard deviations for anomaly threshold
        min_power_threshold_db: Minimum power level to consider (filter noise)

    Returns:
        List of anomaly records
    """
    print(f"Comparing sweep {sweep_id} to baseline...")

    freq_bin_mhz = baseline.get("freq_bin_mhz", 1.0)
    baseline_freqs = baseline.get("frequencies", {})

    # Get RF events for this sweep
    events = store.get_events(sweep_id, event_type="rf", limit=100000)

    anomalies = []

    for event in events:
        if event["freq_hz"] is None or event["power_db"] is None:
            continue

        power_db = event["power_db"]

        # Filter out noise floor
        if power_db < min_power_threshold_db:
            continue

        # Bin frequency
        freq_mhz = event["freq_hz"] / 1e6
        freq_bin = round(freq_mhz / freq_bin_mhz) * freq_bin_mhz

        # Check if we have baseline for this frequency
        freq_key = str(freq_bin)
        if freq_key not in baseline_freqs:
            # Unknown frequency - could be anomaly
            anomalies.append({
                "freq_hz": event["freq_hz"],
                "power_db": power_db,
                "kind": "unknown_frequency",
                "score": 0.5,  # Medium confidence
                "details": "No baseline data for this frequency",
                "event_id": event["id"],
            })
            continue

        baseline_data = baseline_freqs[freq_key]
        mean_db = baseline_data["mean_db"]
        stdev_db = baseline_data["stdev_db"]

        # Calculate deviation in standard deviations
        if stdev_db > 0:
            deviation = abs(power_db - mean_db) / stdev_db

            if deviation > threshold_sigma:
                # Significant deviation from baseline
                score = min(1.0, deviation / (threshold_sigma * 2))  # Normalize score

                anomalies.append({
                    "freq_hz": event["freq_hz"],
                    "power_db": power_db,
                    "kind": "power_anomaly",
                    "score": score,
                    "details": f"Power {power_db:.1f} dB deviates {deviation:.1f}σ from baseline {mean_db:.1f}±{stdev_db:.1f} dB",
                    "event_id": event["id"],
                    "deviation_sigma": deviation,
                })

    print(f"Found {len(anomalies)} anomalies")

    return anomalies


def store_anomalies(store: SweepStore, sweep_id: int, anomalies: List[Dict]) -> int:
    """
    Store detected anomalies in database.

    Args:
        store: Storage instance
        sweep_id: Database ID of sweep
        anomalies: List of anomaly records from compare_to_baseline()

    Returns:
        Number of anomalies stored
    """
    count = 0

    for anomaly in anomalies:
        metadata = {
            "freq_hz": anomaly.get("freq_hz"),
            "power_db": anomaly.get("power_db"),
            "details": anomaly.get("details"),
        }

        # Add any extra fields
        for key in ["deviation_sigma"]:
            if key in anomaly:
                metadata[key] = anomaly[key]

        store.insert_anomaly(
            sweep_id=sweep_id,
            event_id=anomaly.get("event_id"),
            kind=anomaly["kind"],
            score=anomaly["score"],
            metadata=metadata,
        )
        count += 1

    return count


def get_baseline_sweeps(
    store: SweepStore,
    client_name: str,
    site: Optional[str] = None,
    room: Optional[str] = None,
    days_back: int = 30,
    min_sweeps: int = 3,
) -> List[int]:
    """
    Get sweep IDs suitable for baseline creation.

    Args:
        store: Storage instance
        client_name: Client name to filter
        site: Optional site name
        room: Optional room name
        days_back: Number of days to look back
        min_sweeps: Minimum number of sweeps required

    Returns:
        List of sweep database IDs
    """
    sweeps = store.get_sweeps(
        client_name=client_name,
        site=site,
        room=room,
        limit=100,
    )

    # Filter by date
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
    recent_sweeps = [
        s for s in sweeps
        if s["start_time"] and s["start_time"].replace(tzinfo=timezone.utc) >= cutoff_date
        and s["status"] == "completed"
    ]

    sweep_ids = [s["id"] for s in recent_sweeps]

    if len(sweep_ids) < min_sweeps:
        print(
            f"Warning: Only {len(sweep_ids)} sweeps found, "
            f"minimum {min_sweeps} recommended for baseline"
        )

    return sweep_ids
