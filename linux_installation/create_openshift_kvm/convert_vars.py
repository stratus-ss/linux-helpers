import sys
import yaml
import json

if len(sys.argv) != 3:
    print("Usage: python yaml2json.py vars.yaml vars.json")
    sys.exit(1)

with open(sys.argv[1], 'r') as yaml_file:
    data = yaml.safe_load(yaml_file)

with open(sys.argv[2], 'w') as json_file:
    json.dump(data, json_file, indent=2)
