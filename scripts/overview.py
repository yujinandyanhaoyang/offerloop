"""Compatibility entry for the one current-work view."""
import json
from workspace import refresh

def main():
    print(json.dumps(refresh(), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
