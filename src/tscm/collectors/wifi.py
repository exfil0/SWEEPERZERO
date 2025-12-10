"""Wi-Fi collector using airodump-ng and optional scapy capture."""

import csv
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from tscm.config import TSCMConfig
from tscm.storage.store import SweepStore


def parse_airodump_csv(csv_path: Path, store: SweepStore, sweep_db_id: int) -> int:
    """
    Parse airodump-ng CSV output and store Wi-Fi events.

    airodump-ng CSV format has two sections:
    1. Access Points (APs) with columns: BSSID, First time seen, Last time seen, channel, Speed, Privacy, Cipher, Authentication, Power, # beacons, # IV, LAN IP, ID-length, ESSID, Key
    2. Clients (stations) with columns: Station MAC, First time seen, Last time seen, Power, # packets, BSSID, Probed ESSIDs

    Args:
        csv_path: Path to airodump-ng CSV file
        store: Storage instance
        sweep_db_id: Database ID of sweep

    Returns:
        Number of events stored
    """
    event_count = 0

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Split into AP and Station sections
        # Try both Windows (CRLF) and Unix (LF) line endings
        if "\r\n\r\n" in content:
            parts = content.split("\r\n\r\n")
        else:
            parts = content.split("\n\n")
        
        if len(parts) < 2:
            print(f"Warning: Invalid airodump-ng CSV format in {csv_path}")
            return 0

        # Parse Access Points section
        ap_section = parts[0]
        ap_lines = ap_section.strip().split("\n")

        # Skip header line
        if len(ap_lines) > 1:
            reader = csv.reader(ap_lines[1:])
            for row in reader:
                if len(row) < 14:
                    continue

                bssid = row[0].strip()
                first_seen_str = row[1].strip()
                last_seen_str = row[2].strip()
                channel = row[3].strip()
                privacy = row[5].strip()
                cipher = row[6].strip()
                auth = row[7].strip()
                power = row[8].strip()
                essid = row[13].strip()

                # Parse timestamp
                try:
                    timestamp = datetime.strptime(last_seen_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    timestamp = datetime.now(timezone.utc)

                # Parse power (signal strength)
                try:
                    signal_strength = float(power)
                except ValueError:
                    signal_strength = None

                # Store as Wi-Fi event
                encryption = f"{privacy}/{cipher}/{auth}" if privacy else "Open"
                
                store.add_event(
                    sweep_db_id=sweep_db_id,
                    event_type="wifi",
                    timestamp=timestamp,
                    mac_address=bssid,
                    ssid=essid or "(hidden)",
                    signal_strength=signal_strength,
                    metadata={
                        "channel": channel,
                        "encryption": encryption,
                        "first_seen": first_seen_str,
                    },
                )
                event_count += 1

        # Parse Stations (clients) section
        if len(parts) > 1:
            station_section = parts[1]
            station_lines = station_section.strip().split("\n")

            # Skip header line
            if len(station_lines) > 1:
                reader = csv.reader(station_lines[1:])
                for row in reader:
                    if len(row) < 6:
                        continue

                    station_mac = row[0].strip()
                    first_seen_str = row[1].strip()
                    last_seen_str = row[2].strip()
                    power = row[3].strip()
                    bssid = row[5].strip()
                    # Probed ESSIDs can contain commas, so join all remaining fields
                    probed_essids = ",".join(row[6:]).strip() if len(row) > 6 else ""

                    # Parse timestamp
                    try:
                        timestamp = datetime.strptime(last_seen_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        timestamp = datetime.now(timezone.utc)

                    # Parse power
                    try:
                        signal_strength = float(power)
                    except ValueError:
                        signal_strength = None

                    # Store client event
                    store.add_event(
                        sweep_db_id=sweep_db_id,
                        event_type="wifi",
                        timestamp=timestamp,
                        mac_address=station_mac,
                        ssid=probed_essids or None,
                        signal_strength=signal_strength,
                        metadata={
                            "client": True,
                            "associated_bssid": bssid,
                            "first_seen": first_seen_str,
                        },
                    )
                    event_count += 1

    except Exception as e:
        print(f"Error parsing airodump-ng CSV: {e}")

    return event_count


def run_wifi_sweep(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
    output_dir: Optional[Path] = None,
) -> bool:
    """
    Run Wi-Fi sweep using airodump-ng.

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep
        output_dir: Optional directory to save raw captures

    Returns:
        True if successful
    """
    if not config.wifi.enabled:
        print("Wi-Fi collection is disabled in config")
        return False

    # Check if airodump-ng is available
    airodump_path = shutil.which("airodump-ng")
    if not airodump_path:
        print("airodump-ng not found. Install with: apt install aircrack-ng")
        return False

    interface = config.wifi.interface
    duration = config.durations.wifi_duration

    print(f"Running Wi-Fi sweep on interface: {interface}")
    print(f"Duration: {duration} seconds")

    # Check if interface exists
    try:
        result = subprocess.run(
            ["iwconfig", interface],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            print(f"Warning: Interface {interface} may not exist or be wireless")
    except Exception as e:
        print(f"Warning: Could not check interface: {e}")

    # Create output directory
    if output_dir is None:
        output_dir = Path("/tmp/tscm_wifi")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    output_prefix = output_dir / f"airodump_{timestamp}"

    try:
        # Run airodump-ng
        # -w: output file prefix
        # --output-format csv: CSV output only
        cmd = [
            "airodump-ng",
            "-w",
            str(output_prefix),
            "--output-format",
            "csv",
            interface,
        ]

        print(f"Running: {' '.join(cmd)}")

        # Start airodump-ng
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Let it run for the specified duration
        time.sleep(duration)

        # Terminate process
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

        # Find the CSV file (airodump-ng adds -01.csv suffix)
        csv_file = Path(f"{output_prefix}-01.csv")
        if not csv_file.exists():
            print(f"Warning: Expected CSV file not found: {csv_file}")
            return False

        # Parse CSV and store events
        print(f"Parsing Wi-Fi capture: {csv_file}")
        event_count = parse_airodump_csv(csv_file, store, sweep_db_id)
        print(f"Stored {event_count} Wi-Fi events")

        # Store artifact
        store.add_artifact(
            sweep_db_id,
            artifact_type="wifi_airodump_csv",
            file_path=str(csv_file),
            file_size_bytes=csv_file.stat().st_size,
            description=f"Wi-Fi capture {interface} {duration}s",
        )

        # Check if pcap file was created
        pcap_files = list(output_dir.glob(f"{output_prefix.name}-*.cap"))
        for pcap_file in pcap_files:
            store.add_artifact(
                sweep_db_id,
                artifact_type="wifi_pcap",
                file_path=str(pcap_file),
                file_size_bytes=pcap_file.stat().st_size,
                description=f"Wi-Fi packet capture {interface}",
            )

        return True

    except FileNotFoundError:
        print("Error: airodump-ng not found")
        return False
    except KeyboardInterrupt:
        print("\nWi-Fi sweep interrupted")
        if "process" in locals():
            process.terminate()
        return False
    except Exception as e:
        print(f"Error during Wi-Fi sweep: {e}")
        return False


def run_wifi_sweep_scapy(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
) -> bool:
    """
    Run Wi-Fi sweep using scapy for packet capture.

    This is an alternative to airodump-ng that uses scapy for capturing
    Wi-Fi management frames in monitor mode.

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep

    Returns:
        True if successful
    """
    try:
        from scapy.all import sniff, Dot11, Dot11Beacon, Dot11ProbeResp
    except ImportError:
        print("scapy not installed. Install with: pip install scapy")
        return False

    if not config.wifi.enabled:
        print("Wi-Fi collection is disabled in config")
        return False

    interface = config.wifi.interface
    duration = config.durations.wifi_duration

    print(f"Running Wi-Fi sweep with scapy on interface: {interface}")
    print(f"Duration: {duration} seconds")

    captured_aps = {}

    def packet_handler(pkt):
        """Handle captured Wi-Fi packets."""
        if pkt.haslayer(Dot11Beacon) or pkt.haslayer(Dot11ProbeResp):
            try:
                bssid = pkt[Dot11].addr2
                ssid = pkt.info.decode("utf-8", errors="ignore")
                
                # Get signal strength from RadioTap if available
                signal_strength = None
                if hasattr(pkt, "dBm_AntSignal"):
                    signal_strength = pkt.dBm_AntSignal

                # Extract channel from DS parameter set
                channel = None
                if pkt.haslayer(Dot11Beacon):
                    stats = pkt[Dot11Beacon]
                    # Try to extract channel from DS parameter set
                    # This is simplified; real implementation would parse IE fields

                # Store unique APs
                if bssid not in captured_aps:
                    captured_aps[bssid] = {
                        "ssid": ssid,
                        "signal_strength": signal_strength,
                        "channel": channel,
                        "timestamp": datetime.now(timezone.utc),
                    }

            except Exception as e:
                pass  # Skip packets with parsing errors

    try:
        # Sniff packets for specified duration
        sniff(
            iface=interface,
            prn=packet_handler,
            timeout=duration,
            store=False,
        )

        # Store captured APs as events
        event_count = 0
        for bssid, ap_info in captured_aps.items():
            store.add_event(
                sweep_db_id=sweep_db_id,
                event_type="wifi",
                timestamp=ap_info["timestamp"],
                mac_address=bssid,
                ssid=ap_info["ssid"] or "(hidden)",
                signal_strength=ap_info["signal_strength"],
                metadata={
                    "channel": ap_info["channel"],
                    "capture_method": "scapy",
                },
            )
            event_count += 1

        print(f"Stored {event_count} Wi-Fi APs captured with scapy")
        return True

    except Exception as e:
        print(f"Error during scapy Wi-Fi capture: {e}")
        return False
