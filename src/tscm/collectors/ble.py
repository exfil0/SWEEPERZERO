"""BLE collector using ubertooth, hcitool, or python-bleak."""

import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from tscm.config import TSCMConfig
from tscm.storage.store import SweepStore


def parse_ubertooth_output(output_lines: List[str]) -> List[Dict]:
    """
    Parse ubertooth-btle output.

    Ubertooth format example:
    systime=1702216200 freq=2402 addr=5A:3B:C1:D2:E3:F4 delta_t=100.123 rssi=-45
    <advertisement data in hex>

    Args:
        output_lines: Lines from ubertooth-btle output

    Returns:
        List of BLE event dictionaries
    """
    events = []
    current_event = None

    for line in output_lines:
        line = line.strip()
        if not line:
            continue

        # Look for header line with systime, freq, addr
        header_match = re.match(
            r"systime=(\d+)\s+freq=(\d+)\s+addr=([0-9A-Fa-f:]+)(?:\s+delta_t=([\d.]+))?\s+rssi=([-\d]+)",
            line,
        )
        
        if header_match:
            # Save previous event if exists
            if current_event:
                events.append(current_event)
            
            systime, freq, addr, delta_t, rssi = header_match.groups()
            
            current_event = {
                "timestamp": datetime.fromtimestamp(int(systime), tz=timezone.utc),
                "mac_address": addr.upper(),
                "signal_strength": float(rssi),
                "frequency": int(freq),
                "adv_data": "",
            }
        elif current_event and line:
            # Accumulate advertisement data (hex bytes)
            current_event["adv_data"] += line.replace(" ", "")

    # Save last event
    if current_event:
        events.append(current_event)

    return events


def parse_hcitool_output(output_lines: List[str]) -> List[Dict]:
    """
    Parse hcitool lescan output.

    hcitool format example:
    5A:3B:C1:D2:E3:F4 Device Name
    5A:3B:C1:D2:E3:F5 (unknown)

    Args:
        output_lines: Lines from hcitool lescan output

    Returns:
        List of BLE event dictionaries
    """
    events = []

    for line in output_lines:
        line = line.strip()
        if not line:
            continue

        # Match MAC address and optional device name
        match = re.match(r"([0-9A-Fa-f:]{17})\s+(.*)", line)
        if match:
            mac, name = match.groups()
            
            events.append({
                "timestamp": datetime.now(timezone.utc),
                "mac_address": mac.upper(),
                "device_name": name if name != "(unknown)" else None,
                "signal_strength": None,  # hcitool doesn't provide RSSI
            })

    return events


def run_ble_ubertooth(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
    output_dir: Optional[Path] = None,
) -> bool:
    """
    Run BLE sweep using Ubertooth.

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep
        output_dir: Optional directory to save raw logs

    Returns:
        True if successful
    """
    ubertooth_path = shutil.which("ubertooth-btle")
    if not ubertooth_path:
        print("ubertooth-btle not found")
        return False

    duration = config.durations.ble_duration

    print(f"Running BLE sweep with Ubertooth")
    print(f"Duration: {duration} seconds")

    # Create output file if directory specified
    output_file = None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
        output_file = output_dir / f"ubertooth_{timestamp}.log"

    try:
        # Run ubertooth-btle with following mode (-f)
        cmd = ["ubertooth-btle", "-f"]

        print(f"Running: {' '.join(cmd)}")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Collect output for specified duration
        output_lines = []
        start_time = time.time()
        
        file_handle = None
        if output_file:
            file_handle = open(output_file, "w")

        try:
            while time.time() - start_time < duration:
                line = process.stdout.readline()
                if not line:
                    break
                
                if file_handle:
                    file_handle.write(line)
                
                output_lines.append(line)
        finally:
            if file_handle:
                file_handle.close()
            
            # Terminate process
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

        # Parse output
        ble_events = parse_ubertooth_output(output_lines)
        
        # Store events in database
        event_count = 0
        for event in ble_events:
            store.add_event(
                sweep_db_id=sweep_db_id,
                event_type="ble",
                timestamp=event["timestamp"],
                mac_address=event["mac_address"],
                signal_strength=event.get("signal_strength"),
                metadata={
                    "frequency": event.get("frequency"),
                    "adv_data": event.get("adv_data"),
                    "capture_method": "ubertooth",
                },
            )
            event_count += 1

        print(f"Stored {event_count} BLE events")

        # Store artifact
        if output_file and output_file.exists():
            store.add_artifact(
                sweep_db_id,
                artifact_type="ble_ubertooth_log",
                file_path=str(output_file),
                file_size_bytes=output_file.stat().st_size,
                description=f"BLE Ubertooth capture {duration}s",
            )

        return True

    except Exception as e:
        print(f"Error during Ubertooth BLE capture: {e}")
        return False


