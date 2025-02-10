import threading

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
