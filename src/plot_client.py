import socket
import time
import sys
import json
import threading
import tkinter as tk

import matplotlib
matplotlib.use('TkAgg')  # Force Tk as backend
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

def start_plotting_and_recording_client(host='127.0.0.1', port=12345, output_file='recorded_data.jsonl'):
    """
    A combined client that plots data from the server in real time and optionally records
    it to a JSONL file. Recording can be toggled with a button in the GUI.

    This version attempts to reconnect if the connection fails or is refused.
    """

    root = tk.Tk()
    root.title("Live Data Plot + Recording")
    fig, ax = plt.subplots()
    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    data_history = []
    stop_event = threading.Event()

    # Recording-related state
    recording = [False]   # mutable boolean in a list so nested scope can modify
    record_file = [None]  # track file handle

    def toggle_recording():
        """Toggle recording on/off"""
        if not recording[0]:
            # Start recording
            try:
                record_file[0] = open(output_file, 'w', encoding='utf-8')
                recording[0] = True
                record_button.config(text="Stop Recording")
                print(f"Recording started: {output_file}")
            except Exception as e:
                print(f"Failed to open file for recording: {e}")
        else:
            # Stop recording
            if record_file[0]:
                record_file[0].close()
                record_file[0] = None
            recording[0] = False
            record_button.config(text="Start Recording")
            print("Recording stopped.")

    # Button to toggle recording
    record_button = tk.Button(root, text="Start Recording", command=toggle_recording)
    record_button.pack(side=tk.BOTTOM, pady=5)

    # We'll maintain a socket that can be None if not connected.
    client_socket = [None]
    buffer = b''

    def try_connect():
        """Repeatedly try to connect to the server until success or stop_event is set."""
        while not stop_event.is_set():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            try:
                s.connect((host, port))
                s.settimeout(1.0)
                print(f"Connected to server at {host}:{port}")
                return s
            except (ConnectionRefusedError, TimeoutError, OSError) as e:
                s.close()
                print(f"Connection error: {e}, retrying in 2 seconds...")
                time.sleep(2)
        return None

    def recv_and_plot():
        nonlocal buffer
        while not stop_event.is_set():
            # Ensure we have a connection
            if client_socket[0] is None:
                client_socket[0] = try_connect()
                if client_socket[0] is None:
                    break  # stop_event must have been set, so exit

            # Attempt to receive data
            try:
                chunk = client_socket[0].recv(1024)
                if not chunk:
                    # Server closed connection?
                    print("Server closed connection, will attempt to reconnect.")
                    client_socket[0].close()
                    client_socket[0] = None
                    continue

                buffer += chunk
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    line = line.strip()
                    if line:
                        try:
                            line_str = line.decode('utf-8')
                            data = json.loads(line_str)
                            data_history.append(data)

                            # Recording logic
                            if recording[0] and record_file[0]:
                                record_file[0].write(line_str + "\n")

                        except json.JSONDecodeError:
                            continue

                        # Update the plot
                        ax.clear()
                        for key in data.keys():
                            ax.plot(range(len(data_history)), [d.get(key, 0) for d in data_history], label=key)
                        ax.legend()
                        canvas.draw()
            except socket.timeout:
                # No data received this loop, just continue
                pass
            except (ConnectionResetError, OSError) as e:
                print(f"Connection lost ({e}), will attempt to reconnect.")
                client_socket[0].close()
                client_socket[0] = None
                continue

        # Clean up any open socket if we exit
        if client_socket[0] is not None:
            try:
                client_socket[0].close()
            except OSError:
                pass

    # Thread that receives data and updates the plot (and handles recording), with reconnection
    plot_thread = threading.Thread(target=recv_and_plot)
    plot_thread.start()

    def on_close():
        stop_event.set()
        # If recording is active, close file
        if recording[0] and record_file[0]:
            record_file[0].close()
            record_file[0] = None
            print("Recording stopped.")
        root.quit()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()

    plot_thread.join()
    plt.close(fig)

    print("Plotting+Recording client closed fully.")
    sys.exit(0)
