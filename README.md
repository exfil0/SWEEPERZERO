## 0. Scope & Assumptions

* OS: **Ubuntu 22.04 / 24.04 LTS**.
* Hardware (minimum):

  * bladeRF 2.0 (xA4/xA9/x40) for GSM decode.
  * HackRF One for fast wideband sweeping.
  * RTL-SDR for long-run power sweeps.
  * Ubertooth One for BLE.
  * Wi-Fi NIC supporting monitor mode (e.g. `wlan0`).
* You’re comfortable tweaking device strings and basic Python.

### Optional “pro kit” (nice to integrate, but not required)

* **REI MESA 2.0** – 10 kHz–6 GHz spectrum analyzer with SmartBars, Wi-Fi/Bluetooth modes and jammer/interference detection.
* **REI ANDRE** – broadband near-field detector with histogram displays and signal lists up to 12 GHz.
* **REI ORION 2.4 HX** – NLJD with digitally modulated transmit, correlated 2nd/3rd harmonics and histogram/spectrum displays.
* **REI TALAN 3.0** – line analyzer with multimeter, RF broadband detector to 8 GHz, spectrum analyzer to 85 MHz, FDR and built-in NLJD.
* **REI PSK** (Physical Search Kit) – borescope, wireless inspection camera, IR/UV tools, evidence bags, etc.
* **REI PMK-8** – speech masking kit with eight voice masking generators and 16 transducers for rapid audio-masking deployment

These augment the RF/GSM/BLE stack; the blueprint focuses on the open-source, SDR-driven core.

---

## 1. Directory layout & global config

### 1.1 Folder structure

```bash
mkdir -p ~/tscm/{bin,config,data,analysis,logs}
mkdir -p ~/tscm/data/clients
```

Data will end up like:

```text
~/tscm/data/clients/
  ACME_CORP/
    HQ/
      CEO_office/
        2025-12-09_2030Z/
          rf_hackrf_low.csv
          rf_hackrf_mid.csv
          rf_hackrf_high.csv
          rf_rtl_power.csv
          wifi_airodump-01.csv
          ble_log.txt
          gsm_scanner.raw
          gsm_cells.json
          gps.json
          notes.txt
          sweep.log
      gsm_baseline.json
      ble_baseline.json
```

### 1.2 Main config – `~/tscm/config/tscm.conf`

```bash
# Client identity
CLIENT_NAME="ACME_CORP"
BASE_DIR="$HOME/tscm/data/clients"

# Network interfaces
WIFI_IFACE="wlan0"

# GPS
GPSD_HOST="127.0.0.1"
GPSD_PORT="2947"
ENABLE_GPS=1

# Durations (seconds)
RF_DURATION=600          # HackRF sweeps
WIFI_DURATION=900        # Wi-Fi airodump
BLE_DURATION=900         # BLE ubertooth
GSM_DURATION=600         # GSM scanner

# HackRF bands: "FREQ_RANGE STEP_MHz OUT_FILE"
RF_BANDS=(
  "25M:300M:10M 5M rf_hackrf_low.csv"
  "300M:1200M:10M 5M rf_hackrf_mid.csv"
  "1200M:6000M:20M 10M rf_hackrf_high.csv"
)

# rtl_power (RTL-SDR) long sweep
ENABLE_RTL_POWER=1
RTL_POWER_ARGS="-f 50M:1700M:1M -i 10 -e 600"

# GSM (bladeRF + gr-gsm / gr-osmosdr)
ENABLE_GSM=1
GSM_DEVICE_STRING="bladerf=0"           # osmosdr device string
GSM_BANDS="EGSM900,DCS1800"            # bands for grgsm_scanner

# Allowed operators (for rogue scoring) – MCC-MNC list
# For example: South Africa Vodacom 655-01, MTN 655-10, Cell C 655-07
GSM_ALLOWED_MCC_MNC="655-01,655-07,655-10"

# BLE logical name for scripts (no system effect)
BLE_IFACE="ubertooth"
```

If you work in a different country, adjust `GSM_ALLOWED_MCC_MNC` appropriately.

---

## 2. Tooling install script

