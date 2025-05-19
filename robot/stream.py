#!/usr/bin/env python3
import yaml
import os
import platform
import subprocess
import sys
import argparse
import cv2
import numpy as np
import time
import threading
import hashlib
import zmq
import json

class VideoStreamer:
    """Captures frames with OpenCV and streams them over the network."""
    
    def __init__(self, config):
        """Initialize with configuration parameters."""
        self.config = config
        self.width = config['video']['width']
        self.height = config['video']['height']
        self.framerate = config['video']['framerate']
        self.video_port = config['network']['video_port']
        self.operator_ip = config['network']['operator_ip']
        self.running = False
        self.frame_count = 0
        self.start_time = time.time()
        self.last_fps_print = time.time()
        self.zmq_messages_sent = 0
        self.last_zmq_print = time.time()
        
        # Create pipe for passing frames to ffmpeg
        self.ffmpeg_cmd = None
        self.ffmpeg_process = None
        
        # Initialize ZeroMQ context and publisher socket
        try:
            self.zmq_context = zmq.Context()
            self.zmq_socket = self.zmq_context.socket(zmq.PUB)
            # Using a different port for ZMQ (video_port + 1)
            self.zmq_port = self.video_port + 1
            
            # Use TCP wildcard address to bind to all interfaces
            bind_address = f"tcp://*:{self.zmq_port}"
            print(f"Attempting to bind ZeroMQ publisher to {bind_address}")
            self.zmq_socket.bind(bind_address)
            
            # Set a high water mark for buffering (optional)
            self.zmq_socket.setsockopt(zmq.SNDHWM, 1000)
            
            # Set linger period to 0 means to discard unsent messages on close
            self.zmq_socket.setsockopt(zmq.LINGER, 0)
            
            print(f"ZeroMQ publisher successfully bound to port {self.zmq_port}")
            print(f"Local IP addresses for connection:")
            self._print_local_ips()
        except Exception as e:
            print(f"Error setting up ZeroMQ publisher: {e}")
            raise
            
    def _print_local_ips(self):
        """Print local IP addresses for easier configuration"""
        import socket
        try:
            # Get all local IP addresses
            hostname = socket.gethostname()
            print(f"Hostname: {hostname}")
            
            # Get IP addresses
            addresses = socket.getaddrinfo(hostname, None)
            for addr in addresses:
                ip = addr[4][0]
                if ip != '127.0.0.1' and not ip.startswith('::'):  # Skip localhost and IPv6
                    print(f"IP address: {ip}")
        except Exception as e:
            print(f"Could not determine local IP addresses: {e}")
        
    def setup_camera(self):
        """Set up the camera capture based on platform."""
        # Determine camera source based on platform
        if platform.system() == "Darwin":
            # macOS - use device 0
            camera_source = 0
            print("Detected macOS, using camera index 0")
        else:
            # Linux/Other - use device 0
            camera_source = 0
            print("Detected Linux/Other, using camera index 0")
            
        # Create video capture object
        self.cap = cv2.VideoCapture(camera_source)
        
        # Set resolution
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        
        # Set framerate
        self.cap.set(cv2.CAP_PROP_FPS, self.framerate)
        
        # Check if camera is opened
        if not self.cap.isOpened():
            print("Error: Could not open camera")
            return False
            
        # Get actual camera properties (may differ from requested)
        actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
        
        print(f"Camera initialized with resolution: {actual_width}x{actual_height}, FPS: {actual_fps}")
        return True
    
    def setup_ffmpeg(self):
        """Set up ffmpeg process for streaming the frames."""
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",  # Overwrite output file
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{self.width}x{self.height}",
            "-r", str(self.framerate),
            "-i", "-",  # Read from stdin
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-b:v", "1000k",
            "-minrate", "800k",
            "-maxrate", "1200k",
            "-bufsize", "1000k",
            "-g", str(self.framerate * 2),
            "-keyint_min", str(self.framerate),
            "-f", "mpegts",
            f"udp://{self.operator_ip}:{self.video_port}?pkt_size=1316"
        ]
        
        # Start ffmpeg process
        self.ffmpeg_process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        print(f"FFmpeg started, streaming to {self.operator_ip}:{self.video_port}")
        return True
    
    def process_frame(self, frame):
        """Process frame before sending it (can be extended)."""

        # Add a fingerprint to the frame to identify later for latency measurement
        # This fingerprint is simply a global counter that keeps increasing for each frame, looping
        # every 32 frames.
        self.frame_count = (self.frame_count + 1) % 32
        
        # Add the fingerprint to the frame as a binary code of either white or black squares.
        # The code is five squares long, and 32x32 pixels.
        frame[0:32, 0:32, :] = (self.frame_count >> 0 & 1) * 255
        frame[0:32, 32:64, :] = (self.frame_count >> 1 & 1) * 255
        frame[32:64, 0:32, :] = (self.frame_count >> 2 & 1) * 255
        frame[32:64, 32:64, :] = (self.frame_count >> 3 & 1) * 255
        frame[64:96, 0:32, :] = (self.frame_count >> 4 & 1) * 255

        # Get current timestamp with millisecond precision
        current_time = time.time()
        
        # Send frame count and timestamp over ZeroMQ
        try:
            message = {
                "frame_count": self.frame_count,
                "timestamp": current_time,
                "frame_id": int(time.time() * 1000)  # Unique ID for this frame
            }
            
            # Send as JSON string
            json_msg = json.dumps(message)
            self.zmq_socket.send_string(json_msg)
            
            # Count sent messages
            self.zmq_messages_sent += 1
            
            # Print ZMQ stats every 5 seconds
            if current_time - self.last_zmq_print >= 5.0:
                rate = self.zmq_messages_sent / (current_time - self.last_zmq_print)
                print(f"ZMQ: Sent {self.zmq_messages_sent} messages at {rate:.1f} msg/sec")
                self.zmq_messages_sent = 0
                self.last_zmq_print = current_time
                
        except Exception as e:
            print(f"Error sending ZMQ message: {e}")
        
        return frame
    
    def calculate_fps(self):
        """Calculate and print the current FPS."""
        current_time = time.time()
        elapsed = current_time - self.start_time
        
        # Print FPS every second
        if current_time - self.last_fps_print >= 1.0:
            fps = self.frame_count / elapsed
            print(f"FPS: {fps:.2f}")
            self.frame_count = 0
            self.start_time = current_time
            self.last_fps_print = current_time
    
    def start(self):
        """Start capturing and streaming."""
        self.running = True
        
        # Set up camera
        if not self.setup_camera():
            return False
            
        # Set up ffmpeg
        if not self.setup_ffmpeg():
            self.cap.release()
            return False
        
        print("Starting capture and stream...")
        print(f"ZeroMQ metrics on port: {self.zmq_port} (connect to this from viewer)")
        
        try:
            while self.running:
                # Capture frame
                ret, frame = self.cap.read()
                
                if not ret:
                    print("Error: Could not read frame from camera")
                    time.sleep(0.1)
                    continue
                
                # Process the frame (modify as needed)
                processed_frame = self.process_frame(frame)
                
                # Calculate and print FPS
                self.calculate_fps()
                
                # Send the frame to ffmpeg
                self.ffmpeg_process.stdin.write(processed_frame.tobytes())
                
        except KeyboardInterrupt:
            print("\nCapture interrupted by user")
        except Exception as e:
            print(f"Error during capture: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.stop()
            
        return True
    
    def stop(self):
        """Stop capturing and streaming."""
        self.running = False
        
        # Close ZeroMQ socket
        if hasattr(self, 'zmq_socket'):
            try:
                self.zmq_socket.close()
                print("ZeroMQ socket closed")
            except Exception as e:
                print(f"Error closing ZeroMQ socket: {e}")
        if hasattr(self, 'zmq_context'):
            try:
                self.zmq_context.term()
                print("ZeroMQ context terminated")
            except Exception as e:
                print(f"Error terminating ZeroMQ context: {e}")
        
        # Release camera
        if hasattr(self, 'cap') and self.cap.isOpened():
            self.cap.release()
            
        # Stop ffmpeg
        if hasattr(self, 'ffmpeg_process'):
            try:
                self.ffmpeg_process.stdin.close()
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait(timeout=2)
            except:
                self.ffmpeg_process.kill()
                
        print("Capture and stream stopped")

def load_config(config_path):
    """Load configuration from YAML file."""
    with open(config_path, 'r') as file:
        return yaml.safe_load(file)

def main():
    parser = argparse.ArgumentParser(description='Stream webcam video using OpenCV and ffmpeg')
    parser.add_argument('--config', default='../params.yaml', help='Path to config file')
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Print stream information
    print(f"Starting webcam stream with settings:")
    print(f"Resolution: {config['video']['width']}x{config['video']['height']}")
    print(f"Framerate: {config['video']['framerate']}")
    print(f"Streaming to: {config['network']['operator_ip']}:{config['network']['video_port']}")
    print(f"ZeroMQ metrics on port: {config['network']['video_port'] + 1}")
    
    # Create and start streamer
    streamer = VideoStreamer(config)
    
    try:
        streamer.start()
    except KeyboardInterrupt:
        print("\nStream interrupted by user. Stopping...")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if hasattr(streamer, 'stop'):
            streamer.stop()

if __name__ == "__main__":
    main() 