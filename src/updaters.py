import time
import os
import json

# If you have bosdyn libraries, you can import them here.
import bosdyn.client
import bosdyn.client.util
from bosdyn.client.robot_state import RobotStateClient

from globals import GlobalRobotState

UPDATE_FREQUENCY = 10

def spot_data_updater(robot_state_client: RobotStateClient,
                      global_state: GlobalRobotState,
                      update_rate=2.5):
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

def interpolate(val1, val2, fraction):
    return val1 + (val2 - val1) * fraction

def interpolation_updater(folder_path, global_state: GlobalRobotState,
                          period=10, update_frequency=UPDATE_FREQUENCY):
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

def replay_updater(file_path, global_state: GlobalRobotState,
                   update_frequency=UPDATE_FREQUENCY, period=0.1):
    """
    Continuously replay lines from a single JSONL file, interpolating
    between successive lines. Each pair of lines is interpolated over 'period' seconds.
    """
    # Read and parse all lines into a list of dictionaries
    lines = []
    with open(file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    data = json.loads(line)
                    lines.append(data)
                except json.JSONDecodeError:
                    pass

    if len(lines) < 2:
        print("At least two lines are required for interpolation. Falling back to simple replay.")
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
        return

    steps = int(period * update_frequency)
    sleep_time = 1.0 / update_frequency

    try:
        while True:
            # Forward pass
            for i in range(len(lines) - 1):
                data1 = lines[i]
                data2 = lines[i + 1]
                for j in range(steps + 1):
                    fraction = j / steps
                    interp_dict = {}
                    all_keys = set(data1.keys()) | set(data2.keys())
                    for key in all_keys:
                        v1 = data1.get(key, 0)
                        v2 = data2.get(key, 0)
                        if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                            interp_dict[key] = interpolate(v1, v2, fraction)
                        else:
                            interp_dict[key] = v1 if fraction < 0.5 else v2

                    global_state.set_data(interp_dict)
                    time.sleep(sleep_time)

            # Backward pass
            for i in range(len(lines) - 1, 0, -1):
                data1 = lines[i]
                data2 = lines[i - 1]
                for j in range(steps + 1):
                    fraction = j / steps
                    interp_dict = {}
                    all_keys = set(data1.keys()) | set(data2.keys())
                    for key in all_keys:
                        v1 = data1.get(key, 0)
                        v2 = data2.get(key, 0)
                        if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                            interp_dict[key] = interpolate(v1, v2, fraction)
                        else:
                            interp_dict[key] = v1 if fraction < 0.5 else v2

                    global_state.set_data(interp_dict)
                    time.sleep(sleep_time)
    except Exception as e:
        print("Replay updater thread ending:", e)
