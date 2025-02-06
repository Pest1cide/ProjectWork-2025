
"""Copied from examples/get_robot_state.py """

import sys

import bosdyn.client
import bosdyn.client.util
from bosdyn.client.robot_state import RobotStateClient
import time
import os

def main():
    import argparse

    commands = {'state', 'hardware', 'metrics'}

    parser = argparse.ArgumentParser()
    bosdyn.client.util.add_base_arguments(parser)
    parser.add_argument('command', choices=list(commands), help='Command to run')
    options = parser.parse_args()

    # Create robot object with an image client.
    sdk = bosdyn.client.create_standard_sdk('RobotStateClient')
    robot = sdk.create_robot(options.hostname)
    bosdyn.client.util.authenticate(robot)
    robot_state_client = robot.ensure_client(RobotStateClient.default_service_name)

    # Make a robot state request
    if options.command == 'state':
        while True:
            joints = {}
            # for i in range(0,20):
                    #  print(robot_state_client.get_robot_state().kinematic_state.joint_states[i].name)
            joint_angles = list(map(lambda x: {"name": x.name, "position": x.position.value}, list(robot_state_client.get_robot_state().kinematic_state.joint_states)))
            for joint_angle in joint_angles:
                joints[joint_angle["name"]] = joint_angle["position"]
            # print(list(map(lambda x: {"name": x.name, "position": x.position}, list(robot_state_client.get_robot_state().kinematic_state.joint_states))))
            print(*joint_angles, sep='\n')
            # print(joints["fl.hx"])
            time.sleep(1)
            os.system('clear')
    elif options.command == 'hardware':
        print(robot_state_client.get_hardware_config_with_link_info())
    elif options.command == 'metrics':
        print(robot_state_client.get_robot_metrics())

    return True


if __name__ == '__main__':
    if not main():
        sys.exit(1)
