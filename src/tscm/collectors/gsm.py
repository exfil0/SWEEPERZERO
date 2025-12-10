"""GSM scanning collector using gr-gsm."""

import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tscm.config import TSCMConfig
from tscm.storage.store import SweepStore


def run_gsm_sweep(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
    output_dir: Optional[Path] = None,
) -> bool:
    """
    Run GSM scanning sweep using gr-gsm.

    Scans configured GSM bands and detects cell towers. Can identify
    rogue base stations by comparing against allowed MCC-MNC pairs.

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep
        output_dir: Optional directory to save scan logs

    Returns:
        True if successful
    """
    if not config.gsm.enabled:
        print("GSM collection is disabled in config")
        return False

    device_string = config.gsm.device_string
    bands = config.gsm.bands
    duration = config.durations.gsm_duration

    print(f"GSM sweep on device {device_string}, bands {bands}")
    print(f"Duration: {duration} seconds")

    # Check if grgsm_scanner is available
    if not subprocess.run(["which", "grgsm_scanner"], capture_output=True).returncode == 0:
        print("Error: grgsm_scanner not found")
        print("Install gr-gsm from: https://github.com/ptrkrysik/gr-gsm")
        return False

    # Prepare output directory
    if output_dir is None:
        output_dir = Path("/tmp/tscm_gsm")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    log_file = output_dir / f"gsm_scan_{timestamp}.log"

    try:
        print("Starting GSM scan...")
        # Run grgsm_scanner
        # Format: grgsm_scanner -b BAND -d DEVICE
        cmd = [
            "grgsm_scanner",
            "-b",
            bands,
            "-d",
            device_string,
        ]

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

        print("GSM scan completed")

        # Parse log file
        events_stored = _parse_grgsm_log(log_file, store, sweep_db_id, config)
        print(f"Stored {events_stored} GSM events")

        # Add artifact
        store.add_artifact(
            sweep_db_id,
            artifact_type="gsm_log",
            file_path=str(log_file),
            file_size_bytes=log_file.stat().st_size,
            description=f"GSM scan log bands {bands}",
        )

        return True

    except Exception as e:
        print(f"Error during GSM sweep: {e}")
        return False


def _parse_grgsm_log(
    log_path: Path, store: SweepStore, sweep_db_id: int, config: TSCMConfig
) -> int:
    """
    Parse grgsm_scanner log output.

    Typical format includes:
    ARFCN: XXX, Freq: XXX.X MHz, CID: XXXXX, LAC: XXXXX, MCC: XXX, MNC: XX, PWR: -XX dBm

    Args:
        log_path: Path to gr-gsm log file
        store: Storage instance
        sweep_db_id: Database ID of sweep
        config: TSCM configuration (for allowed MCC-MNC checking)

    Returns:
        Number of events stored
    """
    events_count = 0
    allowed_mcc_mnc = set(config.gsm.allowed_mcc_mnc)

    try:
        with open(log_path, "r") as f:
            for line in f:
                # Parse GSM cell information
                # Look for patterns like:
                # ARFCN: 123, Freq: 935.4 MHz, CID: 12345, LAC: 1234, MCC: 655, MNC: 01, PWR: -75

                arfcn_match = re.search(r"ARFCN[:\s]+(\d+)", line, re.IGNORECASE)
                cid_match = re.search(r"CID[:\s]+(\d+)", line, re.IGNORECASE)
                lac_match = re.search(r"LAC[:\s]+(\d+)", line, re.IGNORECASE)
                mcc_match = re.search(r"MCC[:\s]+(\d+)", line, re.IGNORECASE)
                mnc_match = re.search(r"MNC[:\s]+(\d+)", line, re.IGNORECASE)
                power_match = re.search(r"PWR[:\s]+(-?\d+)", line, re.IGNORECASE)

                # Need at least ARFCN and one of MCC/MNC to be useful
                if arfcn_match and (mcc_match or mnc_match):
                    arfcn = int(arfcn_match.group(1))
                    mcc = int(mcc_match.group(1)) if mcc_match else None
                    mnc = int(mnc_match.group(1)) if mnc_match else None
                    lac = int(lac_match.group(1)) if lac_match else None
                    cid = int(cid_match.group(1)) if cid_match else None
                    power = float(power_match.group(1)) if power_match else None

                    # Check if this is a potentially rogue cell
                    is_rogue = False
                    if mcc is not None and mnc is not None and allowed_mcc_mnc:
                        mcc_mnc_str = f"{mcc}-{mnc:02d}"
                        if mcc_mnc_str not in allowed_mcc_mnc:
                            is_rogue = True
                            print(f"⚠ Potential rogue cell detected: MCC-MNC {mcc_mnc_str}")

                    # Prepare metadata
                    metadata = {}
                    if is_rogue:
                        metadata["is_rogue"] = True

                    # Store GSM event
                    store.add_event(
                        sweep_db_id=sweep_db_id,
                        event_type="gsm",
                        timestamp=datetime.now(timezone.utc),
                        mcc=mcc,
                        mnc=mnc,
                        lac=lac,
                        cid=cid,
                        arfcn=arfcn,
                        signal_strength=power,
                        metadata=metadata if metadata else None,
                    )
                    events_count += 1

    except Exception as e:
        print(f"Error parsing GSM log: {e}")

    return events_count
