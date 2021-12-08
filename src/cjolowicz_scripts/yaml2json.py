"""Convert YAML to JSON."""
import json
import sys

import yaml


def main() -> None:
    """Convert YAML to JSON."""
    data = yaml.safe_load(sys.stdin)

    json.dump(data, sys.stdout, sort_keys=True, indent=2)

    print()


if __name__ == "__main__":
    main()