def run_ble_hcitool(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
) -> bool:
    """
    Run BLE sweep using hcitool.

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep

    Returns:
        True if successful
    """
    hcitool_path = shutil.which("hcitool")
    if not hcitool_path:
        print("hcitool not found")
        return False

    duration = config.durations.ble_duration
    interface = config.ble.interface

    # Check if interface is hci*
    if not interface.startswith("hci"):
        print(f"Interface {interface} is not an HCI device, skipping hcitool")
        return False

    print(f"Running BLE sweep with hcitool on {interface}")
    print(f"Duration: {duration} seconds")

    try:
        # Run hcitool lescan
        cmd = ["hcitool", "-i", interface, "lescan"]

        print(f"Running: {' '.join(cmd)}")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Collect output for specified duration
        output_lines = []
        start_time = time.time()

        try:
            while time.time() - start_time < duration:
                line = process.stdout.readline()
                if not line:
                    break
                output_lines.append(line)
        finally:
            # Terminate process
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

        # Parse output
        ble_events = parse_hcitool_output(output_lines)
        
        # Store unique devices
        unique_devices = {}
        for event in ble_events:
            mac = event["mac_address"]
            if mac not in unique_devices:
                unique_devices[mac] = event

        # Store events in database
        event_count = 0
        for event in unique_devices.values():
            store.add_event(
                sweep_db_id=sweep_db_id,
                event_type="ble",
                timestamp=event["timestamp"],
                mac_address=event["mac_address"],
                signal_strength=event.get("signal_strength"),
                metadata={
                    "device_name": event.get("device_name"),
                    "capture_method": "hcitool",
                },
            )
            event_count += 1

        print(f"Stored {event_count} unique BLE devices")

        return True

    except Exception as e:
        print(f"Error during hcitool BLE scan: {e}")
        return False


def run_ble_bleak(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
) -> bool:
    """
    Run BLE sweep using python-bleak.

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep

    Returns:
        True if successful
    """
    try:
        from bleak import BleakScanner
    except ImportError:
        print("bleak not installed. Install with: pip install bleak")
        return False

    duration = config.durations.ble_duration

    print(f"Running BLE sweep with bleak")
    print(f"Duration: {duration} seconds")

    try:
        import asyncio

        async def scan_ble():
            devices = await BleakScanner.discover(timeout=duration)
            return devices

        # Run async scan
        devices = asyncio.run(scan_ble())

        # Store devices
        event_count = 0
        for device in devices:
            # Extract service UUIDs
            service_uuids = []
            if device.metadata and "uuids" in device.metadata:
                service_uuids = device.metadata["uuids"]

            store.add_event(
                sweep_db_id=sweep_db_id,
                event_type="ble",
                timestamp=datetime.now(timezone.utc),
                mac_address=device.address.upper(),
                signal_strength=device.rssi if hasattr(device, "rssi") else None,
                metadata={
                    "device_name": device.name,
                    "service_uuids": service_uuids,
                    "capture_method": "bleak",
                },
            )
            event_count += 1

        print(f"Stored {event_count} BLE devices")

        return True

    except Exception as e:
        print(f"Error during bleak BLE scan: {e}")
        return False


def run_ble_sweep(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
    output_dir: Optional[Path] = None,
) -> bool:
    """
    Run BLE sweep using available tools.

    Tries tools in order: Ubertooth, bleak, hcitool

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep
        output_dir: Optional directory to save raw logs

    Returns:
        True if successful
    """
    if not config.ble.enabled:
        print("BLE collection is disabled in config")
        return False

    interface = config.ble.interface

    # Try Ubertooth first if configured
    if interface == "ubertooth":
        if shutil.which("ubertooth-btle"):
            return run_ble_ubertooth(config, store, sweep_db_id, output_dir)
        else:
            print("Ubertooth configured but ubertooth-btle not found")

    # Try bleak (cross-platform)
    try:
        import bleak
        return run_ble_bleak(config, store, sweep_db_id)
    except ImportError:
        pass

    # Try hcitool if interface is hci*
    if interface.startswith("hci"):
        if shutil.which("hcitool"):
            return run_ble_hcitool(config, store, sweep_db_id)

    print("No BLE collection tools available")
    print("  Tried: ubertooth-btle, bleak, hcitool")
    return False