`~/tscm/bin/install_tscm_stack.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root (sudo)" >&2
  exit 1
fi

apt update

apt install -y \
  git build-essential cmake pkg-config \
  python3 python3-venv python3-pip python3-numpy python3-pandas \
  tmux screen jq sqlite3 gpsd gpsd-clients \
  curl wget net-tools

# SDR / RF tools
apt install -y \
  gnuradio \
  gqrx-sdr \
  hackrf \
  rtl-sdr \
  aircrack-ng \
  wireshark tshark tcpdump \
  bluez bluez-hcidump \
  libusb-1.0-0-dev

# Ubertooth (if available in repo; otherwise build from source)
apt install -y ubertooth || true

# GSM stack – gr-gsm (from distro; if too old, build from source separately)
apt install -y gr-gsm || true

# Python analytics
pip3 install --upgrade pip
pip3 install \
  matplotlib \
  scipy \
  scikit-learn \
  jinja2
```

Run:

```bash
sudo chmod +x ~/tscm/bin/install_tscm_stack.sh
sudo ~/tscm/bin/install_tscm_stack.sh
```

Install bladeRF drivers/FW from Nuand separately, then confirm devices:

```bash
bladeRF-cli -p
hackrf_info
rtl_test -t
ubertooth-util -v
```

---

## 3. Per-room sweep script (RF + Wi-Fi + BLE + GSM)

`~/tscm/bin/run_room_sweep.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

CONF="${TSCM_CONF:-$HOME/tscm/config/tscm.conf}"
# shellcheck disable=SC1090
source "$CONF"

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <site_name> <room_name>" >&2
  exit 1
fi

SITE="$1"
ROOM="$2"

TIMESTAMP="$(date -u +'%Y-%m-%d_%H%MZ')"
OUT_DIR="$BASE_DIR/$CLIENT_NAME/$SITE/$ROOM/$TIMESTAMP"
mkdir -p "$OUT_DIR"

LOG="$OUT_DIR/sweep.log"
touch "$LOG"

echo "[*] Client  : $CLIENT_NAME" | tee -a "$LOG"
echo "[*] Site    : $SITE"        | tee -a "$LOG"
echo "[*] Room    : $ROOM"        | tee -a "$LOG"
echo "[*] Out dir : $OUT_DIR"     | tee -a "$LOG"
echo "[*] Start   : $(date -u)"   | tee -a "$LOG"
echo | tee -a "$LOG"

run_with_timeout() {
  local seconds="$1"; shift
  local logfile="$1"; shift
  echo "[*] $*  (max ${seconds}s)" | tee -a "$LOG"
  timeout "$seconds" "$@" >>"$logfile" 2>&1 || \
    echo "[!] Command exited non-zero: $*" | tee -a "$LOG"
}

# --- GPS (optional) ---
if [[ "${ENABLE_GPS:-0}" -eq 1 ]] && command -v gpspipe >/dev/null 2>&1; then
  echo "[*] Capturing GPS..." | tee -a "$LOG"
  gpspipe -w -n 10 > "$OUT_DIR/gps.json" 2>>"$LOG" || true
fi

# --- HackRF RF sweeps ---
echo "[*] HackRF RF sweeps..." | tee -a "$LOG"
for entry in "${RF_BANDS[@]}"; do
  read -r FREQ_RANGE STEP_MHz OUT_FILE <<<"$entry"
  run_with_timeout "$RF_DURATION" "$OUT_DIR/$OUT_FILE" \
    bash -lc "hackrf_sweep -f $FREQ_RANGE -w $STEP_MHz -o /dev/stdout"
done

# --- rtl_power (RTL-SDR) ---
if [[ "${ENABLE_RTL_POWER:-0}" -eq 1 ]] && command -v rtl_power >/dev/null 2>&1; then
  echo "[*] rtl_power sweep..." | tee -a "$LOG"
  run_with_timeout "$RF_DURATION" "$OUT_DIR/rf_rtl_power.csv" \
    bash -lc "rtl_power $RTL_POWER_ARGS -"
fi

# --- Wi-Fi capture (airodump-ng) ---
echo "[*] Wi-Fi capture..." | tee -a "$LOG"
MON_IFACE="${WIFI_IFACE}mon"
sudo airmon-ng start "$WIFI_IFACE" >>"$LOG" 2>&1 || true

run_with_timeout "$WIFI_DURATION" "$OUT_DIR/wifi_airodump.log" \
  sudo airodump-ng --manufacturer --output-format csv \
       --write "$OUT_DIR/wifi_airodump" "$MON_IFACE"

sudo airmon-ng stop "$MON_IFACE" >>"$LOG" 2>&1 || true

# --- BLE capture (delegated) ---
if command -v "$HOME/tscm/bin/capture_ble_room.sh" >/dev/null 2>&1; then
  "$HOME/tscm/bin/capture_ble_room.sh" "$OUT_DIR" "$BLE_DURATION" >>"$LOG" 2>&1 || \
    echo "[!] BLE capture script failed" | tee -a "$LOG"
else
  echo "[!] BLE capture script not found; skipping" | tee -a "$LOG"
fi

# --- GSM capture (delegated) ---
if [[ "${ENABLE_GSM:-0}" -eq 1 ]] && command -v "$HOME/tscm/bin/capture_gsm_room.sh" >/dev/null 2>&1; then
  "$HOME/tscm/bin/capture_gsm_room.sh" "$OUT_DIR" "$GSM_DURATION" >>"$LOG" 2>&1 || \
    echo "[!] GSM capture script failed" | tee -a "$LOG"
fi

# --- Notes template ---
cat >"$OUT_DIR/notes.txt" <<EOF
Client:  $CLIENT_NAME
Site:    $SITE
Room:    $ROOM
Time:    $(date -u)
Observer: ______
Lat/Long: see gps.json (if present)

Physical inspection:
  - Under desks:
  - Ceiling void & lights:
  - Power outlets & adaptors:
  - Ethernet ports / hidden bridges:
  - Furniture joints:
  - TV/AV gear:
  - Telephones / VoIP / PBX:
  - Other findings:

Initial RF/GSM/BLE impressions:
  -
EOF

echo "[*] Sweep done for $SITE / $ROOM" | tee -a "$LOG"
echo "[*] Data at: $OUT_DIR" | tee -a "$LOG"
```

