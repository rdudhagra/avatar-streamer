#!/bin/bash

# Source parameters from the YAML file
VIDEO_PORT=$(grep "video_port:" ../params.yaml | awk '{print $2}')

echo "Starting ffplay to receive stream on port ${VIDEO_PORT}"

# Run ffplay with low-latency options
ffplay -i udp://@0.0.0.0:${VIDEO_PORT} \
  -max_delay 0 \
  -max_probe_packets 1 \
  -analyzeduration 0 \
  -flags +low_delay \
  -fflags +nobuffer 