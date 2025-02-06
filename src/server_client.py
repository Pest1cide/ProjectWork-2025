import socket
import time
import sys
import json
import os

# Update frequency in Hz
UPDATE_FREQUENCY = 10

def interpolate(val1, val2, fraction):
    return val1 + (val2 - val1) * fraction

# Function to interpolate forward and backward between multiple files
def interpolate_files_from_folder(folder_path, period=10, update_frequency=UPDATE_FREQUENCY):
    files = sorted([os.path.join(folder_path, f) for f in os.listdir(folder_path) if f.endswith('.json')])
    if len(files) < 2:
        raise ValueError("At least two JSON files are required for interpolation.")
    
    steps = period * update_frequency  # Number of updates within the period
    sleep_time = 1.0 / update_frequency  # Time between updates
    
    while True:
        for i in range(len(files) - 1):
            with open(files[i], 'r') as f1, open(files[i + 1], 'r') as f2:
                data1 = json.load(f1)
                data2 = json.load(f2)
                
            for j in range(steps + 1):  # Forward interpolation
                fraction = j / steps
                interpolated_data = {key: interpolate(data1[key], data2[key], fraction) for key in data1}
                yield json.dumps(interpolated_data)
                time.sleep(sleep_time)
        
        for i in range(len(files) - 1, 0, -1):
            with open(files[i], 'r') as f1, open(files[i - 1], 'r') as f2:
                data1 = json.load(f1)
                data2 = json.load(f2)
                
            for j in range(steps + 1):  # Backward interpolation
                fraction = j / steps
                interpolated_data = {key: interpolate(data1[key], data2[key], fraction) for key in data1}
                yield json.dumps(interpolated_data)
                time.sleep(sleep_time)

# Server Code
def start_server(folder_path, host='127.0.0.1', port=12345):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Allow address reuse
    server_socket.bind((host, port))
    server_socket.listen(1)
    print(f"Server listening on {host}:{port}")
    
    try:
        conn, addr = server_socket.accept()
        print(f"Connection from {addr}")
        
        for interpolated_data in interpolate_files_from_folder(folder_path):
            conn.sendall(interpolated_data.encode())
    except (BrokenPipeError, ConnectionResetError):
        print("Client disconnected")
    except KeyboardInterrupt:
        print("Server shutting down.")
    finally:
        conn.close()
        server_socket.close()
        print("Server socket closed.")

# Client Code
def start_client(host='127.0.0.1', port=12345):
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.connect((host, port))
    
    try:
        while True:
            response = client_socket.recv(1024)
            if not response:
                break
            print(f"Server response: {response.decode()}")
    except KeyboardInterrupt:
        print("Client terminated.")
    finally:
        client_socket.close()

if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == 'server':
        start_server(sys.argv[2])
    else:
        start_client()