Make executable:

```bash
chmod +x ~/tscm/bin/run_room_sweep.sh
```

---

## 4. GSM pipeline with rogue-cell scoring (bladeRF + gr-gsm)

### 4.1 GSM capture – `~/tscm/bin/capture_gsm_room.sh`

This uses `grgsm_scanner` with the bladeRF osmosdr device string.

```bash
#!/usr/bin/env bash
set -euo pipefail

CONF="${TSCM_CONF:-$HOME/tscm/config/tscm.conf}"
# shellcheck disable=SC1090
source "$CONF"

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <out_dir> <duration_sec>" >&2
  exit 1
fi

OUT_DIR="$1"
DURATION="$2"

RAW="$OUT_DIR/gsm_scanner.raw"

if ! command -v grgsm_scanner >/dev/null 2>&1; then
  echo "[!] grgsm_scanner not found; skipping GSM"
  exit 0
fi

echo "[*] GSM capture via grgsm_scanner (device: $GSM_DEVICE_STRING)..."

export GR_GSM_DEVICE_ARGS="$GSM_DEVICE_STRING"
export GR_GSM_LNA=36
export GR_GSM_PPM=0

# Capture for a time window; scanner continues cycling bands
timeout "$DURATION" grgsm_scanner -b "$GSM_BANDS" -p 0 -g 36 \
  2>"$RAW" || true

echo "[*] GSM scanner raw output -> $RAW"

# Parse raw to JSON
python3 << 'EOF'
import json, re, sys
from pathlib import Path

out_dir = Path(sys.argv[1])
raw_path = out_dir / "gsm_scanner.raw"
text = raw_path.read_text(errors="ignore").splitlines()

# Typical grgsm_scanner lines look like:
# ARFCN: 123, Freq: 947.4 MHz, CID: 0x1234, LAC: 0x5678, MCC: 655, MNC: 01, Pwr: -70 dBm
pattern = re.compile(
    r"ARFCN:\s*(\d+),\s*Frequ:\s*([\d\.]+)\s*MHz,\s*CID:\s*(0x[0-9A-Fa-f]+|\d+),\s*LAC:\s*(0x[0-9A-Fa-f]+|\d+),\s*MCC:\s*(\d+),\s*MNC:\s*(\d+).*?Pwr:\s*([-\d]+)\s*dBm",
    re.IGNORECASE
)

cells = []
for line in text:
    m = pattern.search(line)
    if not m:
        continue
    arfcn, freq_mhz, cid, lac, mcc, mnc, pwr = m.groups()

    def parse_int(x):
        x = x.strip()
        return int(x, 16) if x.lower().startswith("0x") else int(x)

    cells.append({
        "arfcn": int(arfcn),
        "freq_mhz": float(freq_mhz),
        "cid": parse_int(cid),
        "lac": parse_int(lac),
        "mcc": int(mcc),
        "mnc": int(mnc),
        "pwr_dbm": int(pwr),
        "raw_line": line.strip(),
    })

out = out_dir / "gsm_cells.json"
out.write_text(json.dumps(cells, indent=2), encoding="utf-8")
print(f"[+] Parsed {len(cells)} cells -> {out}")
EOF
"$OUT_DIR"

echo "[*] GSM capture finished"
```

