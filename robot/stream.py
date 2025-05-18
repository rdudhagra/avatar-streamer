#!/usr/bin/env python3
import yaml
import os
import platform
import subprocess
import sys
import argparse

def load_config(config_path):
    """Load parameters from YAML file."""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config
    except FileNotFoundError:
        print(f"Error: Configuration file {config_path} not found.")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file: {e}")
        sys.exit(1)
        
def get_ffmpeg_command(config):
    """Generate the ffmpeg command based on config and platform."""
    width = config['video']['width']
    height = config['video']['height']
    framerate = config['video']['framerate']
    video_port = config['network']['video_port']
    operator_ip = config['network']['operator_ip']
    
    # Determine platform-specific settings
    if platform.system() == "Darwin":
        input_device = "avfoundation"
        input_option = "0"
        print("Detected macOS, using avfoundation for webcam")
    else:
        input_device = "video4linux2"
        input_option = "/dev/video0"
        print("Detected Linux/Other, using video4linux2 for webcam")
    
    # Build the ffmpeg command
    cmd = [
        "ffmpeg",
        "-f", input_device,
        "-pix_fmt", "0rgb",  # Use a compatible pixel format
        "-framerate", str(framerate),
        "-video_size", f"{width}x{height}",
        "-i", input_option,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-b:v", "1000k",
        "-minrate", "800k",
        "-maxrate", "1200k",
        "-bufsize", "1000k",
        "-g", str(framerate * 2),
        "-keyint_min", str(framerate),
        "-r", str(framerate),
        "-f", "mpegts",
        f"udp://{operator_ip}:{video_port}?pkt_size=1316"
    ]
    
    return cmd

def main():
    parser = argparse.ArgumentParser(description='Stream webcam video using ffmpeg')
    parser.add_argument('--config', default='../params.yaml', help='Path to config file')
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Get the ffmpeg command
    cmd = get_ffmpeg_command(config)
    
    # Print stream information
    print(f"Starting webcam stream with settings:")
    print(f"Resolution: {config['video']['width']}x{config['video']['height']}")
    print(f"Framerate: {config['video']['framerate']}")
    print(f"Streaming to: {config['network']['operator_ip']}:{config['network']['video_port']}")
    
    # Execute ffmpeg command
    try:
        process = subprocess.Popen(cmd)
        process.wait()
    except KeyboardInterrupt:
        print("\nStream interrupted by user. Stopping...")
        process.terminate()
    except Exception as e:
        print(f"Error running ffmpeg: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 