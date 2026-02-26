import json

def find_paths(d, target, path=""):
    if isinstance(d, dict):
        for k, v in d.items():
            if k == target:
                print(f"Found key '{target}' at {path}.{k}")
            elif isinstance(v, str) and target in v:
                print(f"Found string '{target}' at {path}.{k}: {v[:50]}")
            find_paths(v, target, f"{path}.{k}" if path else k)
    elif isinstance(d, list):
        for i, v in enumerate(d):
            if isinstance(v, str) and target in v:
                print(f"Found string '{target}' at {path}[{i}]: {v[:50]}")
            find_paths(v, target, f"{path}[{i}]")

with open("multikino_mlociny.json", encoding="utf-8") as f:
    data = json.load(f)

find_paths(data, "sessionId")