Make executable:

```bash
chmod +x ~/tscm/bin/capture_gsm_room.sh
```

### 4.2 GSM baseline – `~/tscm/analysis/gsm_build_baseline.py`

```python
#!/usr/bin/env python3
import argparse
from pathlib import Path
import json
import pandas as pd

KEY = ["mcc", "mnc", "lac", "cid", "arfcn"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sweep_dir", type=Path, help="Dir with gsm_cells.json (baseline sweep)")
    ap.add_argument("out_file", type=Path, help="Output baseline JSON")
    args = ap.parse_args()

    cells_path = args.sweep_dir / "gsm_cells.json"
    if not cells_path.exists():
        raise SystemExit(f"{cells_path} not found")

    cells = json.loads(cells_path.read_text())
    df = pd.DataFrame(cells)
    if df.empty:
        raise SystemExit("No GSM cells in baseline")

    for col in KEY:
        df[col] = df[col].astype(int)

    # Aggregate statistics per cell identity
    baseline = df.groupby(KEY, as_index=False).agg(
        mean_pwr_dbm=("pwr_dbm", "mean"),
        min_pwr_dbm=("pwr_dbm", "min"),
        max_pwr_dbm=("pwr_dbm", "max"),
        freq_mhz=("freq_mhz", "mean")
    )

    args.out_file.write_text(baseline.to_json(orient="records", indent=2), encoding="utf-8")
    print(f"[+] Baseline cells: {len(baseline)} -> {args.out_file}")

if __name__ == "__main__":
    main()
```

Usage (once per room/site):

```bash
python3 ~/tscm/analysis/gsm_build_baseline.py \
  ~/tscm/data/clients/ACME_CORP/HQ/CEO_office/2025-12-09_2030Z \
  ~/tscm/data/clients/ACME_CORP/HQ/CEO_office/gsm_baseline.json
```

### 4.3 GSM comparison + **rogue scoring** – `~/tscm/analysis/gsm_compare_to_baseline.py`

This script:

* Loads baseline and current GSM scan.
* Computes classic anomalies:

  * new cells
  * foreign MCC/MNC
  * big power deviations.
* Computes a **score 0-100** per cell for “rogue-ness”.

Heuristics:

* **new_cell** (not in baseline): +30
* **foreign_mcc_mnc** (not in allowed list): +50
* **power_delta**:

  * |Δ| ≥ 15 dB: +20
  * |Δ| ≥ 8 dB: +10
* **isolated** (only ≤2 cells for that MCC/MNC in current scan): +15
* **very_strong** (pwr_dbm > −55 dBm): +10

Score is clipped to [0, 100].

Interpretation:

* `score >= 60` → **likely rogue / hostile** (or at least warranting serious scrutiny).
* `40 ≤ score < 60` → suspicious but possibly explainable.
* `< 40` → probably normal variations.

