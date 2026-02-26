import json

with open("multikino_api_real.json", encoding="utf-8") as f:
    data = json.load(f)

def find_showings(d, path=""):
    if isinstance(d, dict):
        if "showings" in d and isinstance(d["showings"], list) and len(d["showings"]) > 0:
            print(f"FOUND showings at {path}")
            print(f"Number of showings here: {len(d['showings'])}")
            
            show0 = d['showings'][0]
            if isinstance(show0, dict) and 'fields' in show0:
                print(f"Sample showing fields: {show0['fields'].keys()}")
                print(f"Sample showing times: {[s['fields'].get('time') for s in d['showings'][:5]]}")
                print(f"Sample sessionIds: {[s['fields'].get('sessionId') for s in d['showings'][:5]]}")
            else:
                print(f"Sample showing: {show0}")
                
            if "title" in d or "filmName" in d:
                print(f"Film title/name here: {d.get('title', d.get('filmName'))}")
            elif "fields" in d and ("title" in d["fields"] or "filmName" in d["fields"]):
                print(f"Film title/name here: {d['fields'].get('title', d['fields'].get('filmName'))}")
        for k, v in d.items():
            find_showings(v, f"{path}.{k}" if path else k)
    elif isinstance(d, list):
        for i, v in enumerate(d):
            find_showings(v, f"{path}[{i}]")

find_showings(data["pageProps"])
