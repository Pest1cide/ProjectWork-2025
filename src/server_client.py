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
from bosdyn.client.frame_helpers import BODY_FRAME_NAME, ODOM_FRAME_NAME, get_a_tform_b

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

def spot_data_updater(robot_state_client, global_state, update_rate=10):
    """
    Continuously grab data from Spot's real robot state client,
    and update the global state.
    """
    try:
        while True:
            # Grab the robot's state
            robot_state = robot_state_client.get_robot_state()
            joint_states = robot_state.kinematic_state.joint_states
            transforms = robot_state.kinematic_state.transforms_snapshot
            
            # Body pose
            body_pose = get_a_tform_b(transforms,ODOM_FRAME_NAME, BODY_FRAME_NAME)
            data_dict = {
                'base_x': body_pose.x,
                'base_y': body_pose.y,
                'base_z': body_pose.z,
                'base_qx': body_pose.rot.x,
                'base_qy': body_pose.rot.y,
                'base_qz': body_pose.rot.z,
                'base_qw': body_pose.rot.w
            }
            
            # Joint angles
            for js in joint_states:
                if js.name and js.position.value is not None:
                    data_dict[js.name] = js.position.value

            global_state.set_data(data_dict)
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
                    interpolated_data = {}
                    # Interpolate only numeric values
                    for key in data1:
                        if isinstance(data1[key], (int, float)) and isinstance(data2[key], (int, float)):
                            interpolated_data[key] = interpolate(data1[key], data2[key], fraction)
                        else:
                            # If not numeric, just copy from the first or do custom logic
                            interpolated_data[key] = data1[key]

                    global_state.set_data(interpolated_data)
                    time.sleep(sleep_time)

            # Backward pass
            for i in range(len(files) - 1, 0, -1):
                with open(files[i], 'r') as f1, open(files[i - 1], 'r') as f2:
                    data1 = json.load(f1)
                    data2 = json.load(f2)

                for j in range(steps + 1):
                    fraction = j / steps
                    interpolated_data = {}
                    for key in data1:
                        if isinstance(data1[key], (int, float)) and isinstance(data2[key], (int, float)):
                            interpolated_data[key] = interpolate(data1[key], data2[key], fraction)
                        else:
                            interpolated_data[key] = data1[key]

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
    
    Updated to be faster and avoid getting behind the server by:
      - Using larger recv buffer.
      - Only re-drawing the plot at a limited rate.
      - Keeping a ring buffer of data (instead of indefinite growth).
    """

    import collections

    root = tk.Tk()
    root.title("Live Data Plot + Recording")
    fig, ax = plt.subplots()
    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # We'll store only the last N data points to avoid slow plotting over time
    MAX_POINTS = 1000
    data_history = collections.deque(maxlen=MAX_POINTS)

    stop_event = threading.Event()

    # Recording-related state
    recording = [False]  # mutable boolean in a list so nested scope can modify
    record_file = [None] # track file handle

    # We'll store references to line objects here, keyed by 'variable name'
    lines = {}

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

    # We'll do a modest redraw rate so we don't bog down.
    # e.g. refresh plot at ~10 fps.
    PLOT_REFRESH_INTERVAL = 0.1
    last_plot_time = time.time()

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

    def redraw_plot():
        # Clear the axes so we can rebuild the lines fresh
        ax.clear()
        # We'll track what keys exist in the last data point.
        if len(data_history) == 0:
            canvas.draw()
            return

        latest_data = data_history[-1]
        # For each key, if numeric, plot its time history
        # We can do one line per key.
        # Convert data_history to a list for indexing if needed.
        dh_list = list(data_history)

        for key in latest_data.keys():
            # gather the time series for this key
            val_list = [d.get(key, 0) for d in dh_list]
            if all(isinstance(v, (int, float)) for v in val_list):
                ax.plot(range(len(val_list)), val_list, label=key)
        ax.legend()
        canvas.draw()

    def recv_and_plot():
        nonlocal buffer, last_plot_time
        while not stop_event.is_set():
            # Ensure we have a connection
            if client_socket[0] is None:
                client_socket[0] = try_connect()
                if client_socket[0] is None:
                    break  # stop_event must have been set, so exit

            # Attempt to receive data
            try:
                chunk = client_socket[0].recv(8192)  # bigger buffer
                if not chunk:
                    # Server closed connection?
                    print("Server closed connection, will attempt to reconnect.")
                    client_socket[0].close()
                    client_socket[0] = None
                    continue

                buffer += chunk
                lines_in_buffer = buffer.split(b'\n')
                # We'll parse all but the last partial line (if any)
                for i in range(len(lines_in_buffer) - 1):
                    line = lines_in_buffer[i].strip()
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
                # The last piece in lines_in_buffer is incomplete, so keep it in buffer
                buffer = lines_in_buffer[-1]

                # Throttle plotting to ~10 fps
                now = time.time()
                if (now - last_plot_time) > PLOT_REFRESH_INTERVAL:
                    redraw_plot()
                    last_plot_time = now

            except socket.timeout:
                # No data received this loop, just do a partial check if time to draw
                now = time.time()
                if (now - last_plot_time) > PLOT_REFRESH_INTERVAL:
                    redraw_plot()
                    last_plot_time = now
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
def start_3d_visualization_client(host="localhost",port=12346, urdf_path='spot.urdf'):
   return start_3d_visualization_clients([(host, port), (host, port+1)], [urdf_path, urdf_path])

def start_3d_visualization_clients(servers, urdf_paths):
    """
    A client that connects to multiple servers, receives joint data, and displays multiple 3D robot visualizations
    using PyBullet. Each URDF file must be specified for each server connection.
    """
    if p is None:
        print("PyBullet is not installed. Please install pybullet to use 3D visualization.")
        return

    stop_event = threading.Event()
    client_sockets = {}
    buffers = {}
    robot_ids = {}
    joint_maps = {}

    # PyBullet setup
    physics_client = p.connect(p.GUI)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.resetDebugVisualizerCamera(cameraDistance=2.0, cameraYaw=30, cameraPitch=-30, cameraTargetPosition=[0, 0, 12])
    p.setGravity(0, 0, 0)
    p.setRealTimeSimulation(0)

    # Load robots and establish connections
    for server, urdf_path in zip(servers, urdf_paths):
        host, port = server
        try:
            robot_id = p.loadURDF(urdf_path, useFixedBase=False)
            robot_ids[str(server)] = robot_id
        except Exception as e:
            print(f"Failed to load URDF {urdf_path} for server {server}: {e}")
            continue

        joint_name_to_index = {}
        num_joints = p.getNumJoints(robot_id)
        for i in range(num_joints):
            joint_info = p.getJointInfo(robot_id, i)
            name = joint_info[1].decode('utf-8')
            joint_name_to_index[name] = i
        joint_maps[str(server)] = joint_name_to_index

        def try_connect_viz(server):
            while not stop_event.is_set():
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2.0)
                try:
                    s.connect(server)
                    s.settimeout(1.0)
                    print(f"[3D Viz] Connected to server at {server}")
                    return s
                except (ConnectionRefusedError, TimeoutError, OSError) as e:
                    s.close()
                    print(f"[3D Viz] Connection error: {e}, retrying in 2 seconds...")
                    time.sleep(2)
            return None

        client_sockets[str(server)] = try_connect_viz(server)
        buffers[str(server)] = b''

    if not client_sockets:
        print("[3D Viz] No connections established, exiting.")
        return

    try:
        while not stop_event.is_set():
            for server in list(client_sockets.keys()):
                client_socket = client_sockets[str(server)]
                if client_socket is None:
                    continue

                try:
                    chunk = client_socket.recv(1024)
                    if not chunk:
                        print(f"[3D Viz] Server {server} closed connection, will attempt to reconnect.")
                        client_socket.close()
                        client_sockets[str(server)] = try_connect_viz(server)
                        if client_sockets[str(server)] is None:
                            del client_sockets[str(server)]
                            del robot_ids[str(server)]
                            del joint_maps[str(server)]
                        continue

                    buffers[str(server)] += chunk
                    while b'\n' in buffers[str(server)]:
                        line, buffers[str(server)] = buffers[str(server)].split(b'\n', 1)
                        line = line.strip()
                        if line:
                            try:
                                data = json.loads(line.decode('utf-8'))
                                robot_id = robot_ids[str(server)]

                                base_x = data.get('base_x', 0.0)
                                base_y = data.get('base_y', 0.0)
                                base_z = data.get('base_z', 0.0)
                                qx = data.get('base_qx', 0.0)
                                qy = data.get('base_qy', 0.0)
                                qz = data.get('base_qz', 0.0)
                                qw = data.get('base_qw', 1.0)

                                p.resetBasePositionAndOrientation(robot_id, [base_x, base_y, base_z], [qx, qy, qz, qw])

                                for joint_name, angle in data.items():
                                    if joint_name in joint_maps[str(server)]:
                                        j_idx = joint_maps[str(server)][joint_name]
                                        p.resetJointState(robot_id, j_idx, angle)

                                p.stepSimulation()
                            except json.JSONDecodeError:
                                continue
                except socket.timeout:
                    p.stepSimulation()
                    time.sleep(0.01)
                except (ConnectionResetError, OSError) as e:
                    print(f"[3D Viz] Connection lost with {server} ({e}), will attempt to reconnect.")
                    client_socket.close()
                    client_sockets[str(server)] = try_connect_viz(server)
                    if client_sockets[str(server)] is None:
                        del client_sockets[str(server)]
                        del robot_ids[str(server)]
                        del joint_maps[str(server)]
                    continue
                
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("[3D Viz] Keyboard interrupt, shutting down.")
    finally:
        stop_event.set()
        for client_socket in client_sockets.values():
            if client_socket:
                client_socket.close()
        p.disconnect()
        print("[3D Viz] Exiting 3D visualization.")

#########################
# Puppeteer Updater
#########################
def puppet_updater(global_state, urdf_path='spot.urdf', update_frequency=UPDATE_FREQUENCY):
    """
    Launch a PyBullet GUI that lets the user:
      - Drag the robot around for position/orientation,
      - Manipulate joints by clicking/dragging links (if the URDF allows),
      - Use WASD to move the robot base around in the XY plane,
      - Use Q/E to turn the robot around its Z axis.

    All resulting base/joint states are continuously published to global_state,
    with orientation reported as a quaternion.
    """
    if p is None:
        print("PyBullet is not installed. Please install pybullet to use the puppeteer.")
        return

    # PyBullet setup
    physics_client = p.connect(p.GUI)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.resetDebugVisualizerCamera(
        cameraDistance=2.0, cameraYaw=30, cameraPitch=-30,
        cameraTargetPosition=[0, 0, 0]
    )

    # You can enable normal gravity if desired
    p.setGravity(0, 0, 0)  # no gravity

    # For interactive dragging, we can enable real-time sim or step-based.
    p.setRealTimeSimulation(0)

    # Load the robot URDF
    try:
        # useFixedBase=False lets you drag or move the base in the GUI
        robot_id = p.loadURDF(urdf_path, useFixedBase=False)
    except Exception as e:
        print(f"Failed to load URDF {urdf_path}: {e}")
        return

    # Give the user a draggable interface
    p.configureDebugVisualizer(p.COV_ENABLE_GUI, 1)

    # Build a map from joint index to joint name so we can store in data
    joint_map = {}
    num_joints = p.getNumJoints(robot_id)
    for i in range(num_joints):
        info = p.getJointInfo(robot_id, i)
        j_name = info[1].decode('utf-8')
        joint_map[i] = j_name

    sleep_time = 1.0 / update_frequency

    # WASD movement parameters
    linear_speed = 0.02   # speed for forward/back/strafe per loop
    angular_speed = 0.02  # rad step for turning (Q/E)

    print("[Puppeteer] PyBullet GUI open. Drag the robot or use WASD (and Q/E) to move/turn. Joints can also be manipulated.")

    try:
        while True:
            # Get base pose: position + orientation (quaternion)
            base_pos, base_quat = p.getBasePositionAndOrientation(robot_id)

            # Convert quaternion to Euler to easily modify yaw
            base_eul = p.getEulerFromQuaternion(base_quat)

            # Check keyboard for WASD/QE input
            keys = p.getKeyboardEvents()

            # Forward/back (W/S) and strafe (A/D) in the global frame for simplicity:
            if ord('w') in keys and keys[ord('w')] & p.KEY_IS_DOWN:
                base_pos = (base_pos[0] + linear_speed, base_pos[1], base_pos[2])
            if ord('s') in keys and keys[ord('s')] & p.KEY_IS_DOWN:
                base_pos = (base_pos[0] - linear_speed, base_pos[1], base_pos[2])
            if ord('a') in keys and keys[ord('a')] & p.KEY_IS_DOWN:
                base_pos = (base_pos[0], base_pos[1] + linear_speed, base_pos[2])
            if ord('d') in keys and keys[ord('d')] & p.KEY_IS_DOWN:
                base_pos = (base_pos[0], base_pos[1] - linear_speed, base_pos[2])

            # Turn left (Q) or right (E) by changing yaw
            yaw = base_eul[2]
            if ord('q') in keys and keys[ord('q')] & p.KEY_IS_DOWN:
                yaw += angular_speed
            if ord('e') in keys and keys[ord('e')] & p.KEY_IS_DOWN:
                yaw -= angular_speed

            # Convert updated Euler back to quaternion
            updated_quat = p.getQuaternionFromEuler((base_eul[0], base_eul[1], yaw))

            # Apply new base pose
            p.resetBasePositionAndOrientation(robot_id, base_pos, updated_quat)

            # Build data_dict with base pose
            data_dict = {
                'base_x': base_pos[0],
                'base_y': base_pos[1],
                'base_z': base_pos[2],
                'base_qx': updated_quat[0],
                'base_qy': updated_quat[1],
                'base_qz': updated_quat[2],
                'base_qw': updated_quat[3]
            }

            # Get each joint's angle
            for j_idx in range(num_joints):
                j_state = p.getJointState(robot_id, j_idx)
                j_angle = j_state[0]  # position
                data_dict[joint_map[j_idx]] = j_angle

            # Publish to the global state
            global_state.set_data(data_dict)

            # Step simulation
            p.stepSimulation()
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("[Puppeteer] Keyboard interrupt, shutting down.")
    finally:
        p.disconnect()
        print("[Puppeteer] Exiting puppeteer updater.")


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
    # 6) python script.py puppeteer <urdf_file> -> Start a local PyBullet puppeteer that updates global_state.

    if len(sys.argv) >= 2:
        mode = sys.argv[1]

        if mode == 'server' and len(sys.argv) >= 3:
            path = sys.argv[2]
            print(sys.argv)
            port =  int(sys.argv[3]) if len(sys.argv) > 3 else 12346
            print(port)
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
            start_server(global_state, port=port)

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

        elif mode == 'puppeteer':
            # Start a local puppeteer in PyBullet that updates global_state
            urdf_path = 'spot.urdf'
            if len(sys.argv) >= 3:
                urdf_path = sys.argv[2]
            # We'll run the puppeteer in a thread, then also start the server if desired.
            # Or we can just run it alone if we only want to update the local global_state.

            # Start puppeteer in a background thread
            updater_thread = threading.Thread(
                target=puppet_updater,
                args=(global_state, urdf_path),
                daemon=True
            )
            updater_thread.start()

            # Optionally start the server to broadcast the puppet changes
            # or just wait for user to Ctrl+C if no server is needed.
            print("Starting server so others can see the puppet updates...")
            start_server(global_state)

        else:
            print("Usage:")
            print("  server <folder_or_file>")
            print("  spot <hostname>")
            print("  plot_and_record [host] [port] [output_file]")
            print("  record <host> <port> <output_file>")
            print("  visual3d <host> <port> <urdf_file>")
            print("  puppeteer <urdf_file>")
    else:
        # Default to the combined plotting+recording client
        start_plotting_and_recording_client()