```python
#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
from typing import Set, Tuple

import pandas as pd

KEY = ["mcc", "mnc", "lac", "cid", "arfcn"]

def parse_allowed_pairs(s: str) -> Set[Tuple[int, int]]:
    """
    Parse '655-01,655-07' into {(655,1),(655,7)}.
    """
    pairs = set()
    if not s:
        return pairs
    for token in s.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            mcc_str, mnc_str = token.split("-", 1)
            pairs.add((int(mcc_str), int(mnc_str)))
        except ValueError:
            continue
    return pairs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline_json", type=Path)
    ap.add_argument("current_dir", type=Path)
    ap.add_argument("--pwr_threshold", type=float, default=8.0,
                    help="dB threshold for power anomaly consideration")
    ap.add_argument("--allowed-mcc-mnc", type=str, default="",
                    help="Comma-separated MCC-MNC pairs (e.g. '655-01,655-07')")
    args = ap.parse_args()

    baseline = pd.read_json(args.baseline_json)
    cur_path = args.current_dir / "gsm_cells.json"
    if not cur_path.exists():
        raise SystemExit(f"{cur_path} not found")

    current = pd.read_json(cur_path)

    for col in KEY:
        baseline[col] = baseline[col].astype(int)
        current[col] = current[col].astype(int)

    # Allowed MCC/MNC pairs:
    env_allowed = os.environ.get("GSM_ALLOWED_MCC_MNC", "")
    allowed_str = args.allowed_mcc_mnc or env_allowed
    if allowed_str:
        allowed_pairs = parse_allowed_pairs(allowed_str)
    else:
        # if none provided, allow whatever we saw in baseline
        allowed_pairs = set(zip(baseline["mcc"], baseline["mnc"]))

    # Merge baseline stats into current cells
    merged = current.merge(baseline, on=KEY, how="left", suffixes=("", "_base"))

    # Precompute per-MCC/MNC cell counts in current scan
    mcc_mnc_counts = merged.groupby(["mcc", "mnc"]).size().to_dict()

    scores = []
    for idx, row in merged.iterrows():
        mcc = int(row["mcc"])
        mnc = int(row["mnc"])
        lac = int(row["lac"])
        cid = int(row["cid"])
        arfcn = int(row["arfcn"])
        pwr = float(row["pwr_dbm"])

        key = (mcc, mnc, lac, cid, arfcn)

        new_cell = pd.isna(row.get("mean_pwr_dbm"))
        foreign_pair = (mcc, mnc) not in allowed_pairs
        baseline_mean = float(row["mean_pwr_dbm"]) if not new_cell else None

        power_delta = None
        if baseline_mean is not None:
            power_delta = pwr - baseline_mean

        iso_count = mcc_mnc_counts.get((mcc, mnc), 0)
        isolated = iso_count <= 2
        very_strong = pwr > -55.0  # adjustable

        score = 0.0

        if new_cell:
            score += 30.0
        if foreign_pair:
            score += 50.0

        if power_delta is not None:
            if abs(power_delta) >= 15.0:
                score += 20.0
            elif abs(power_delta) >= args.pwr_threshold:
                score += 10.0

        if isolated:
            score += 15.0
        if very_strong:
            score += 10.0

        if score > 100.0:
            score = 100.0

        label = "normal"
        if score >= 60.0:
            label = "likely_rogue"
        elif score >= 40.0:
            label = "suspicious"

        scores.append({
            "mcc": mcc, "mnc": mnc, "lac": lac, "cid": cid, "arfcn": arfcn,
            "freq_mhz": float(row["freq_mhz"]) if not pd.isna(row.get("freq_mhz")) else None,
            "pwr_dbm": pwr,
            "baseline_mean_pwr_dbm": baseline_mean,
            "power_delta_db": power_delta,
            "new_cell": new_cell,
            "foreign_mcc_mnc": foreign_pair,
            "isolated_operator_cells": isolated,
            "very_strong": very_strong,
            "score": score,
            "label": label,
            "raw_line": row.get("raw_line", "")
        })

    out_df = pd.DataFrame(scores)
    out_df.sort_values("score", ascending=False, inplace=True)

    out_file = args.current_dir / "gsm_scored_cells.csv"
    out_df.to_csv(out_file, index=False)

    # convenience filtered views
    out_df[out_df["label"] == "likely_rogue"].to_csv(
        args.current_dir / "gsm_likely_rogue.csv", index=False
    )
    out_df[out_df["label"] == "suspicious"].to_csv(
        args.current_dir / "gsm_suspicious.csv", index=False
    )

    print(f"[+] Total cells: {len(out_df)}")
    print(f"[+] Likely rogue: {len(out_df[out_df['label']=='likely_rogue'])}")
    print(f"[+] Suspicious : {len(out_df[out_df['label']=='suspicious'])}")
    print(f"[+] Results: {out_file}")

if __name__ == "__main__":
    main()
```

