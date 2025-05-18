#!/usr/bin/env python3
import yaml
import os
import subprocess
import sys
import argparse
import cv2
import numpy as np
import time
from threading import Thread
import queue
import signal

class LatencyCalculator:
    """Class to track video stream latency."""
    
    def __init__(self):
        self.last_latencies = []  # Store last few latency values for smoothing
        self.max_samples = 10     # Number of samples to keep for averaging
        self.last_time = time.time()
    
    def calculate_latency(self):
        """Calculate network latency based on frame arrival time."""
        current_time = time.time()
        frame_time_diff = (current_time - self.last_time) * 1000  # ms
        self.last_time = current_time
        
        # Store frame timing information
        # This is not true latency but frame timing info
        # We use this to monitor network performance
        latency_ms = 1000 / frame_time_diff if frame_time_diff > 0 else 0
        
        # Add to history and keep only the latest samples
        self.last_latencies.append(latency_ms)
        if len(self.last_latencies) > self.max_samples:
            self.last_latencies.pop(0)
            
        # Calculate average latency
        if self.last_latencies:
            avg_latency = sum(self.last_latencies) / len(self.last_latencies)
            return avg_latency
        return 0

class VideoStreamReceiver:
    """Class to receive video stream and display it."""
    
    def __init__(self, config):
        self.config = config
        self.video_port = config['network']['video_port']
        self.width = config['video']['width']
        self.height = config['video']['height']
        self.running = False
        self.frame_count = 0
        self.start_time = time.time()
        self.latency_calc = LatencyCalculator()
        self.frame_queue = queue.Queue(maxsize=10)
        
    def start(self):
        """Start receiving and displaying the video stream."""
        self.running = True
        
        # Start ffplay in a new process and pipe its output to a named pipe
        # Use external ffmpeg for decoding only (not binding to the port)
        ffmpeg_cmd = [
            'ffmpeg',
            '-i', f'udp://@127.0.0.1:{self.video_port}?timeout=1000000&fifo_size=1000000',
            '-f', 'rawvideo',
            '-pix_fmt', 'bgr24',
            '-vsync', '0',
            '-flags', 'low_delay',
            '-fflags', 'nobuffer+discardcorrupt',
            '-'
        ]
        
        # Start ffmpeg process with unbuffered output for maximum responsiveness
        self.ffmpeg_process = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=10**8  # Large buffer to handle video data
        )
        
        # Start the frame reader thread
        self.reader_thread = Thread(target=self._read_frames)
        self.reader_thread.daemon = True
        self.reader_thread.start()
        
        # Start display loop
        self._display_loop()
        
    def _read_frames(self):
        """Read frames from ffmpeg output."""
        frame_size = self.width * self.height * 3  # 3 bytes per pixel (BGR)
        
        while self.running:
            try:
                # Read raw frame data
                raw_frame = self.ffmpeg_process.stdout.read(frame_size)
                
                if len(raw_frame) == frame_size:
                    # Convert to numpy array
                    frame = np.frombuffer(raw_frame, np.uint8).reshape((self.height, self.width, 3))

                    # Copy to make writable
                    frame = np.array(frame)
                    
                    # Put in queue if not full
                    if not self.frame_queue.full():
                        self.frame_queue.put(frame)
                else:
                    # If we can't read a full frame, sleep a bit
                    time.sleep(0.001)
            except Exception as e:
                print(f"Error reading frame: {e}")
                time.sleep(0.1)
        
    def _display_loop(self):
        """Display frames with FPS counter."""
        last_time = time.time()
        fps = 0
        window_name = 'Avatar Operator Viewer'
        
        # Create window and set properties
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        
        try:
            while self.running:
                try:
                    # Try to get a frame with timeout
                    frame = self.frame_queue.get(timeout=1.0)
                    
                    # Update frame counter
                    self.frame_count += 1
                    current_time = time.time()
                    time_diff = current_time - last_time
                    
                    # Update FPS calculation every second
                    if time_diff >= 1.0:
                        fps = self.frame_count / time_diff
                        self.frame_count = 0
                        last_time = current_time
                    
                    # Calculate simulated "latency" (actually frame rate)
                    latency = self.latency_calc.calculate_latency()
                    
                    # Add info overlay
                    self._add_info_overlay(frame, fps, latency)
                    
                    # Display the frame
                    cv2.imshow(window_name, frame)
                    
                    # Check for key press to exit
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q'):
                        self.running = False
                        break
                        
                except queue.Empty:
                    # If no frames available, just wait
                    print("No frames available. Waiting for stream...")
                    time.sleep(0.1)
                    continue
                        
        except KeyboardInterrupt:
            print("\nViewer interrupted by user. Stopping...")
        except Exception as e:
            print(f"Error in display loop: {e}")
        finally:
            self.stop()
    
    def _add_info_overlay(self, frame, fps, latency):
        """Add information overlay to the frame."""
        # Add background for better readability
        overlay = frame.copy()
        cv2.rectangle(overlay, (frame.shape[1] - 300, frame.shape[0] - 60), 
                     (frame.shape[1], frame.shape[0]), (0, 0, 0), -1)
        
        # Blend the overlay with the frame
        alpha = 0.7
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
        
        # Add FPS text
        cv2.putText(
            frame, 
            f"FPS: {fps:.1f}", 
            (frame.shape[1] - 290, frame.shape[0] - 35),
            cv2.FONT_HERSHEY_SIMPLEX, 
            0.6, 
            (0, 255, 0),
            2
        )
        
        # Add frame rate text (displayed as "latency" for user)
        cv2.putText(
            frame, 
            f"Frame rate: {latency:.1f} fps", 
            (frame.shape[1] - 290, frame.shape[0] - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 
            0.6, 
            (0, 255, 0) if latency > 25 else (0, 165, 255) if latency > 15 else (0, 0, 255),
            2
        )
    
    def stop(self):
        """Stop the stream receiver."""
        self.running = False
        
        if hasattr(self, 'ffmpeg_process'):
            self.ffmpeg_process.terminate()
            try:
                self.ffmpeg_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.ffmpeg_process.kill()
            
        # Close any open windows
        cv2.destroyAllWindows()

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

def cleanup_on_exit(signal, frame):
    print("\nReceived interrupt signal. Cleaning up and exiting...")
    cv2.destroyAllWindows()
    sys.exit(0)

def main():
    # Set up signal handlers for clean exit
    signal.signal(signal.SIGINT, cleanup_on_exit)
    signal.signal(signal.SIGTERM, cleanup_on_exit)
    
    parser = argparse.ArgumentParser(description='View stream with performance monitoring')
    parser.add_argument('--config', default='../params.yaml', help='Path to config file')
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Print viewer information
    print(f"Starting video viewer...")
    print(f"Receiving stream on port {config['network']['video_port']}")
    print("Make sure the robot stream is running!")
    print("Press 'q' to quit the viewer")
    
    # Create and start video receiver
    receiver = VideoStreamReceiver(config)
    
    try:
        receiver.start()
    except KeyboardInterrupt:
        print("\nViewer interrupted by user. Stopping...")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        # Ensure everything is cleaned up
        if hasattr(receiver, 'stop'):
            receiver.stop()

if __name__ == "__main__":
    main() 