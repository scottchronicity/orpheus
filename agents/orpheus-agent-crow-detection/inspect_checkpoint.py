import torch
import sys

path = "/path/to/data/orpheus/models/mt_70.pt" # Update if needed

try:
    print(f"Loading {path}...")
    chk = torch.load(path, map_location='cpu')
    
    # Unwrap
    if isinstance(chk, dict):
        if 'state_dict' in chk: chk = chk['state_dict']
        elif 'model' in chk: chk = chk['model']
        
    print("\n=== LAYER STRUCTURE ===")
    for key, value in chk.items():
        # Only print weights to save space (skip biases/running_stats)
        if "weight" in key and "bias" not in key:
            print(f"{key:<30} | Shape: {list(value.shape)}")
            
except Exception as e:
    print(f"Error: {e}")
