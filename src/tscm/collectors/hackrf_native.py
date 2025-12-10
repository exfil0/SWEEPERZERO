"""Native HackRF sweep collector with custom parser.

hackrf_sweep output format:
date, time, hz_low, hz_high, hz_bin_width, num_samples, dB, dB, dB, ...

Example:
2024-12-09, 14:30:00, 2400000000, 2500000000, 1000000, 100, -45.2, -46.3, -44.1, ...
"""

import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tscm.collectors.rf_parser import RTLPowerParser
from tscm.config import TSCMConfig
from tscm.storage.store import SweepStore


def run_hackrf_native_sweep(
    config: TSCMConfig,
    store: SweepStore,
    sweep_db_id: int,
    output_dir: Optional[Path] = None,
) -> bool:
    """
    Run native hackrf_sweep and parse results.

    Args:
        config: TSCM configuration
        store: Storage instance
        sweep_db_id: Database ID of sweep
        output_dir: Optional directory to save raw CSV

    Returns:
        True if successful
    """
    if not config.hackrf.enabled:
        print("HackRF is disabled in config")
        return False

    print("Running HackRF native sweeps...")

    all_success = True
    for band in config.hackrf.bands:
        print(f"\nBand: {band.label} ({band.freq_start_mhz}-{band.freq_end_mhz} MHz)")

        freq_start_hz = int(band.freq_start_mhz * 1e6)
        freq_end_hz = int(band.freq_end_mhz * 1e6)
        step_hz = int(band.step_mhz * 1e6)
        duration_sec = config.durations.rf_duration

        # Build hackrf_sweep command
        # hackrf_sweep -f start:end -w bin_width -N num_sweeps
        # We'll use -1 for continuous and use timeout for duration
        cmd = [
            "hackrf_sweep",
            "-f",
            f"{freq_start_hz//1000000}:{freq_end_hz//1000000}",  # MHz format
            "-w",
            str(step_hz),
        ]

        print(f"Running: {' '.join(cmd)}")
        print(f"Duration: {duration_sec} seconds")

        # Create output file if requested
        output_file = None
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
            output_file = output_dir / f"hackrf_sweep_{band.label}_{timestamp}.csv"

        try:
            # Run hackrf_sweep with timeout
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            # Use RTLPowerParser (hackrf_sweep has similar format)
            parser = RTLPowerParser(strict=False)
            events_batch = []
            batch_size = 100

            file_handle = None
            if output_file:
                file_handle = open(output_file, "w")

            try:
                start_time = time.time()

                # Process output line by line with timeout
                for line in process.stdout:
                    # Check timeout
                    if time.time() - start_time > duration_sec:
                        process.send_signal(signal.SIGINT)
                        break

                    # Save to file if requested
                    if file_handle:
                        file_handle.write(line)

                    # Parse line (similar to rtl_power format)
                    event = parser.parse_line(line)
                    if event is None:
                        continue

                    # Convert to database events
                    for freq_hz, power_db in event.freq_bins:
                        events_batch.append({
                            "event_type": "rf",
                            "timestamp": event.timestamp,
                            "freq_hz": freq_hz,
                            "power_db": power_db,
                            "bandwidth_hz": event.freq_step_hz,
                        })

                    # Bulk insert when batch is full
                    if len(events_batch) >= batch_size:
                        store.add_events_bulk(sweep_db_id, events_batch)
                        print(f"Stored {len(events_batch)} RF events")
                        events_batch = []

            finally:
                if file_handle:
                    file_handle.close()

                # Terminate process
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()

            # Store remaining events
            if events_batch:
                store.add_events_bulk(sweep_db_id, events_batch)
                print(f"Stored {len(events_batch)} RF events")

            # Add artifact record
            if output_file and output_file.exists():
                store.add_artifact(
                    sweep_db_id,
                    artifact_type="hackrf_sweep_csv",
                    file_path=str(output_file),
                    file_size_bytes=output_file.stat().st_size,
                    description=f"HackRF sweep {band.label} {freq_start_hz/1e6:.0f}-{freq_end_hz/1e6:.0f} MHz",
                )

            print(
                f"HackRF band {band.label} completed. "
                f"Parsed {parser.lines_parsed} lines, skipped {parser.lines_skipped}"
            )

        except FileNotFoundError:
            print("Error: hackrf_sweep not found. Install with: apt install hackrf")
            all_success = False
        except Exception as e:
            print(f"Error during HackRF sweep: {e}")
            all_success = False

    return all_success
