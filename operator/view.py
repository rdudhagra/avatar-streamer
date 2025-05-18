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
import hashlib
import zmq
import json
import collections

class LatencyCalculator:
    """Class to track video stream latency."""
    
    def __init__(self):
        self.last_latencies = []  # Store last few latency values for smoothing
        self.max_samples = 10     # Number of samples to keep for averaging
        self.last_time = time.time()
        
        # For true latency calculation
        self.frame_timestamps = {}  # Store sent timestamps by frame_count
        self.latency_values = collections.deque(maxlen=30)  # Store last 30 latency values
    
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
    
    def store_frame_timestamp(self, frame_count, timestamp):
        """Store timestamp for a given frame count."""
        self.frame_timestamps[frame_count] = timestamp
        
        # Clean up old timestamps (keep only last 100)
        if len(self.frame_timestamps) > 100:
            oldest = min(self.frame_timestamps.keys())
            self.frame_timestamps.pop(oldest)
    
    def calculate_true_latency(self, frame_count):
        """Calculate true latency based on sent and received timestamps."""
        if frame_count in self.frame_timestamps:
            sent_time = self.frame_timestamps[frame_count]
            received_time = time.time()
            latency_ms = (received_time - sent_time) * 1000  # Convert to milliseconds
            
            # Store latency value
            self.latency_values.append(latency_ms)
            
            # Calculate average latency
            avg_latency = sum(self.latency_values) / len(self.latency_values)
            
            return avg_latency, latency_ms
        return None, None

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
        
        # Initialize ZeroMQ context and subscriber socket
        self.zmq_context = zmq.Context()
        self.zmq_socket = self.zmq_context.socket(zmq.SUB)
        # Connect to publisher (video_port + 1)
        self.zmq_port = self.video_port + 1
        self.zmq_socket.connect(f"tcp://{config['network']['operator_ip']}:{self.zmq_port}")
        # Subscribe to all messages
        self.zmq_socket.setsockopt_string(zmq.SUBSCRIBE, "")
        print(f"ZeroMQ subscriber connected to {config['network']['operator_ip']}:{self.zmq_port}")
        
        # Start ZeroMQ receiver thread
        self.zmq_thread = Thread(target=self._receive_zmq_messages)
        self.zmq_thread.daemon = True
        self.zmq_thread.start()
        
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
    
    def _receive_zmq_messages(self):
        """Receive ZeroMQ messages with frame timestamps."""
        while self.running:
            try:
                # Use poll with timeout to prevent blocking indefinitely
                if self.zmq_socket.poll(100) & zmq.POLLIN:
                    message = self.zmq_socket.recv_string()
                    data = json.loads(message)
                    
                    # Store frame timestamp
                    frame_count = data.get('frame_count')
                    timestamp = data.get('timestamp')
                    if frame_count is not None and timestamp is not None:
                        self.latency_calc.store_frame_timestamp(frame_count, timestamp)
                        print(f"ZMQ: Received timestamp for frame {frame_count}")
            except Exception as e:
                print(f"Error receiving ZMQ message: {e}")
                time.sleep(0.1)
        
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

                    # Process frame
                    frame = self.process_frame(frame)
                    
                    # Put in queue if not full
                    if not self.frame_queue.full():
                        self.frame_queue.put(frame)
                else:
                    # If we can't read a full frame, sleep a bit
                    time.sleep(0.001)
            except Exception as e:
                print(f"Error reading frame: {e}")
                time.sleep(0.1)
        
    def process_frame(self, frame):
        """Process frame before displaying it."""

        # Calculate the counter of the frame from the fingerprint
        decoded_counter = 0
        decoded_counter |= (1 << 0) if int(np.average(frame[0:32, 0:32, :])) > 128 else 0
        decoded_counter |= (1 << 1) if int(np.average(frame[0:32, 32:64, :])) > 128 else 0
        decoded_counter |= (1 << 2) if int(np.average(frame[32:64, 0:32, :])) > 128 else 0
        decoded_counter |= (1 << 3) if int(np.average(frame[32:64, 32:64, :])) > 128 else 0
        decoded_counter |= (1 << 4) if int(np.average(frame[64:96, 0:32, :])) > 128 else 0

        # Calculate true latency based on ZeroMQ timestamps
        avg_latency, frame_latency = self.latency_calc.calculate_true_latency(decoded_counter)
        
        # Add text with proper None handling
        cv2.putText(frame, f"Decoded counter: {decoded_counter}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        cv2.putText(frame, f"Frame count: {self.frame_count}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        
        if frame_latency is not None:
            cv2.putText(frame, f"Frame latency: {frame_latency:.1f} ms", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        else:
            cv2.putText(frame, "Frame latency: waiting...", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 2)
            
        if avg_latency is not None:
            cv2.putText(frame, f"Avg latency: {avg_latency:.1f} ms", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        else:
            cv2.putText(frame, "Avg latency: waiting...", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 2)
        
        return frame
    
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
                    
                    # Calculate frame rate (from original latency calculator)
                    frame_rate = self.latency_calc.calculate_latency()
                    
                    # Get true latency from frame (safe default to 0 if not available)
                    true_latency = getattr(frame, 'latency', 0)
                    frame_latency = getattr(frame, 'frame_latency', 0)
                    
                    # Add info overlay with both metrics
                    self._add_info_overlay(frame, fps, frame_rate, true_latency, frame_latency)
                    
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
            import traceback
            traceback.print_exc()
        finally:
            self.stop()
    
    def _add_info_overlay(self, frame, fps, frame_rate, true_latency, frame_latency):
        """Add information overlay to the frame."""
        # Add background for better readability
        overlay = frame.copy()
        cv2.rectangle(overlay, (frame.shape[1] - 300, frame.shape[0] - 100), 
                     (frame.shape[1], frame.shape[0]), (0, 0, 0), -1)
        
        # Blend the overlay with the frame
        alpha = 0.7
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
        
        # Add FPS text
        cv2.putText(
            frame, 
            f"FPS: {fps:.1f}", 
            (frame.shape[1] - 290, frame.shape[0] - 75),
            cv2.FONT_HERSHEY_SIMPLEX, 
            0.6, 
            (0, 255, 0),
            2
        )
        
        # Add frame rate text
        cv2.putText(
            frame, 
            f"Frame rate: {frame_rate:.1f} fps", 
            (frame.shape[1] - 290, frame.shape[0] - 50),
            cv2.FONT_HERSHEY_SIMPLEX, 
            0.6, 
            (0, 255, 0) if frame_rate > 25 else (0, 165, 255) if frame_rate > 15 else (0, 0, 255),
            2
        )
        
        # Add true latency text (with None check)
        latency_color = (0, 255, 0) if true_latency < 100 else (0, 165, 255) if true_latency < 200 else (0, 0, 255)
        if true_latency > 0:
            # Only show latency if we have valid data
            cv2.putText(
                frame, 
                f"Avg latency: {true_latency:.1f} ms", 
                (frame.shape[1] - 290, frame.shape[0] - 25),
                cv2.FONT_HERSHEY_SIMPLEX, 
                0.6, 
                latency_color,
                2
            )
            
            # Add frame latency
            cv2.putText(
                frame, 
                f"Frame latency: {frame_latency:.1f} ms", 
                (frame.shape[1] - 290, frame.shape[0] - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 
                0.5, 
                latency_color,
                1
            )
        else:
            # Show waiting message
            cv2.putText(
                frame, 
                "Waiting for latency data...", 
                (frame.shape[1] - 290, frame.shape[0] - 25),
                cv2.FONT_HERSHEY_SIMPLEX, 
                0.6, 
                (0, 165, 255),
                2
            )
    
    def stop(self):
        """Stop the stream receiver."""
        self.running = False
        
        # Close ZeroMQ socket
        if hasattr(self, 'zmq_socket'):
            self.zmq_socket.close()
        if hasattr(self, 'zmq_context'):
            self.zmq_context.term()
        
        if hasattr(self, 'ffmpeg_process'):
            self.ffmpeg_process.terminate()
            try:
                self.ffmpeg_process.wait(timeout=2)
            except:
                self.ffmpeg_process.kill()
                
        cv2.destroyAllWindows()
        print("Stream receiver stopped")

def load_config(config_path):
    """Load configuration from YAML file."""
    with open(config_path, 'r') as file:
        return yaml.safe_load(file)

# Signal handler for clean exit
def cleanup_on_exit(signal, frame):
    print("\nExiting...")
    sys.exit(0)

def main():
    # Set up signal handlers for clean exit
    signal.signal(signal.SIGINT, cleanup_on_exit)
    signal.signal(signal.SIGTERM, cleanup_on_exit)
    
    parser = argparse.ArgumentParser(description='Receive and display video stream')
    parser.add_argument('--config', default='../params.yaml', help='Path to config file')
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Print view information
    print(f"Starting video viewer with settings:")
    print(f"Resolution: {config['video']['width']}x{config['video']['height']}")
    print(f"Receiving from port: {config['network']['video_port']}")
    print(f"ZeroMQ metrics from port: {config['network']['video_port'] + 1}")
    
    # Create and start receiver
    receiver = VideoStreamReceiver(config)
    receiver.start()

if __name__ == "__main__":
    main() 