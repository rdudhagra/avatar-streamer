#!/usr/bin/env python3
import yaml
import os
import argparse
import subprocess
import sys
import cv2
import numpy as np
import time
import threading
import datetime
import select
import socket
from pathlib import Path

def load_config(config_path):
    """Load configuration from YAML file."""
    with open(config_path, 'r') as file:
        return yaml.safe_load(file)

class StreamRecorder:
    """Captures video stream and saves it to a file."""
    
    def __init__(self, config, output_dir=None):
        """Initialize with configuration parameters."""
        self.config = config
        self.width = config['video']['width']
        self.height = config['video']['height']
        self.framerate = config['video']['framerate']
        self.video_port = config['network']['video_port']
        self.running = False
        self.frame_count = 0
        self.start_time = time.time()
        
        # Set output directory
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = Path("recordings")
        
        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate output filename with current date and time
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_file = self.output_dir / f"recording_{timestamp}.mp4"
        
        # FFmpeg process
        self.ffmpeg_process = None
        # UDP socket for receiving
        self.sock = None
        
    def setup_socket(self):
        """Setup UDP socket for receiving without binding exclusively."""
        # Create UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Allow address reuse
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):  # Not available on all platforms
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            
        # Bind to all interfaces
        try:
            self.sock.bind(('0.0.0.0', self.video_port))
            print(f"Successfully bound to UDP port {self.video_port}")
            return True
        except socket.error as e:
            print(f"Socket binding failed: {e}")
            
            # Try a different method - create a receive-only socket
            try:
                # Create a new socket with special options for shared binding
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if hasattr(socket, 'SO_REUSEPORT'):
                    self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                    
                # Set larger buffer
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16*1024*1024)
                
                # Try joining a multicast group to get packets
                # This is a workaround to receive UDP packets when port is already bound
                self.sock.bind(('', self.video_port))  # Bind to all interfaces, port
                print(f"Using non-exclusive UDP reception on port {self.video_port}")
                return True
            except socket.error as e2:
                print(f"Alternative socket method failed: {e2}")
                return False
    
    def start(self):
        """Start capturing and recording the stream."""
        self.running = True
        
        # Setup reception socket
        if not self.setup_socket():
            print("Failed to setup reception socket, cannot continue")
            return False
            
        # Set up a temporary file for storing received UDP data
        temp_file = self.output_dir / "temp_udp_stream.ts"
        
        # FFmpeg command to convert the data to MP4
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",  # Overwrite output file
            "-re",  # Read input at native frame rate (for pipes)
            "-fflags", "nobuffer",  # Reduce buffering for lower latency
            "-i", "pipe:0",  # Read from stdin
            "-c:v", "copy",  # Copy video stream without re-encoding
            "-movflags", "faststart",  # Optimize for streaming
            "-reset_timestamps", "1",  # Reset timestamps
            str(self.output_file)
        ]
        
        print(f"Starting recording to {self.output_file}")
        print(f"Listening on port: {self.video_port}")
        print("Waiting for stream data... (Press Ctrl+C to cancel)")
        
        # Start FFmpeg process with pipe for input
        self.ffmpeg_process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=10**8  # Large buffer
        )
        
        # Create a thread to monitor FFmpeg stderr output
        stderr_thread = threading.Thread(target=self._monitor_ffmpeg_stderr)
        stderr_thread.daemon = True
        stderr_thread.start()
        
        # Create a thread to handle UDP reception and pipe to FFmpeg
        udp_thread = threading.Thread(target=self._receive_and_pipe)
        udp_thread.daemon = True
        udp_thread.start()
        
        try:
            # Monitor the process
            while self.running and self.ffmpeg_process.poll() is None:
                time.sleep(1)
                
                # Check if FFmpeg is still running
                if self.ffmpeg_process.poll() is not None:
                    print(f"FFmpeg process exited with code {self.ffmpeg_process.poll()}")
                    self.running = False
                    break
                
                # Print recording duration every 10 seconds
                current_time = time.time()
                elapsed = current_time - self.start_time
                if int(elapsed) > 0 and int(elapsed) % 10 == 0:
                    print(f"Recording in progress... {elapsed:.0f} seconds")
        
        except KeyboardInterrupt:
            print("\nRecording interrupted by user")
        except Exception as e:
            print(f"Error during recording: {e}")
        finally:
            self.stop()
            
        return True
    
    def _receive_and_pipe(self):
        """Receive UDP packets and pipe them to FFmpeg."""
        # Buffer to count received data
        bytes_received = 0
        last_report_time = time.time()
        
        while self.running:
            try:
                # Check if socket ready to read (with timeout)
                ready = select.select([self.sock], [], [], 0.5)
                
                # If socket has data
                if self.sock in ready[0]:
                    # Receive UDP packet
                    data, addr = self.sock.recvfrom(65536)  # Max UDP packet size
                    
                    # If data received and process still running
                    if data and self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                        # Pipe data to FFmpeg
                        try:
                            self.ffmpeg_process.stdin.write(data)
                            self.ffmpeg_process.stdin.flush()
                            
                            # Count bytes received
                            bytes_received += len(data)
                            
                            # Report data rate every 5 seconds
                            current_time = time.time()
                            if current_time - last_report_time >= 5:
                                data_rate = bytes_received / (current_time - last_report_time) / 1024
                                print(f"Data rate: {data_rate:.2f} KB/s")
                                bytes_received = 0
                                last_report_time = current_time
                                
                        except BrokenPipeError:
                            print("FFmpeg pipe broken, stopping")
                            self.running = False
                            break
                            
            except Exception as e:
                print(f"Error receiving UDP data: {e}")
                time.sleep(0.1)
    
    def _monitor_ffmpeg_stderr(self):
        """Monitor FFmpeg's stderr for errors and important messages."""
        # Read error output line by line
        for line in iter(self.ffmpeg_process.stderr.readline, b''):
            if not self.running:
                break
                
            line = line.decode('utf-8', errors='replace').strip()
            
            # Only print crucial errors or stream info
            if any(keyword in line.lower() for keyword in ['error', 'fail', 'fatal', 'invalid']):
                print(f"FFmpeg: {line}")
                
            elif "Input #0" in line or "Stream mapping" in line:
                print(f"FFmpeg: {line}")
                print("Stream detected! Recording started.")
    
    def stop(self):
        """Stop recording."""
        if not self.running:
            return  # Already stopped
            
        self.running = False
        
        # Close the UDP socket
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
        
        # Stop FFmpeg process gracefully
        if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
            print("Stopping recording...")
            
            # Close stdin to signal EOF to FFmpeg
            if hasattr(self.ffmpeg_process, 'stdin') and self.ffmpeg_process.stdin:
                try:
                    self.ffmpeg_process.stdin.close()
                except:
                    pass
            
            # Wait for process to finish
            try:
                self.ffmpeg_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("FFmpeg did not terminate in time, forcing...")
                self.ffmpeg_process.kill()
        
        recording_time = time.time() - self.start_time
        print(f"Recording stopped. Duration: {recording_time:.2f} seconds")
        
        # Check if the output file exists and has a size greater than 1KB
        if self.output_file.exists() and self.output_file.stat().st_size > 1024:
            print(f"Output file: {self.output_file}")
        else:
            print("No data was recorded. Make sure a stream is active on the specified port.")

def main():
    parser = argparse.ArgumentParser(description='Record video stream to file')
    parser.add_argument('--config', default='../params.yaml', help='Path to config file')
    parser.add_argument('--output-dir', help='Directory to save recordings')
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Create and start recorder
    recorder = StreamRecorder(config, args.output_dir)
    
    try:
        recorder.start()
    except KeyboardInterrupt:
        print("\nRecorder interrupted by user. Stopping...")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        if hasattr(recorder, 'stop'):
            recorder.stop()

if __name__ == "__main__":
    main() 