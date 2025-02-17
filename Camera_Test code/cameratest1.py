import bosdyn.client
import bosdyn.client.util
from bosdyn.client.image import ImageClient
import cv2
import numpy as np

# Spot Robot IP Address (Update this based on your setup)
ROBOT_IP = "10.0.0.30"

# Connect to Spot
sdk = bosdyn.client.create_standard_sdk('SpotCameraClient')
robot = sdk.create_robot(ROBOT_IP)
bosdyn.client.util.authenticate(robot)  # Authenticate using stored credentials

# Create Image Client
image_client = robot.ensure_client(ImageClient.default_service_name)

# Request image from front stereo cameras (You can choose either left or right)
camera_sources = ['frontright_fisheye_image', 'frontleft_fisheye_image']
image_responses = image_client.get_image_from_sources(camera_sources)

# Define fisheye camera intrinsic parameters (Replace with actual values from Spot's documentation)
K = np.array([[600, 0, 320], [0, 600, 240], [0, 0, 1]])  # Camera matrix (fx, fy, cx, cy)
D = np.array([-0.3, 0.1, 0, 0, 0])  # Distortion coefficients

# Process the first image (frontright camera)
for img in image_responses:
    # Convert image data to OpenCV format
    np_img = np.frombuffer(img.shot.image.data, dtype=np.uint8)
    cv_image = cv2.imdecode(np_img, cv2.IMREAD_COLOR)

    # Undistort the fisheye image
    h, w = cv_image.shape[:2]
    new_K, roi = cv2.getOptimalNewCameraMatrix(K, D, (w, h), 1, (w, h))
    map1, map2 = cv2.initUndistortRectifyMap(K, D, None, new_K, (w, h), cv2.CV_16SC2)
    undistorted = cv2.remap(cv_image, map1, map2, interpolation=cv2.INTER_LINEAR)

    # Convert to grayscale
    gray = cv2.cvtColor(undistorted, cv2.COLOR_BGR2GRAY)

    # Apply Gaussian blur to reduce noise
    blurred = cv2.GaussianBlur(gray, (15, 15), 2)

    # Apply adaptive thresholding
    adaptive_thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY, 21, 5)  # Increased block size an
    
    # Define Region of Interest (ROI) - Modify as needed
    h, w = gray.shape
    roi = adaptive_thresh[int(h*0.3):int(h*0.9), int(w*0.2):int(w*0.8)]

    # Detect circles using HoughCircles
    circles = cv2.HoughCircles(roi, cv2.HOUGH_GRADIENT, dp=1.2, minDist=10,
                           param1=100, param2=70, minRadius=10, maxRadius=500)  # Increased param2
    
    # Debugging output
    if circles is not None:
        circles = np.uint16(np.around(circles))
        for i in circles[0, :]:
            print(f"Detected circle at X:{i[0]}, Y:{i[1]}, Radius:{i[2]}")
            cv2.circle(undistorted, (i[0] + int(w*0.2), i[1] + int(h*0.3)), i[2], (0, 255, 0), 2)
        print("Ball detected!")
    else:
        print("Not ball.")

    # Show the image with detected circles (for debugging)
    cv2.imshow("Spot Front Camera - Debug", undistorted)
    cv2.waitKey(0)  # Press any key to close window
    cv2.destroyAllWindows()
