"""Wi-Fi monitoring collector using aircrack-ng suite."""

import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tscm.config import TSCMConfig
from tscm.storage.store import SweepStore


def run_wifi_sweep(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
    output_dir: Optional[Path] = None,
) -> bool:
    """
    Run Wi-Fi monitoring sweep using aircrack-ng.

    Uses airmon-ng to enable monitor mode and airodump-ng to capture
    Wi-Fi packets. Parses CSV output to extract AP and client information.

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep
        output_dir: Optional directory to save capture files

    Returns:
        True if successful
    """
    if not config.wifi.enabled:
        print("Wi-Fi collection is disabled in config")
        return False

    interface = config.wifi.interface
    duration = config.durations.wifi_duration

    print(f"Wi-Fi sweep on interface {interface} for {duration} seconds")

    # Check if tools are available
    if not shutil.which("airmon-ng"):
        print("Error: airmon-ng not found. Please install the aircrack-ng suite for your operating system.")
        return False

    # Prepare output directory
    if output_dir is None:
        output_dir = Path("/tmp/tscm_wifi")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    capture_prefix = output_dir / f"wifi_capture_{timestamp}"

    monitor_interface = None

    try:
        # Enable monitor mode
        print(f"Enabling monitor mode on {interface}...")
        result = subprocess.run(
            ["airmon-ng", "start", interface],
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Parse output to find monitor interface name (e.g., wlan0mon)
        for line in result.stdout.split("\n"):
            if "monitor mode" in line.lower() and "enabled" in line.lower():
                # Extract interface name (usually ends with 'mon')
                match = re.search(r"(\w+mon)", line)
                if match:
                    monitor_interface = match.group(1)
                    break

        if not monitor_interface:
            # Try common pattern
            monitor_interface = f"{interface}mon"

        print(f"Monitor interface: {monitor_interface}")

        # Run airodump-ng
        print(f"Capturing Wi-Fi traffic for {duration} seconds...")
        cmd = [
            "airodump-ng",
            monitor_interface,
            "-w",
            str(capture_prefix),
            "--output-format",
            "csv",
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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

        print("Wi-Fi capture completed")

        # Parse CSV output
        csv_file = Path(f"{capture_prefix}-01.csv")
        if csv_file.exists():
            events_stored = _parse_airodump_csv(csv_file, store, sweep_db_id)
            print(f"Stored {events_stored} Wi-Fi events")

            # Add artifact
            store.add_artifact(
                sweep_db_id,
                artifact_type="wifi_csv",
                file_path=str(csv_file),
                file_size_bytes=csv_file.stat().st_size,
                description=f"Wi-Fi capture CSV {interface}",
            )

            # Also track pcap if exists
            pcap_file = Path(f"{capture_prefix}-01.cap")
            if pcap_file.exists():
                store.add_artifact(
                    sweep_db_id,
                    artifact_type="wifi_pcap",
                    file_path=str(pcap_file),
                    file_size_bytes=pcap_file.stat().st_size,
                    description=f"Wi-Fi packet capture {interface}",
                )

        return True

    except FileNotFoundError as e:
        print(f"Error: Required tool not found: {e}")
        return False
    except Exception as e:
        print(f"Error during Wi-Fi sweep: {e}")
        return False
    finally:
        # Disable monitor mode
        if monitor_interface:
            print(f"Disabling monitor mode on {monitor_interface}...")
            try:
                subprocess.run(
                    ["airmon-ng", "stop", monitor_interface],
                    capture_output=True,
                    timeout=10,
                )
            except Exception as e:
                print(f"Warning: Could not disable monitor mode: {e}")


def _parse_airodump_csv(csv_path: Path, store: SweepStore, sweep_db_id: int) -> int:
    """
    Parse airodump-ng CSV output.

    Format:
    - First section: Access Points (BSSID, First time seen, Last time seen, channel, Speed, Privacy, Cipher, Authentication, Power, # beacons, # IV, LAN IP, ID-length, ESSID, Key)
    - Second section: Stations (Station MAC, First time seen, Last time seen, Power, # packets, BSSID, Probed ESSIDs)

    Args:
        csv_path: Path to airodump CSV file
        store: Storage instance
        sweep_db_id: Database ID of sweep

    Returns:
        Number of events stored
    """
    events_count = 0

    try:
        with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Split into AP and Station sections
        sections = content.split("\r\n\r\n")

        # Parse APs (first section)
        if sections:
            ap_lines = sections[0].split("\n")
            # Find header and data rows
            for i, line in enumerate(ap_lines):
                if line.strip().startswith("BSSID"):
                    # Parse AP entries
                    for ap_line in ap_lines[i + 1 :]:
                        if not ap_line.strip():
                            continue
                        try:
                            parts = [p.strip() for p in ap_line.split(",")]
                            if len(parts) >= 14:
                                bssid = parts[0]
                                power = parts[8]
                                essid = parts[13]

                                # Convert power to float
                                power_db = float(power) if power and power != "-1" else None

                                # Store event
                                store.add_event(
                                    sweep_db_id=sweep_db_id,
                                    event_type="wifi",
                                    timestamp=datetime.now(timezone.utc),
                                    mac_address=bssid,
                                    ssid=essid if essid else None,
                                    signal_strength=power_db,
                                )
                                events_count += 1
                        except (ValueError, IndexError):
                            continue
                    break

        # Parse Stations (second section if exists)
        if len(sections) > 1:
            station_lines = sections[1].split("\n")
            for i, line in enumerate(station_lines):
                if "Station MAC" in line:
                    # Parse station entries
                    for station_line in station_lines[i + 1 :]:
                        if not station_line.strip():
                            continue
                        try:
                            parts = [p.strip() for p in station_line.split(",")]
                            if len(parts) >= 6:
                                station_mac = parts[0]
                                power = parts[3]
                                bssid = parts[5]

                                power_db = float(power) if power and power != "-1" else None

                                # Store station event
                                store.add_event(
                                    sweep_db_id=sweep_db_id,
                                    event_type="wifi",
                                    timestamp=datetime.now(timezone.utc),
                                    mac_address=station_mac,
                                    signal_strength=power_db,
                                    metadata={"associated_bssid": bssid},
                                )
                                events_count += 1
                        except (ValueError, IndexError):
                            continue
                    break

    except Exception as e:
        print(f"Error parsing airodump CSV: {e}")

    return events_count
