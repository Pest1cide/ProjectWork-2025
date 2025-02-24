import os
os.environ["OMP_NUM_THREADS"] = "1"
import torch
import numpy as np
import cv2
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans
from transformers import AutoModel, AutoImageProcessor

# Fix memory leak warning in Windows
os.environ["OMP_NUM_THREADS"] = "1"

# Load DINOv2 model and processor
device = "cuda" if torch.cuda.is_available() else "cpu"
model_name = "facebook/dinov2-base"
#processor = AutoImageProcessor.from_pretrained(model_name, use_fast=True)  # Explicitly set use_fast=True
processor = AutoImageProcessor.from_pretrained(model_name)

model = AutoModel.from_pretrained(model_name).to(device)
model.eval()

def extract_features(image):
    """Extracts DINOv2 features from an image"""
    inputs = processor(images=image, return_tensors="pt").to(device)
    with torch.no_grad():
        features = model(**inputs).last_hidden_state[:, 1:, :]  # Ignore CLS token
    
    return features.squeeze(0).cpu().numpy()  # Shape: (256, feature_dim)

def segment_image(image, k=3):
    """Clusters image features to segment the ball"""
    img_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    img_resized = cv2.resize(img_rgb, (224, 224))  # Resize for model input

    # Extract features
    features = extract_features(img_resized)  # Shape: (256, feature_dim)
    
    # K-Means clustering
    kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = kmeans.fit_predict(features)  # Shape: (256,)

    # DINOv2 extracts a 16x16 feature grid for a 224x224 image
    segmented = labels.reshape(16, 16)  # Ensure correct reshaping

    return segmented

def detect_ball(image, segmented_mask):
    """Finds the largest segmented region (ball) and draws a bounding box"""
    mask_resized = cv2.resize(segmented_mask.astype(np.uint8), (image.shape[1], image.shape[0]), interpolation=cv2.INTER_NEAREST)
    
    # Convert mask to binary
    mask_binary = (mask_resized == mask_resized.max()).astype(np.uint8) * 255  # Highlight only the largest cluster

    # Find contours
    contours, _ = cv2.findContours(mask_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Select the largest contour (assuming it's the ball)
    if contours:
        largest_contour = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(largest_contour)
        
        # Draw bounding box on a copy of the image
        output_image = image.copy()
        cv2.rectangle(output_image, (x, y), (x+w, y+h), (0, 255, 0), 3)  # Green box
        return output_image
    return image  # Return original image if no ball is found

# Load and process input image
image_path = "ball.jpg"  # Change to your image file
image = cv2.imread(image_path)

# Ensure the image is loaded correctly
if image is None:
    raise FileNotFoundError(f"Could not load image at path: {image_path}")

# Segment the ball using DINOv2 features
segmented_mask = segment_image(image)

# Detect and highlight the ball
output_image = detect_ball(image, segmented_mask)

# Display result
plt.figure(figsize=(8, 6))
plt.imshow(cv2.cvtColor(output_image, cv2.COLOR_BGR2RGB))
plt.axis("off")
plt.show()
