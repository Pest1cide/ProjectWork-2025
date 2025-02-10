import socket
import time
import sys
import json
import threading

try:
    import pybullet as p
    import pybullet_data
except ImportError:
    p = None

def start_3d_visualization_client(host='127.0.0.1', port=12346, urdf_path='spot.urdf'):
    """
    A client that connects to the server, receives joint data, and displays a 3D visualization
    of the robot using PyBullet. The URDF file must be specified (or default to 'spot.urdf'),
    and the joint names from the server should match the URDF's joint naming.

    We also load a floor (plane) so that if the URDF is not fixed, the robot
    can fall onto the ground.
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
    p.resetDebugVisualizerCamera(cameraDistance=3.0, cameraYaw=30, cameraPitch=-30, cameraTargetPosition=[0,0,0])
    p.setGravity(0,0,-9.81)
    p.setRealTimeSimulation(1)

    # Load a floor (plane)
    plane_id = p.loadURDF("plane.urdf", [0,0,0])

    # Load the robot URDF (not a fixed base, so it can fall)
    try:
        robot_id = p.loadURDF(urdf_path, [0,0,1], useFixedBase=False)
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
                                    # We use resetJointState for simplicity. Alternatively, use setJointMotorControl2.
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
