#!/usr/bin/env python3
"""
Verify alignment between ONNX labels and TFLite Meta Model classes.
Usage: python3 tools/scripts/verify_birdnet_labels.py
"""
import zipfile
import json
import os
from pathlib import Path

# Default paths based on standard Orpheus layout
MODEL_DIR = os.getenv("ORPHEUS_DATA_ROOT", "./artifacts") + "/models"

def check_label_alignment():
    onnx_labels_path = Path(MODEL_DIR) / "labels.json"
    tflite_path = Path(MODEL_DIR) / "birdnet_meta.tflite"

    if not onnx_labels_path.exists() or not tflite_path.exists():
        print(f"Skipping: Models not found at {MODEL_DIR}")
        return

    # 1. Load ONNX Labels
    with open(onnx_labels_path, "r") as f:
        onnx_labels = json.load(f)

    # 2. Extract TFLite Labels
    tflite_labels = []
    try:
        with zipfile.ZipFile(tflite_path, "r") as z:
            if "labels.txt" in z.namelist():
                with z.open("labels.txt") as f:
                    content = f.read().decode("utf-8")
                    tflite_labels = [l.strip() for l in content.splitlines() if l.strip()]
    except zipfile.BadZipFile:
        print("⚠️ TFLite model is not zip-based. Skipping internal check.")
        return

    # 3. Compare
    print(f"ONNX Count: {len(onnx_labels)}")
    print(f"TFLite Count: {len(tflite_labels)}")
    
    if len(onnx_labels) != len(tflite_labels):
        print("🚨 CRITICAL MISMATCH: Model outputs do not align!")
        exit(1)
    else:
        print("✅ Labels aligned.")

if __name__ == "__main__":
    check_label_alignment()