Usage for a new sweep:

```bash
# ENV can carry allowed operators if you don't pass CLI flag
export GSM_ALLOWED_MCC_MNC="655-01,655-07,655-10"

python3 ~/tscm/analysis/gsm_compare_to_baseline.py \
  ~/tscm/data/clients/ACME_CORP/HQ/CEO_office/gsm_baseline.json \
  ~/tscm/data/clients/ACME_CORP/HQ/CEO_office/2025-12-11_0830Z \
  --pwr_threshold 8
```

You then look at:

* `gsm_likely_rogue.csv` – top priority follow-up.
* `gsm_suspicious.csv` – might be explained by network changes; cross-check with operator.

For each “likely_rogue” row, you can:

* Use MESA/ANDRE + directional antenna to physically hunt the transmitter.
* Compare ARFCN to local operator allocations.
* Correlate with time, presence of target, etc.

---

## 5. BLE tracker correlation with Ubertooth

### 5.1 BLE capture – `~/tscm/bin/capture_ble_room.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <out_dir> <duration_sec>" >&2
  exit 1
fi

OUT_DIR="$1"
DURATION="$2"

BLE_LOG="$OUT_DIR/ble_log.txt"

if ! command -v ubertooth-btle >/dev/null 2>&1; then
  echo "[!] ubertooth-btle not found; skipping BLE"
  exit 0
fi

echo "[*] BLE capture via Ubertooth..." >&2

# -f: follow advertising; -s full data
timeout "$DURATION" stdbuf -oL ubertooth-btle -f -s \
  | awk '{ print strftime("%Y-%m-%dT%H:%M:%SZ"), $0 }' > "$BLE_LOG" 2>/dev/null || true

echo "[*] BLE log -> $BLE_LOG" >&2
```

Make executable:

```bash
chmod +x ~/tscm/bin/capture_ble_room.sh
```

### 5.2 BLE baseline per room – `~/tscm/analysis/ble_build_baseline.py`

```python
#!/usr/bin/env python3
import argparse
from pathlib import Path
import re
import pandas as pd

LINE_RE = re.compile(
    r"^(?P<ts>\S+)\s+.+?ADV_.*?([\s\"])(?P<mac>([0-9A-F]{2}:){5}[0-9A-F]{2})([\s\"]|$)",
    re.IGNORECASE
)

def parse_ble_log(path: Path) -> pd.DataFrame:
    rows = []
    for line in path.read_text(errors="ignore").splitlines():
        m = LINE_RE.search(line)
        if not m:
            continue
        rows.append({"timestamp": m.group("ts"), "mac": m.group("mac").upper()})
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["timestamp", "mac"])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ble_log", type=Path)
    ap.add_argument("out_file", type=Path)
    args = ap.parse_args()

    df = parse_ble_log(args.ble_log)
    if df.empty:
        print("[!] No BLE frames parsed; baseline will be empty")
        args.out_file.write_text("[]", encoding="utf-8")
        return

    stats = df.groupby("mac").agg(
        seen_count=("timestamp", "count"),
        first_seen=("timestamp", "min"),
        last_seen=("timestamp", "max"),
    ).reset_index()

    args.out_file.write_text(stats.to_json(orient="records", indent=2), encoding="utf-8")
    print(f"[+] Baseline BLE MACs: {len(stats)} -> {args.out_file}")

if __name__ == "__main__":
    main()
```

Usage:

```bash
python3 ~/tscm/analysis/ble_build_baseline.py \
  ~/tscm/data/clients/ACME_CORP/HQ/CEO_office/2025-12-09_2030Z/ble_log.txt \
  ~/tscm/data/clients/ACME_CORP/HQ/CEO_office/ble_baseline.json
```

### 5.3 BLE compare + per-sweep corpus – `~/tscm/analysis/ble_compare_and_correlate.py`

```python
#!/usr/bin/env python3
import argparse
from pathlib import Path
import re
import json
import pandas as pd

LINE_RE = re.compile(
    r"^(?P<ts>\S+)\s+.+?ADV_.*?([\s\"])(?P<mac>([0-9A-F]{2}:){5}[0-9A-F]{2})([\s\"]|$)",
    re.IGNORECASE
)

