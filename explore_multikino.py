import json

def find_keys_with_value(d, target, path=""):
    if isinstance(d, dict):
        for k, v in d.items():
            new_path = f"{path}.{k}" if path else k
            if target.lower() in str(k).lower():
                print(f"Key match: {new_path}")
            find_keys_with_value(v, target, new_path)
    elif isinstance(d, list):
        for i, v in enumerate(d):
            new_path = f"{path}[{i}]"
            find_keys_with_value(v, target, new_path)

try:
    with open('c:/Users/Kacper Szatkowski/PycharmProjects/warsaw-cinema-aggregator/multikino_sample.json', encoding='utf-8') as f:
        data = json.load(f)
    print("Searching for 'showing'...")
    find_keys_with_value(data, "showing")
    print("\nSearching for 'session'...")
    find_keys_with_value(data, "session")
except Exception as e:
    print(f"Error: {e}")
