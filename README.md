# SpotDigitalTwin

## Installation:

### Downloading the SDK
```
git clone https://github.com/boston-dynamics/spot-sdk.git
```

### Installing venv
```
python3 -m pip install venv
```
### Initializing the virtual environment
```
python3 -m venv venv
```
### Activating the virtual environment
```
source /venv/bin/activate
```

### Installing python packages
```
python3 -m pip install --upgrade bosdyn-client bosdyn-mission bosdyn-choreography-client bosdyn-orbit
```

### Installing requirements
```
python3 -m pip install -r requirements.txt
```

## Check battery
```
https://10.0.0.30/battery
```

## vncserver
```
password: spot1234
```

## export BOSDYN_CLIENT
```
BOSDYN_CLIENT_USERNAME = rllab
BOSDYN_CLIENT_PASSWORD = robotlearninglab
```

## SPOT CONNECTION
```
Power on Spot by holding the power button down until the fans start. Wait for the fans to turn off.
```

### Step 1: Connect to Spot via wifi
```
WIFI_USERNAME = Spot
WIFI_PASSWORD = t98HRMRZY552
```

### Step 2: Ping Spot
```
Open a Terminal/Window Powershell to ping Spot at 10.0.0.30

Command: ping 10.0.0.30
BOSDYN_CLIENT_USERNAME = rllab
BOSDYN_CLIENT_PASSWORD = robotlearninglab
```

### Step 3: Request Spot robot ID
```
This step is used to check if you are now successfully communicating with Spot via Python.

Command: $ python3 -m bosdyn.client 10.0.0.30 id

The output returned shows your Spot robot unique serial number, its nickname and robot type (Boston Dynamics has multiple robots), the software version, and install date.

Example: 
beta-BD-90490007     02-19904-9903   beta29     spot (V3)
Software: 2.3.4 (b11205d698e 2020-12-11 11:53:12)
Installed: 2020-12-11 15:06:57

```

### Step 4: Run Python code
```
Open a Terminal/Window Powershell in the repository where you store the python file
Install dependent packages

Command: 
$ python3 -m pip install -r requirements.txt
$ python <name of file.py> 10.0.0.30
BOSDYN_CLIENT_USERNAME = rllab
BOSDYN_CLIENT_PASSWORD = robotlearninglab
```