def parse_ble_log(path: Path, site: str, room: str, sweep_id: str) -> pd.DataFrame:
    rows = []
    for line in path.read_text(errors="ignore").splitlines():
        m = LINE_RE.search(line)
        if not m:
            continue
        rows.append({
            "timestamp": m.group("ts"),
            "mac": m.group("mac").upper(),
            "site": site,
            "room": room,
            "sweep": sweep_id,
        })
    return pd.DataFrame(rows)

def load_baseline(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["mac", "seen_count", "first_seen", "last_seen"])
    return pd.read_json(path)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline_json", type=Path)
    ap.add_argument("current_ble_log", type=Path)
    ap.add_argument("--site", required=True)
    ap.add_argument("--room", required=True)
    ap.add_argument("--sweep_id", required=True)
    args = ap.parse_args()

    base = load_baseline(args.baseline_json)
    cur_df = parse_ble_log(args.current_ble_log, args.site, args.room, args.sweep_id)

    if cur_df.empty:
        print("[!] No BLE frames in current log")
        return

    base_macs = set(base["mac"]) if not base.empty else set()
    cur_macs = set(cur_df["mac"])

    new_macs = cur_macs - base_macs
    missing_macs = base_macs - cur_macs

    out_dir = args.current_ble_log.parent

    pd.DataFrame(sorted(new_macs), columns=["mac"]).to_csv(out_dir / "ble_new_macs.csv", index=False)
    pd.DataFrame(sorted(missing_macs), columns=["mac"]).to_csv(out_dir / "ble_missing_macs.csv", index=False)

    print(f"[+] Current unique BLE MACs: {len(cur_macs)}")
    print(f"[+] New vs baseline: {len(new_macs)}")
    print(f"[+] Missing vs baseline: {len(missing_macs)}")

    # Append to corpus (cross-room correlation)
    corpus_file = out_dir.parent / "ble_corpus.csv"
    cur_df.to_csv(corpus_file, mode="a", header=not corpus_file.exists(), index=False)
    print(f"[+] Appended {len(cur_df)} rows to corpus {corpus_file}")

if __name__ == "__main__":
    main()
```

Usage per sweep:

```bash
python3 ~/tscm/analysis/ble_compare_and_correlate.py \
  ~/tscm/data/clients/ACME_CORP/HQ/CEO_office/ble_baseline.json \
  ~/tscm/data/clients/ACME_CORP/HQ/CEO_office/2025-12-11_0830Z/ble_log.txt \
  --site HQ --room CEO_office --sweep_id 2025-12-11_0830Z
```

### 5.4 Cross-room tracker correlation – `~/tscm/analysis/ble_tracker_candidates.py`

```python
#!/usr/bin/env python3
import argparse
from pathlib import Path
import pandas as pd

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_csv", type=Path)
    ap.add_argument("--min_rooms", type=int, default=2)
    ap.add_argument("--min_sweeps", type=int, default=3)
    ap.add_argument("--min_hits", type=int, default=10)
    args = ap.parse_args()

    df = pd.read_csv(args.corpus_csv)
    grp = df.groupby("mac").agg(
        room_count=("room", lambda x: x.nunique()),
        sweep_count=("sweep", lambda x: x.nunique()),
        hit_count=("timestamp", "count"),
    ).reset_index()

    suspects = grp[
        (grp["room_count"] >= args.min_rooms) &
        (grp["sweep_count"] >= args.min_sweeps) &
        (grp["hit_count"] >= args.min_hits)
    ].sort_values(["room_count", "sweep_count", "hit_count"], ascending=False)

    print(f"[+] Candidate trackers: {len(suspects)}")
    print(suspects.head(100).to_string(index=False))

    out = args.corpus_csv.parent / "ble_tracker_candidates.csv"
    suspects.to_csv(out, index=False)
    print(f"[+] Written to {out}")

if __name__ == "__main__":
    main()
```

---

## 6. Continuous monitoring wrapper (optional)

`~/tscm/bin/run_continuous_monitor.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <site> <room>" >&2
  exit 1
fi

SITE="$1"
ROOM="$2"

INTERVAL="${INTERVAL_SECONDS:-3600}"

