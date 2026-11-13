import argparse
import json
from .dataset import OUT, discover
from .operational import release, batch

def main():
    p = argparse.ArgumentParser(description="Independent daily-price extension; never runs protected evaluations")
    p.add_argument("command", choices=["discover", "evaluate-development", "release", "batch", "build"])
    p.add_argument("--issue", help="Timezone-aware issue timestamp; default now in IST")
    a = p.parse_args()
    if a.command in ("discover", "build"):
        discover()
    if a.command == "evaluate-development":
        from .evaluate import study
        study(json.loads((OUT / "catalog.json").read_text(encoding="utf-8")))
    if a.command in ("release", "build"):
        release()
    if a.command in ("batch", "build"):
        batch(a.issue)

if __name__ == "__main__":
    main()
