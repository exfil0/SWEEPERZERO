"""Orchestrator for running multiple sweep types."""

import concurrent.futures
from pathlib import Path
from typing import Dict, List

from tscm.config import TSCMConfig
from tscm.storage.store import SweepStore


def run_wifi_sweep(config: TSCMConfig, store: SweepStore, sweep_db_id: int) -> bool:
    """
    Run Wi-Fi sweep (stub implementation).

    TODO: Implement Wi-Fi capture using aircrack-ng suite.
    - Use airmon-ng to enable monitor mode
    - Use airodump-ng to capture Wi-Fi packets
    - Parse output and store events
    - Disable monitor mode after capture

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep

    Returns:
        True if successful
    """
    if not config.wifi.enabled:
        print("Wi-Fi collection is disabled in config")
        return False

    print("Wi-Fi sweep: TODO - Not yet implemented")
    print(f"  Would capture on interface: {config.wifi.interface}")
    print(f"  Duration: {config.durations.wifi_duration} seconds")

    # TODO: Implement Wi-Fi capture
    # 1. Check if airmon-ng and airodump-ng are available
    # 2. Enable monitor mode on the interface
    # 3. Run airodump-ng for the specified duration
    # 4. Parse CSV output and store Wi-Fi events (AP, clients, etc.)
    # 5. Disable monitor mode
    # 6. Store artifact reference to pcap file

    return True


def run_ble_sweep(config: TSCMConfig, store: SweepStore, sweep_db_id: int) -> bool:
    """
    Run BLE sweep (stub implementation).

    TODO: Implement BLE capture using Ubertooth.
    - Use ubertooth-btle to capture BLE advertisements
    - Parse output and extract MAC addresses
    - Store BLE events

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep

    Returns:
        True if successful
    """
    if not config.ble.enabled:
        print("BLE collection is disabled in config")
        return False

    print("BLE sweep: TODO - Not yet implemented")
    print(f"  Would use device: {config.ble.interface}")
    print(f"  Duration: {config.durations.ble_duration} seconds")

    # TODO: Implement BLE capture
    # 1. Check if ubertooth-btle or hcitool is available
    # 2. Run ubertooth-btle -f -s for specified duration
    # 3. Parse output to extract BLE advertisements and MAC addresses
    # 4. Store BLE events with MAC, RSSI, advertisement data
    # 5. Store artifact reference to raw log file

    return True


def run_gsm_sweep(config: TSCMConfig, store: SweepStore, sweep_db_id: int) -> bool:
    """
    Run GSM sweep (stub implementation).

    TODO: Implement GSM scanning using gr-gsm.
    - Use grgsm_scanner to scan GSM bands
    - Parse cell tower information
    - Store GSM events with MCC, MNC, LAC, CID, ARFCN

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep

    Returns:
        True if successful
    """
    if not config.gsm.enabled:
        print("GSM collection is disabled in config")
        return False

    print("GSM sweep: TODO - Not yet implemented")
    print(f"  Would use device: {config.gsm.device_string}")
    print(f"  Bands: {config.gsm.bands}")
    print(f"  Duration: {config.durations.gsm_duration} seconds")

    # TODO: Implement GSM scanning
    # 1. Check if grgsm_scanner is available
    # 2. Run grgsm_scanner with configured bands
    # 3. Parse output to extract cell information
    # 4. Store GSM events with MCC, MNC, LAC, CID, ARFCN, power
    # 5. Store artifact reference to raw scanner output

    return True


def run_all_sweeps(config: TSCMConfig, store: SweepStore, sweep_db_id: int) -> bool:
    """
    Orchestrate all enabled sweep types.

    Runs sweeps in parallel where feasible, honoring per-collector durations.
    RF sweeps (RTL-SDR, HackRF) can run in parallel with Wi-Fi/BLE/GSM if
    they use different hardware.

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep

    Returns:
        True if all sweeps completed successfully
    """
    from tscm.collectors.hackrf import run_hackrf_sweep

    # Determine which sweeps to run
    sweep_tasks: List[tuple] = []

    if config.rtl_sdr.enabled:
        sweep_tasks.append(("RF (RTL-SDR)", run_hackrf_sweep, config, store, sweep_db_id))

    if config.wifi.enabled:
        sweep_tasks.append(("Wi-Fi", run_wifi_sweep, config, store, sweep_db_id))

    if config.ble.enabled:
        sweep_tasks.append(("BLE", run_ble_sweep, config, store, sweep_db_id))

    if config.gsm.enabled:
        sweep_tasks.append(("GSM", run_gsm_sweep, config, store, sweep_db_id))

    if not sweep_tasks:
        print("No sweeps enabled in configuration")
        return False

    print(f"Running {len(sweep_tasks)} sweep type(s)")

    results: Dict[str, bool] = {}

    if config.parallel_sweeps and len(sweep_tasks) > 1:
        # Run sweeps in parallel
        print("Running sweeps in parallel...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(sweep_tasks)) as executor:
            future_to_name = {}
            for name, func, *args in sweep_tasks:
                future = executor.submit(func, *args)
                future_to_name[future] = name

            for future in concurrent.futures.as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    result = future.result()
                    results[name] = result
                    status = "✓" if result else "✗"
                    print(f"{status} {name} completed")
                except Exception as e:
                    print(f"✗ {name} failed: {e}")
                    results[name] = False
    else:
        # Run sweeps sequentially
        print("Running sweeps sequentially...")

        for name, func, *args in sweep_tasks:
            print(f"\nStarting {name}...")
            try:
                result = func(*args)
                results[name] = result
                status = "✓" if result else "✗"
                print(f"{status} {name} completed")
            except Exception as e:
                print(f"✗ {name} failed: {e}")
                results[name] = False

    # Summary
    print("\n" + "=" * 50)
    print("Sweep Summary:")
    for name, success in results.items():
        status = "✓ Success" if success else "✗ Failed"
        print(f"  {name}: {status}")

    # Return True if all succeeded
    return all(results.values())
