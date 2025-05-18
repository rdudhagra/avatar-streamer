#!/bin/bash

# Source parameters from the YAML file using a simple parser
# Extract width, height, framerate, and port from params.yaml
WIDTH=$(grep "width:" ../params.yaml | awk '{print $2}')
HEIGHT=$(grep "height:" ../params.yaml | awk '{print $2}')
FRAMERATE=$(grep "framerate:" ../params.yaml | awk '{print $2}')
VIDEO_PORT=$(grep "video_port:" ../params.yaml | awk '{print $2}')
OPERATOR_IP=$(grep "operator_ip:" ../params.yaml | awk '{print $2}' | tr -d '"')

echo "Starting webcam stream with settings:"
echo "Resolution: ${WIDTH}x${HEIGHT}"
echo "Framerate: ${FRAMERATE}"
echo "Streaming to: ${OPERATOR_IP}:${VIDEO_PORT}"

# On macOS, use avfoundation for webcam access
if [[ "$(uname)" == "Darwin" ]]; then
    echo "Detected macOS, using avfoundation"
    INPUT_DEVICE="avfoundation"
    INPUT_OPTION="0"
else
    echo "Detected Linux/Other, using video4linux2"
    INPUT_DEVICE="video4linux2"
    INPUT_OPTION="/dev/video0"
fi

# Start ffmpeg stream - robust options with low latency
ffmpeg \
  -f ${INPUT_DEVICE} \
  -pix_fmt 0rgb \
  -framerate ${FRAMERATE} \
  -video_size ${WIDTH}x${HEIGHT} \
  -i ${INPUT_OPTION} \
  -c:v libx264 \
  -preset ultrafast \
  -tune zerolatency \
  -b:v 1000k \
  -minrate 800k \
  -maxrate 1200k \
  -bufsize 1000k \
  -g $(($FRAMERATE * 2)) \
  -keyint_min ${FRAMERATE} \
  -r ${FRAMERATE} \
  -f mpegts \
  udp://${OPERATOR_IP}:${VIDEO_PORT}?pkt_size=1316