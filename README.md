# Avatar Streamer

A system for streaming webcam video from a robot to an operator and a recorder.

## Architecture

- **Robot**: Runs locally and uses Python + ffmpeg to stream the webcam
- **Operator**: Runs locally and uses Python + OpenCV to view the stream and measure latency
- **Recorder**: Runs in Docker and can record the stream (to be implemented)

## Features

- Real-time video streaming over UDP
- Low-latency configuration for minimal delay
- Real-time latency measurement and display
- Cross-platform support (macOS, Linux)

## Requirements

### Host machine
- Conda (Miniconda or Anaconda)
- Git (for version control)

The required packages will be automatically installed in a conda environment:
- Python 3.9
- PyYAML
- ffmpeg
- OpenCV (for video processing and latency measurement)
- NumPy (for frame manipulation)

## Getting Started

1. **Clone the repository**:
   ```
   git clone <repository-url>
   cd avatar-streamer
   ```

2. **Start the robot stream** (in one terminal):
   ```
   cd robot
   ./run.sh
   ```
   This will:
   - Create a conda environment named `avatar-streamer` if it doesn't exist
   - Run the Python script that streams your webcam using ffmpeg
   - Add timestamps to the video frames for latency measurement

3. **Start the operator viewer** (in another terminal):
   ```
   cd operator
   ./run.sh
   ```
   This will:
   - Use the same conda environment
   - Run the Python script that displays the video stream using OpenCV
   - Calculate and display the real-time latency of the video feed
   - Press 'q' to quit the viewer

## Latency Measurement

The system provides real-time latency measurements by:
1. Adding timestamps to frames at the robot side
2. Reading these timestamps at the operator side
3. Calculating the time difference to determine end-to-end latency
4. Displaying this information as an overlay on the video feed

The latency measurement includes:
- Encoding time
- Network transmission time
- Decoding time
- Display processing time

## Configuration

All configuration is in the `params.yaml` file, including:
- Network settings (IPs and ports)
- Video settings (resolution, framerate, encoding)
- Audio settings (channels, rate, encoding)

## Development

### Python Scripts
- `robot/stream.py` - Handles webcam capture and streaming with timestamp overlay
- `operator/view.py` - Receives video stream, calculates latency, and displays video with latency overlay

### Shell Scripts
- `robot/run.sh` and `operator/run.sh` - Setup the conda environment and run the Python scripts

## Troubleshooting

- If you get webcam access errors, make sure your webcam isn't being used by another application
- For Mac users, the ffmpeg command uses avfoundation for webcam access
- If the operator can't receive the stream, check if port 31577 is open in your firewall
- For conda issues, try running `conda clean --all` and then try again
- If OpenCV windows don't appear, check your display settings and X11 configuration
