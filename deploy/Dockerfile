FROM ubuntu:22.04

LABEL maintainer="SWEEPERZERO Contributors"
LABEL description="SWEEPERZERO - Technical Surveillance Counter-Measures toolkit"

# Prevent interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    # Base tools
    git \
    build-essential \
    cmake \
    pkg-config \
    python3 \
    python3-pip \
    python3-dev \
    libusb-1.0-0-dev \
    curl \
    wget \
    # SDR/RF tools
    rtl-sdr \
    hackrf \
    gnuradio \
    # Wi-Fi tools
    aircrack-ng \
    iw \
    wireless-tools \
    # BLE tools
    bluez \
    bluez-hcidump \
    # GPS tools
    gpsd \
    gpsd-clients \
    # Cleanup
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create tscm user
RUN useradd -m -s /bin/bash tscm

# Set working directory
WORKDIR /opt/tscm

# Copy application files
COPY . /opt/tscm/

# Install Python package
RUN pip3 install --no-cache-dir -e .

# Create data directories
RUN mkdir -p /opt/tscm/data /opt/tscm/config && \
    chown -R tscm:tscm /opt/tscm

# Switch to tscm user
USER tscm

# Create default config
RUN tscm init --config /opt/tscm/config/config.yaml

# Expose volume for data
VOLUME ["/opt/tscm/data"]

# Default command
CMD ["tscm", "preflight"]

# Notes:
# - USB devices need to be passed through with --device or --privileged
# - Network mode may need to be host for Wi-Fi monitoring: --network host
# - Run with: docker run --device=/dev/bus/usb --network host sweeperzero tscm sweep --kind rf
