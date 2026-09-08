#!/usr/bin/env python3
"""Prepare a capture-specific review or import a Factorio observer export."""
import argparse
import json
from pathlib import Path
import sys

from advisor_core.game_import import import_capture, review_template


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    review = sub.add_parser("review", help="write unknown routing/supply/power fields for this capture")
    review.add_argument("capture", type=Path)
    review.add_argument("--out", type=Path, required=True)
    convert = sub.add_parser("convert", help="write a snapshot and the game's resolved ruleset")
    convert.add_argument("capture", type=Path)
    convert.add_argument("--review", type=Path)
    convert.add_argument("--out", type=Path, required=True)
    convert.add_argument("--rules-out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        inputs = [args.capture] + ([args.review] if getattr(args, "review", None) else [])
        outputs = [args.out] + ([args.rules_out] if hasattr(args, "rules_out") else [])
        if len({p.resolve() for p in inputs + outputs}) != len(inputs + outputs):
            raise ValueError("capture, review, snapshot and rules output must use distinct paths")
        capture = json.loads(args.capture.read_text())
        if args.command == "review":
            args.out.write_text(json.dumps(review_template(capture), indent=2) + "\n")
            print(f"Wrote {args.out}. Null fields remain unverified; fill only facts checked for this capture.")
        else:
            reviewed = json.loads(args.review.read_text()) if args.review else None
            snapshot, rules = import_capture(capture, reviewed)
            args.rules_out.write_text(json.dumps(rules.document, indent=2) + "\n")
            snapshot.save(args.out)
            print(f"Wrote {args.out} and {args.rules_out}; {len(snapshot.document['observation_gaps'])} observation gaps.")
            for note in snapshot.document["provenance"]["notes"]:
                print(note)
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"import-game: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
