#!/usr/bin/env python3
"""The notebook's planner from a terminal, against a saved game.

    plan.py [--game NAME] status            what the factory adds up to
    plan.py [--game NAME] next [--apply]    the next move; --apply takes it and saves
    plan.py [--game NAME] ladder            the milestone ladder
    plan.py [--game NAME] upgrades          tiers researched that the modules do not use yet

`NAME` is a file written by `Factory.save()` (default `factory.json` in this directory). The notebook
(`game.ipynb`) is the real interface - this is for a quick look without starting a kernel.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from factory import Factory                        # noqa: E402


def load(name):
    path = name if os.path.exists(name) else os.path.join(HERE, f"{name}.json")
    if not os.path.exists(path):
        sys.exit(f"no saved game at {path}: build one in game.ipynb and call f.save()")
    return Factory.load(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", default="factory", help="saved game name or path (default factory)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    n = sub.add_parser("next")
    n.add_argument("--apply", action="store_true", help="take the move and save the game")
    sub.add_parser("ladder")
    sub.add_parser("upgrades")
    args = ap.parse_args()

    f = load(args.game)
    if args.cmd == "ladder":
        print(f.ladder())
    elif args.cmd == "upgrades":
        print("\n".join(f.upgrades()) or "nothing to upgrade: every module is on the best tier you have")
    elif args.cmd == "next":
        move = f.next()
        print(move)
        if args.apply and move.kind in ("build", "scale", "research", "supply"):
            f.apply(move)
            print(f"\napplied, saved to {f.save()}")
    else:
        print(f.status())
    return 0


if __name__ == "__main__":
    sys.exit(main())
