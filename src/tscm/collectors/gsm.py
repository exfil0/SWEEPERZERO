"""GSM collector using gr-gsm/grgsm_scanner."""

import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from tscm.config import TSCMConfig
from tscm.storage.store import SweepStore


def parse_grgsm_scanner_output(output_lines: List[str]) -> List[Dict]:
    """
    Parse grgsm_scanner output.

    grgsm_scanner format example:
    ARFCN: 123, Freq: 943.6MHz, CID: 12345, LAC: 1234, MCC: 310, MNC: 260, Pwr: -65dBm

    Args:
        output_lines: Lines from grgsm_scanner output

    Returns:
        List of GSM cell dictionaries
    """
    cells = []

    for line in output_lines:
        line = line.strip()
        if not line:
            continue

        # Parse grgsm_scanner output
        # Example: ARFCN: 123, Freq: 943.6MHz, CID: 12345, LAC: 1234, MCC: 310, MNC: 260, Pwr: -65dBm
        arfcn_match = re.search(r"ARFCN:\s*(\d+)", line)
        freq_match = re.search(r"Freq:\s*([\d.]+)MHz", line)
        cid_match = re.search(r"CID:\s*(\d+)", line)
        lac_match = re.search(r"LAC:\s*(\d+)", line)
        mcc_match = re.search(r"MCC:\s*(\d+)", line)
        mnc_match = re.search(r"MNC:\s*(\d+)", line)
        pwr_match = re.search(r"Pwr:\s*([-\d.]+)dBm", line)

        if arfcn_match:
            cell = {
                "timestamp": datetime.now(timezone.utc),
                "arfcn": int(arfcn_match.group(1)),
                "frequency_mhz": float(freq_match.group(1)) if freq_match else None,
                "cid": int(cid_match.group(1)) if cid_match else None,
                "lac": int(lac_match.group(1)) if lac_match else None,
                "mcc": int(mcc_match.group(1)) if mcc_match else None,
                "mnc": int(mnc_match.group(1)) if mnc_match else None,
                "power_dbm": float(pwr_match.group(1)) if pwr_match else None,
            }
            cells.append(cell)

    return cells


def is_allowed_operator(mcc: int, mnc: int, allowed_list: List[str]) -> bool:
    """
    Check if MCC-MNC combination is in allowed list.

    Args:
        mcc: Mobile Country Code
        mnc: Mobile Network Code
        allowed_list: List of allowed MCC-MNC strings (e.g., ["310-260", "655-01"])

    Returns:
        True if allowed or if allowed_list is empty
    """
    if not allowed_list:
        # Empty list means all operators are allowed
        return True

    mcc_mnc_str = f"{mcc}-{mnc:02d}"  # Format with leading zero for MNC
    
    # Also check without leading zero
    mcc_mnc_str_alt = f"{mcc}-{mnc}"

    return mcc_mnc_str in allowed_list or mcc_mnc_str_alt in allowed_list


def run_gsm_sweep(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
    output_dir: Optional[Path] = None,
) -> bool:
    """
    Run GSM sweep using grgsm_scanner.

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep
        output_dir: Optional directory to save raw logs

    Returns:
        True if successful
    """
    if not config.gsm.enabled:
        print("GSM collection is disabled in config")
        return False

    # Check if grgsm_scanner is available
    grgsm_path = shutil.which("grgsm_scanner")
    if not grgsm_path:
        print("grgsm_scanner not found. Install gr-gsm package.")
        return False

    duration = config.durations.gsm_duration
    device_string = config.gsm.device_string
    bands = config.gsm.bands

    print(f"Running GSM sweep with gr-gsm")
    print(f"Device: {device_string}")
    print(f"Bands: {bands}")
    print(f"Duration: {duration} seconds")

    # Create output file if directory specified
    output_file = None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
        output_file = output_dir / f"grgsm_{timestamp}.log"

    try:
        # Run grgsm_scanner
        # -d: device string
        # -b: bands to scan
        cmd = [
            "grgsm_scanner",
            "-d",
            device_string,
            "-b",
            bands,
        ]

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
        gsm_cells = parse_grgsm_scanner_output(output_lines)
        
        # Filter by allowed operators if configured
        allowed_mcc_mnc = config.gsm.allowed_mcc_mnc
        if allowed_mcc_mnc:
            print(f"Filtering by allowed operators: {allowed_mcc_mnc}")
        
        # Store cells in database
        event_count = 0
        rogue_count = 0
        
        for cell in gsm_cells:
            is_allowed = is_allowed_operator(
                cell.get("mcc", 0),
                cell.get("mnc", 0),
                allowed_mcc_mnc,
            )
            
            if not is_allowed:
                rogue_count += 1
                print(f"⚠ Potential rogue cell detected: MCC={cell.get('mcc')}, MNC={cell.get('mnc')}, ARFCN={cell.get('arfcn')}")
            
            store.add_event(
                sweep_db_id=sweep_db_id,
                event_type="gsm",
                timestamp=cell["timestamp"],
                arfcn=cell.get("arfcn"),
                mcc=cell.get("mcc"),
                mnc=cell.get("mnc"),
                lac=cell.get("lac"),
                cid=cell.get("cid"),
                signal_strength=cell.get("power_dbm"),
                metadata={
                    "frequency_mhz": cell.get("frequency_mhz"),
                    "is_allowed": is_allowed,
                    "rogue": not is_allowed,
                },
            )
            event_count += 1

        print(f"Stored {event_count} GSM cells")
        if rogue_count > 0:
            print(f"⚠ {rogue_count} potential rogue cells detected!")

        # Store artifact
        if output_file and output_file.exists():
            store.add_artifact(
                sweep_db_id,
                artifact_type="gsm_grgsm_log",
                file_path=str(output_file),
                file_size_bytes=output_file.stat().st_size,
                description=f"GSM gr-gsm scan {bands} {duration}s",
            )

        return True

    except FileNotFoundError:
        print("Error: grgsm_scanner not found")
        return False
    except KeyboardInterrupt:
        print("\nGSM sweep interrupted")
        if "process" in locals():
            process.terminate()
        return False
    except Exception as e:
        print(f"Error during GSM sweep: {e}")
        return False
