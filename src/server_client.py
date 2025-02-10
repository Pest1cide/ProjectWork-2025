import socket
import time
import sys
import json
import os
import threading
import tkinter as tk
import matplotlib
matplotlib.use('TkAgg')  # Force Tk as backend
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Optional: If you have bosdyn libraries, uncomment or place behind a try-except
import bosdyn.client
import bosdyn.client.util
from bosdyn.client.robot_state import RobotStateClient

# For the 3D visualization client
try:
    import pybullet as p
    import pybullet_data
except ImportError:
    p = None

# Update frequency in Hz
UPDATE_FREQUENCY = 10

class GlobalRobotState:
    """
    A global state object that holds the current robot data as a dictionary.
    This state can be updated from real hardware (Spot), from interpolation,
    or from file replay.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {}

    def set_data(self, data_dict):
        with self._lock:
            self._data = dict(data_dict)

    def get_data(self):
        with self._lock:
            return dict(self._data)

#########################
# Spot Data Updater
#########################

def spot_data_updater(robot_state_client, global_state, update_rate=2.5):
    """
    Continuously grab data from Spot's real robot state client,
    and update the global state.
    """
    try:
        while True:
            # Grab the robot's state
            robot_state = robot_state_client.get_robot_state()
            joint_states = robot_state.kinematic_state.joint_states

            joints_dict = {}
            for js in joint_states:
                if js.name and js.position.value is not None:
                    joints_dict[js.name] = js.position.value

            global_state.set_data(joints_dict)
            time.sleep(1.0 / update_rate)
    except Exception as e:
        print("Spot updater thread ending:", e)

#########################
# File Interpolation Updater
#########################

def interpolate(val1, val2, fraction):
    return val1 + (val2 - val1) * fraction


def interpolation_updater(folder_path, global_state, period=10, update_frequency=UPDATE_FREQUENCY):
    """
    Continuously interpolate between JSON files in a folder,
    updating global_state with the interpolated data.
    """
    files = sorted([
        os.path.join(folder_path, f)
        for f in os.listdir(folder_path)
        if f.endswith('.json')
    ])
    if len(files) < 2:
        raise ValueError("At least two JSON files are required for interpolation.")

    steps = period * update_frequency  # Number of updates within the period
    sleep_time = 1.0 / update_frequency  # Time between updates

    try:
        while True:
            # Forward pass
            for i in range(len(files) - 1):
                with open(files[i], 'r') as f1, open(files[i + 1], 'r') as f2:
                    data1 = json.load(f1)
                    data2 = json.load(f2)

                for j in range(steps + 1):
                    fraction = j / steps
                    interpolated_data = {
                        key: interpolate(data1[key], data2[key], fraction)
                        for key in data1
                    }
                    global_state.set_data(interpolated_data)
                    time.sleep(sleep_time)

            # Backward pass
            for i in range(len(files) - 1, 0, -1):
                with open(files[i], 'r') as f1, open(files[i - 1], 'r') as f2:
                    data1 = json.load(f1)
                    data2 = json.load(f2)

                for j in range(steps + 1):
                    fraction = j / steps
                    interpolated_data = {
                        key: interpolate(data1[key], data2[key], fraction)
                        for key in data1
                    }
                    global_state.set_data(interpolated_data)
                    time.sleep(sleep_time)
    except Exception as e:
        print("Interpolation updater thread ending:", e)

#########################
# File Replay Updater
#########################

def replay_updater(file_path, global_state, update_frequency=UPDATE_FREQUENCY):
    """
    Continuously replay lines from a single JSONL file,
    updating global_state with each line.
    """
    sleep_time = 1.0 / update_frequency

    try:
        while True:
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            global_state.set_data(data)
                        except json.JSONDecodeError:
                            pass
                    time.sleep(sleep_time)
    except Exception as e:
        print("Replay updater thread ending:", e)

#########################
# Multi-Client Server
#########################

def handle_client(conn, addr, global_state, send_rate=10):
    """
    Each client runs in its own thread. We continuously fetch the global
    robot state and send it as JSON.
    """
    print(f"Client connected from {addr}")
    sleep_time = 1.0 / send_rate
    try:
        while True:
            data_dict = global_state.get_data()
            message = json.dumps(data_dict) + "\n"
            conn.sendall(message.encode('utf-8'))
            time.sleep(sleep_time)
    except (BrokenPipeError, ConnectionResetError):
        print(f"Client {addr} disconnected")
    finally:
        conn.close()
        print(f"Connection with {addr} closed.")


def start_server(global_state, host='127.0.0.1', port=12346, send_rate=10):
    """
    Start a multi-client server that streams the current global_state to each client.
    """
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen()
    print(f"Server listening on {host}:{port}")

    try:
        while True:
            print("Waiting for a new connection...")
            conn, addr = server_socket.accept()
            client_thread = threading.Thread(
                target=handle_client,
                args=(conn, addr, global_state, send_rate),
                daemon=True
            )
            client_thread.start()
    except KeyboardInterrupt:
        print("Server shutting down.")
    finally:
        server_socket.close()
        print("Server socket closed.")

#########################
# Combined Plotting & Recording Client (with Reconnect)
#########################

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
    recording = [False]  # mutable boolean in a list so nested scope can modify
    record_file = [None] # track file handle

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

#########################
# 3D Visualization Client (PyBullet)
#########################

def start_3d_visualization_client(host='127.0.0.1', port=12346, urdf_path='spot.urdf'):
    """
    A client that connects to the server, receives joint data, and displays a 3D visualization
    of the robot using PyBullet. The URDF file must be specified (or default to 'spot.urdf'),
    and the joint names from the server should match the URDF's joint naming.
    """
    if p is None:
        print("PyBullet is not installed. Please install pybullet to use 3D visualization.")
        return

    # Try to connect to the server
    stop_event = threading.Event()
    client_socket = None
    buffer = b''

    # PyBullet setup
    physics_client = p.connect(p.GUI)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.resetDebugVisualizerCamera(cameraDistance=2.0, cameraYaw=30, cameraPitch=-30, cameraTargetPosition=[0,0,0])
    p.setGravity(0,0,-9.81)
    p.setRealTimeSimulation(0)

    # Load the robot URDF
    try:
        robot_id = p.loadURDF(urdf_path, useFixedBase=True)
    except Exception as e:
        print(f"Failed to load URDF {urdf_path}: {e}")
        return

    # Build a map from joint name to joint index in PyBullet
    joint_name_to_index = {}
    num_joints = p.getNumJoints(robot_id)
    for i in range(num_joints):
        joint_info = p.getJointInfo(robot_id, i)
        name = joint_info[1].decode('utf-8')
        joint_name_to_index[name] = i

    def try_connect_viz():
        while not stop_event.is_set():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            try:
                s.connect((host, port))
                s.settimeout(1.0)
                print(f"[3D Viz] Connected to server at {host}:{port}")
                return s
            except (ConnectionRefusedError, TimeoutError, OSError) as e:
                s.close()
                print(f"[3D Viz] Connection error: {e}, retrying in 2 seconds...")
                time.sleep(2)
        return None

    # Attempt initial connection
    client_socket = try_connect_viz()
    if client_socket is None:
        print("[3D Viz] Could not connect, exiting.")
        return

    try:
        while not stop_event.is_set():
            # Attempt to receive data
            try:
                chunk = client_socket.recv(1024)
                if not chunk:
                    # Server closed connection?
                    print("[3D Viz] Server closed connection, will attempt to reconnect.")
                    client_socket.close()
                    client_socket = None
                    client_socket = try_connect_viz()
                    if client_socket is None:
                        break
                    continue

                buffer += chunk
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    line = line.strip()
                    if line:
                        try:
                            line_str = line.decode('utf-8')
                            data = json.loads(line_str)

                            # Update the robot's joint angles
                            for joint_name, angle in data.items():
                                if joint_name in joint_name_to_index:
                                    j_idx = joint_name_to_index[joint_name]
                                    # Use resetJointState or setJointMotorControl2
                                    p.resetJointState(robot_id, j_idx, angle)

                            # Step simulation
                            p.stepSimulation()

                        except json.JSONDecodeError:
                            continue
            except socket.timeout:
                # no data, step simulation anyway
                p.stepSimulation()
                time.sleep(0.01)
            except (ConnectionResetError, OSError) as e:
                print(f"[3D Viz] Connection lost ({e}), will attempt to reconnect.")
                client_socket.close()
                client_socket = None
                client_socket = try_connect_viz()
                if client_socket is None:
                    break
                continue

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("[3D Viz] Keyboard interrupt, shutting down.")
    finally:
        stop_event.set()
        if client_socket:
            client_socket.close()
        p.disconnect()
        print("[3D Viz] Exiting 3D visualization.")

#########################
# Example Main
#########################
if __name__ == "__main__":
    # The global state object
    global_state = GlobalRobotState()

    # Example usage:
    # 1) python script.py server <path> -> If path is folder, run interpolation in a thread.
    #    If path is file, run replay in a thread. Then start the server.
    # 2) python script.py spot <hostname> -> Connect to Spot and update global_state from real robot.
    #    Then start the server.
    # 3) python script.py plot_and_record -> Start local plotting+recording client.
    # 4) python script.py record <host> <port> <out_file> -> Start local recording client.
    # 5) python script.py visual3d <host> <port> <urdf_path> -> Start 3D PyBullet client.

    if len(sys.argv) >= 2:
        mode = sys.argv[1]

        if mode == 'server' and len(sys.argv) >= 3:
            path = sys.argv[2]
            # Decide if path is folder or file
            if os.path.isdir(path):
                # Start interpolation thread
                updater_thread = threading.Thread(
                    target=interpolation_updater,
                    args=(path, global_state),
                    daemon=True
                )
            else:
                # Start replay thread
                updater_thread = threading.Thread(
                    target=replay_updater,
                    args=(path, global_state),
                    daemon=True
                )
            updater_thread.start()
            # Start server
            start_server(global_state)

        elif mode == 'spot' and len(sys.argv) >= 3:
            # Example usage to connect to real Spot.
            sdk = bosdyn.client.create_standard_sdk("SpotRealDataServer")
            robot = sdk.create_robot(sys.argv[2])
            bosdyn.client.util.authenticate(robot)
            robot_state_client = robot.ensure_client(RobotStateClient.default_service_name)
            # Start spot_data_updater thread
            updater_thread = threading.Thread(
                target=spot_data_updater,
                args=(robot_state_client, global_state),
                daemon=True
            )
            updater_thread.start()
            start_server(global_state)

        elif mode == 'plot_and_record':
            if len(sys.argv) >= 5:
                start_plotting_and_recording_client(
                    host=sys.argv[2],
                    port=int(sys.argv[3]),
                    output_file=sys.argv[4]
                )
            else:
                start_plotting_and_recording_client()

        elif mode == 'record' and len(sys.argv) >= 5:
            # Original separate record client
            host = sys.argv[2]
            port = int(sys.argv[3])
            out_file = sys.argv[4]
            print("The standalone record mode is still available if needed.")
            start_plotting_and_recording_client(host, port, out_file)

        elif mode == 'visual3d':
            if len(sys.argv) >= 5:
                start_3d_visualization_client(
                    host=sys.argv[2],
                    port=int(sys.argv[3]),
                    urdf_path=sys.argv[4]
                )
            elif len(sys.argv) >= 4:
                start_3d_visualization_client(
                    host=sys.argv[2],
                    port=int(sys.argv[3])
                )
            else:
                start_3d_visualization_client()

        else:
            print("Usage:")
            print("  server <folder_or_file>")
            print("  spot <hostname>")
            print("  plot_and_record [host] [port] [output_file]")
            print("  record <host> <port> <output_file>")
            print("  visual3d <host> <port> <urdf_file>")
    else:
        # Default to the combined plotting+recording client
        start_plotting_and_recording_client()
