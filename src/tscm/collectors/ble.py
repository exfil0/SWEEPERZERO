"""BLE (Bluetooth Low Energy) scanning collector using Ubertooth or hcitool."""

import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tscm.config import TSCMConfig
from tscm.storage.store import SweepStore


def run_ble_sweep(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
    output_dir: Optional[Path] = None,
) -> bool:
    """
    Run BLE scanning sweep.

    Attempts to use Ubertooth first, falls back to hcitool if available.

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep
        output_dir: Optional directory to save capture logs

    Returns:
        True if successful
    """
    if not config.ble.enabled:
        print("BLE collection is disabled in config")
        return False

    interface = config.ble.interface
    duration = config.durations.ble_duration

    print(f"BLE sweep using {interface} for {duration} seconds")

    # Try Ubertooth first
    if interface.lower() == "ubertooth":
        return _run_ubertooth_sweep(config, store, sweep_db_id, output_dir, duration)
    else:
        # Try hcitool on specified interface
        return _run_hcitool_sweep(config, store, sweep_db_id, output_dir, duration, interface)


def _run_ubertooth_sweep(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
    output_dir: Optional[Path],
    duration: int,
) -> bool:
    """Run BLE sweep using Ubertooth."""
    # Check if ubertooth-btle is available
    if not subprocess.run(["which", "ubertooth-btle"], capture_output=True).returncode == 0:
        print("Error: ubertooth-btle not found. Install with: apt install ubertooth")
        return False

    # Prepare output directory
    if output_dir is None:
        output_dir = Path("/tmp/tscm_ble")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    log_file = output_dir / f"ble_ubertooth_{timestamp}.log"

    try:
        print("Starting Ubertooth BLE capture...")
        # Run ubertooth-btle -f (follow connections) -s (sniff advertisements)
        cmd = ["ubertooth-btle", "-f", "-s"]

        with open(log_file, "w") as log:
            process = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )

            # Wait for duration
            time.sleep(duration)

            # Stop capture
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

        print("Ubertooth BLE capture completed")

        # Parse log file for BLE advertisements
        events_stored = _parse_ubertooth_log(log_file, store, sweep_db_id)
        print(f"Stored {events_stored} BLE events")

        # Add artifact
        store.add_artifact(
            sweep_db_id,
            artifact_type="ble_log",
            file_path=str(log_file),
            file_size_bytes=log_file.stat().st_size,
            description="BLE Ubertooth capture log",
        )

        return True

    except Exception as e:
        print(f"Error during Ubertooth BLE sweep: {e}")
        return False


def _run_hcitool_sweep(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
    output_dir: Optional[Path],
    duration: int,
    interface: str,
) -> bool:
    """Run BLE sweep using hcitool lescan."""
    # Check if hcitool is available
    if not subprocess.run(["which", "hcitool"], capture_output=True).returncode == 0:
        print("Error: hcitool not found. Install with: apt install bluez")
        return False

    # Prepare output directory
    if output_dir is None:
        output_dir = Path("/tmp/tscm_ble")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    log_file = output_dir / f"ble_hcitool_{timestamp}.log"

    try:
        print(f"Starting hcitool BLE scan on {interface}...")
        # Run hcitool lescan
        cmd = ["hcitool", "-i", interface, "lescan"]

        with open(log_file, "w") as log:
            process = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )

            # Wait for duration
            time.sleep(duration)

            # Stop scan
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

        print("hcitool BLE scan completed")

        # Parse log file
        events_stored = _parse_hcitool_log(log_file, store, sweep_db_id)
        print(f"Stored {events_stored} BLE events")

        # Add artifact
        store.add_artifact(
            sweep_db_id,
            artifact_type="ble_log",
            file_path=str(log_file),
            file_size_bytes=log_file.stat().st_size,
            description=f"BLE hcitool scan log {interface}",
        )

        return True

    except Exception as e:
        print(f"Error during hcitool BLE sweep: {e}")
        return False


def _parse_ubertooth_log(log_path: Path, store: SweepStore, sweep_db_id: int) -> int:
    """
    Parse Ubertooth log for BLE advertisements.

    Look for lines containing MAC addresses and advertisement data.

    Args:
        log_path: Path to Ubertooth log file
        store: Storage instance
        sweep_db_id: Database ID of sweep

    Returns:
        Number of events stored
    """
    events_count = 0
    seen_macs = set()

    try:
        with open(log_path, "r") as f:
            for line in f:
                # Look for MAC addresses in format XX:XX:XX:XX:XX:XX
                mac_matches = re.findall(r"([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})", line)

                for mac in mac_matches:
                    mac_upper = mac.upper()
                    if mac_upper not in seen_macs:
                        seen_macs.add(mac_upper)

                        # Extract RSSI if present (format: RSSI: -XX dBm)
                        rssi = None
                        rssi_match = re.search(r"RSSI[:\s]+(-?\d+)", line, re.IGNORECASE)
                        if rssi_match:
                            rssi = float(rssi_match.group(1))

                        # Store BLE event
                        store.add_event(
                            sweep_db_id=sweep_db_id,
                            event_type="ble",
                            timestamp=datetime.now(timezone.utc),
                            mac_address=mac_upper,
                            signal_strength=rssi,
                        )
                        events_count += 1

    except Exception as e:
        print(f"Error parsing Ubertooth log: {e}")

    return events_count


def _parse_hcitool_log(log_path: Path, store: SweepStore, sweep_db_id: int) -> int:
    """
    Parse hcitool lescan log.

    Format: XX:XX:XX:XX:XX:XX Device Name

    Args:
        log_path: Path to hcitool log file
        store: Storage instance
        sweep_db_id: Database ID of sweep

    Returns:
        Number of events stored
    """
    events_count = 0
    seen_macs = set()

    try:
        with open(log_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("LE Scan"):
                    continue

                # Parse format: XX:XX:XX:XX:XX:XX (Device Name)
                match = re.match(
                    r"([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})\s*(.*)",
                    line,
                )
                if match:
                    mac = match.group(1).upper()
                    device_name = match.group(2).strip() if match.group(2) else None

                    if mac not in seen_macs:
                        seen_macs.add(mac)

                        # Store BLE event
                        metadata = {}
                        if device_name:
                            metadata["device_name"] = device_name

                        store.add_event(
                            sweep_db_id=sweep_db_id,
                            event_type="ble",
                            timestamp=datetime.now(timezone.utc),
                            mac_address=mac,
                            metadata=metadata if metadata else None,
                        )
                        events_count += 1

    except Exception as e:
        print(f"Error parsing hcitool log: {e}")

    return events_count
