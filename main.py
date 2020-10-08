# this script executes the Ray libraries with no-op data that's meant to emulate the behavior of our "real" application
import argparse
import os
from random import randint
from typing import List, Dict

import ray

from arlo_e2e_noop.compute import tally_everything, tally_generic


def gen_candidates(n: int) -> List[str]:
    return [f"Candidate{i:05d}" for i in range(0, n)]


def gen_ballots(n: int, candidates: List[str]) -> List[Dict[str, int]]:
    return [{name: randint(0, 1) for name in candidates} for i in range(0, n)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Runs a 'no-op' simulation of the arlo-e2e computation on Ray (either locally or on a remote cluster)"
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="uses Ray locally (Ray on a cluster by default)",
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="displays a progress-bar as the job runs (off by default)",
    )
    parser.add_argument(
        "--ballot-size",
        help="number of questions per ballot (default: 100)",
        type=int,
        default=100,
    )
    parser.add_argument(
        "--num-ballots",
        help="number of ballots (default: 100000)",
        type=int,
        default=100000,
    )
    parser.add_argument(
        "--speedup",
        help="factor to accelerate the computation (>1 == faster; <1 == slower, default=1.0)",
        type=float,
        default=1.0,
    )

    args = parser.parse_args()
    use_progressbar = args.progress
    ballot_size = args.ballot_size
    num_ballots = args.num_ballots
    speedup = args.speedup

    if not isinstance(speedup, float):
        print("What?")
        exit(1)

    if args.local:
        print("Using Ray locally.")
        ray.init(num_cpus=os.cpu_count())
    else:
        print("Using Ray on a cluster.")
        ray.init(address="auto")

    candidates = gen_candidates(ballot_size)
    ballots = gen_ballots(num_ballots, candidates)
    print("Input generated, starting computation.")

    tally = tally_everything(ballots, use_progressbar, speedup=speedup)
    trivial = tally_generic(*ballots)

    if tally != trivial:
        print("Tallies don't match! (key: expected, actual)")
        for k in sorted(tally.keys()):
            print(f"  {k}: {trivial[k]}, {tally[k]}")

    else:
        print("Tallies match, done.")