while true; do
  echo "[*] $(date -u) – sweep for $SITE / $ROOM"
  "$HOME/tscm/bin/run_room_sweep.sh" "$SITE" "$ROOM" || echo "[!] Sweep error"
  echo "[*] Sleeping for $INTERVAL seconds..."
  sleep "$INTERVAL"
done
```

---

## 7. Sweep summary for reporting

`~/tscm/analysis/build_sweep_summary.py`:

```python
#!/usr/bin/env python3
import argparse
from pathlib import Path
import json
import pandas as pd

def maybe_count(path: Path):
    if not path.exists():
        return None
    return len(pd.read_csv(path))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sweep_dir", type=Path)
    args = ap.parse_args()

    d = args.sweep_dir

    summary = {
        "path": str(d),
        "gsm_total_cells": None,
        "gsm_likely_rogue": None,
        "gsm_suspicious": None,
        "ble_new_macs": None,
        "ble_missing_macs": None,
    }

    gsm_scored = d / "gsm_scored_cells.csv"
    if gsm_scored.exists():
        df = pd.read_csv(gsm_scored)
        summary["gsm_total_cells"] = len(df)
        summary["gsm_likely_rogue"] = int((df["label"] == "likely_rogue").sum())
        summary["gsm_suspicious"] = int((df["label"] == "suspicious").sum())

    summary["ble_new_macs"] = maybe_count(d / "ble_new_macs.csv")
    summary["ble_missing_macs"] = maybe_count(d / "ble_missing_macs.csv")

    out = d / "sweep_summary.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
```

---

## 8. How to actually use this end-to-end

### 8.1 Baseline day (trusted environment)

1. Run a full sweep:

```bash
CLIENT_NAME="ACME_CORP" TSCM_CONF="$HOME/tscm/config/tscm.conf" \
  ~/tscm/bin/run_room_sweep.sh HQ CEO_office
```

Assume it created:

```bash
BASE_DIR=~/tscm/data/clients/ACME_CORP/HQ/CEO_office/2025-12-09_2030Z
```

2. Build GSM baseline:

```bash
python3 ~/tscm/analysis/gsm_build_baseline.py \
  "$BASE_DIR" "$BASE_DIR/../gsm_baseline.json"
```

3. Build BLE baseline:

```bash
python3 ~/tscm/analysis/ble_build_baseline.py \
  "$BASE_DIR/ble_log.txt" "$BASE_DIR/../ble_baseline.json"
```

### 8.2 Investigation day

1. Another sweep:

```bash
CUR_DIR=~/tscm/data/clients/ACME_CORP/HQ/CEO_office/2025-12-11_0830Z

TSCM_CONF="$HOME/tscm/config/tscm.conf" \
  ~/tscm/bin/run_room_sweep.sh HQ CEO_office
```

2. GSM comparison + scoring:

```bash
export GSM_ALLOWED_MCC_MNC="655-01,655-07,655-10"

python3 ~/tscm/analysis/gsm_compare_to_baseline.py \
  "$BASE_DIR/../gsm_baseline.json" \
  "$CUR_DIR" \
  --pwr_threshold 8
```

Check:

* `gsm_likely_rogue.csv` – cells that scored high.
* `gsm_suspicious.csv` – cells that need context.

3. BLE compare, update corpus:

```bash
python3 ~/tscm/analysis/ble_compare_and_correlate.py \
  "$BASE_DIR/../ble_baseline.json" \
  "$CUR_DIR/ble_log.txt" \
  --site HQ --room CEO_office --sweep_id 2025-12-11_0830Z
```

4. Build per-sweep summary:

```bash
python3 ~/tscm/analysis/build_sweep_summary.py "$CUR_DIR"
```

### 8.3 Cross-room tracker hunt

After you have several sweeps from different rooms (each `ble_compare_and_correlate.py` appended to `ble_corpus.csv` in the parent folder):

```bash
python3 ~/tscm/analysis/ble_tracker_candidates.py \
  ~/tscm/data/clients/ACME_CORP/HQ/ble_corpus.csv \
  --min_rooms 2 --min_sweeps 3 --min_hits 10
```

Review `ble_tracker_candidates.csv` for MACs that behave like trackers – appearing in multiple rooms across multiple sweeps with enough hits.
