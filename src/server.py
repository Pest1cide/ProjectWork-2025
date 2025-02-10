import socket
import time
import json
import threading
from globals import GlobalRobotState

def handle_client(conn, addr, global_state: GlobalRobotState, send_rate=10):
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

def start_server(global_state: GlobalRobotState,
                 host='127.0.0.1', port=12346, send_rate=10):
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
