# Avatar Streamer

A system for streaming webcam video from a robot to an operator and a recorder.

## Architecture

- **Robot**: Runs locally and uses ffmpeg to stream the webcam
- **Operator**: Runs locally and uses ffplay to view the stream

## Requirements

### Host machine
- ffmpeg and ffplay installed (for streaming and viewing)

## Getting Started

1. **Start the robot stream** (in one terminal):
   ```
   cd robot
   ./run.sh
   ```
   This will start streaming your webcam using ffmpeg.

2. **Start the operator viewer** (in another terminal):
   ```
   cd operator
   ./run.sh
   ```
   This will start ffplay to receive and display the video stream.

## Configuration

All configuration is in the `params.yaml` file, including:
- Network settings (IPs and ports)
- Video settings (resolution, framerate, encoding)
- Audio settings (channels, rate, encoding)

## Troubleshooting

- If you get webcam access errors, make sure your webcam isn't being used by another application
- For Mac users, the ffmpeg command uses avfoundation for webcam access
- If the operator can't receive the stream, check if port 31577 is open in your firewall
- For lower latency, you can adjust the ffmpeg and ffplay settings in the run.sh scripts
