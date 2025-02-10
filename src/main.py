import os
import threading
import queue
import tkinter as tk
from tkinter import scrolledtext, simpledialog, filedialog, messagebox
from globals import GlobalRobotState
from updaters import interpolation_updater, replay_updater, spot_data_updater
from server import start_server
from plot_client import start_plotting_and_recording_client
from viz_client import start_3d_visualization_client
import bosdyn.client
import bosdyn.client.util
from bosdyn.client.robot_state import RobotStateClient

class MainApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Robot Control GUI")
        self.global_state = GlobalRobotState()
        self.log_queue = queue.Queue()
        self.current_updater_thread = None
        self.updater_lock = threading.Lock()
        
        # Menu Frame
        self.menu_frame = tk.Frame(root)
        self.menu_frame.pack(pady=10)
        
        tk.Button(self.menu_frame, text="Start Server", command=self.start_server).grid(row=0, column=0, padx=5, pady=5)
        tk.Button(self.menu_frame, text="Change Updater", command=self.change_updater).grid(row=0, column=1, padx=5, pady=5)
        tk.Button(self.menu_frame, text="Connect to Spot Robot", command=self.connect_spot).grid(row=1, column=0, padx=5, pady=5)
        tk.Button(self.menu_frame, text="Start Plot & Record", command=self.start_plot_record).grid(row=1, column=1, padx=5, pady=5)
        tk.Button(self.menu_frame, text="Start 3D Viz", command=self.start_3d_viz).grid(row=2, column=0, padx=5, pady=5)
        tk.Button(self.menu_frame, text="Quit", command=self.quit_app).grid(row=2, column=1, pady=10)
        
        # Log Display
        self.log_text = scrolledtext.ScrolledText(root, height=15, width=80, state='disabled')
        self.log_text.pack(pady=10)
        
        # Start log update thread
        self.log_thread = threading.Thread(target=self.log_worker, daemon=True)
        self.log_thread.start()
    
    def log_worker(self):
        while True:
            while not self.log_queue.empty():
                message = self.log_queue.get()
                self.log_text.config(state='normal')
                self.log_text.insert(tk.END, message + "\n")
                self.log_text.config(state='disabled')
                self.log_text.yview(tk.END)
    
    def start_server(self):
        path = filedialog.askopenfilename(title="Select Folder for Interpolation or JSON File for Replay", filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        
        if os.path.isdir(path):
            updater_type = "interpolation"
        else:
            updater_type = "replay"
        
        self.start_updater(path, updater_type)
        threading.Thread(target=start_server, args=(self.global_state,), daemon=True).start()
        self.log_queue.put("Server started with provided path")
    
    def start_updater(self, path, updater_type):
        with self.updater_lock:
            if self.current_updater_thread and self.current_updater_thread.is_alive():
                self.log_queue.put("Stopping current updater...")
                self.current_updater_thread = None
        
            if updater_type == "interpolation":
                self.current_updater_thread = threading.Thread(target=interpolation_updater, args=(path, self.global_state), daemon=True)
                self.log_queue.put(f"Interpolation updater started for: {path}")
            elif updater_type == "replay":
                self.current_updater_thread = threading.Thread(target=replay_updater, args=(path, self.global_state), daemon=True)
                self.log_queue.put(f"Replay updater started for: {path}")
            else:
                self.log_queue.put("Invalid updater type selected.")
                return
        
            self.current_updater_thread.start()
    
    def change_updater(self):
        if not self.current_updater_thread:
            self.log_queue.put("No active updater found. Start the server first.")
            return
        
        path = filedialog.askopenfilename(title="Select New Folder for Interpolation or JSON File for Replay", filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        
        if os.path.isdir(path):
            updater_type = "interpolation"
        else:
            updater_type = "replay"
        
        self.start_updater(path, updater_type)
    
    def connect_spot(self):
        spot_hostname = simpledialog.askstring("Connect to Spot", "Enter Spot hostname:")
        if spot_hostname:
            try:
                sdk = bosdyn.client.create_standard_sdk("SpotRealDataServer")
                robot = sdk.create_robot(spot_hostname)
                bosdyn.client.util.authenticate(robot)
                rsc = robot.ensure_client(RobotStateClient.default_service_name)
                threading.Thread(target=spot_data_updater, args=(rsc, self.global_state), daemon=True).start()
                self.log_queue.put("Spot data updater + server started.")
            except Exception as e:
                self.log_queue.put(f"Error connecting to Spot: {e}")
    
    def start_plot_record(self):
        host = simpledialog.askstring("Plot & Record", "Host:", initialvalue="127.0.0.1")
        port = simpledialog.askinteger("Plot & Record", "Port:", initialvalue=12345)
        out_file = simpledialog.askstring("Plot & Record", "Output file:", initialvalue="recorded_data.jsonl")
        threading.Thread(target=start_plotting_and_recording_client, args=(host, port, out_file), daemon=True).start()
        self.log_queue.put(f"Started Plot+Record client to {host}:{port} -> {out_file}")
    
    def start_3d_viz(self):
        host = simpledialog.askstring("3D Viz", "Host:", initialvalue="127.0.0.1")
        port = simpledialog.askinteger("3D Viz", "Port:", initialvalue=12346)
        urdf = filedialog.askopenfilename(title="Select URDF File", filetypes=[("URDF files", "*.urdf"), ("All files", "*.*")])
        if urdf:
            threading.Thread(target=start_3d_visualization_client, args=(host, port, urdf), daemon=True).start()
            self.log_queue.put(f"3D Viz client started, connecting to {host}:{port} URDF='{urdf}'")
    
    def quit_app(self):
        self.root.quit()

if __name__ == "__main__":
    root = tk.Tk()
    app = MainApp(root)
    root.mainloop()