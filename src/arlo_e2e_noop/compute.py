from dataclasses import dataclass
from random import randint
from time import sleep
from typing import List, Dict, Optional, Sequence

import ray
from arlo_e2e_noop.ray_progress import ProgressBar
from arlo_e2e_noop.ray_reduce import ray_reduce_with_ray_wait
from arlo_e2e_noop.utils import shard_list_uniform
from ray import ObjectRef
from ray.actor import ActorHandle


# we need something roughly 4000 bits long to simulate the right data size
P = 1044388881413152506691752710716624382579964249047383780384233483283953907971553643537729993126875883902173634017777416360502926082946377942955704498542097614841825246773580689398386320439747911160897731551074903967243883427132918813748016269754522343505285898816777211761912392772914485521155521641049273446207578961939840619466145806859275053476560973295158703823395710210329314709715239251736552384080845836048778667318931418338422443891025911884723433084701207771901944593286624979917391350564662632723703007964229849154756196890615252286533089643184902706926081744149289517418249153634178342075381874131646013444796894582106870531535803666254579602632453103741452569793905551901541856173251385047414840392753585581909950158046256810542678368121278509960520957624737942914600310646609792665012858397381435755902851312071248102599442308951327039250818892493767423329663783709190716162023529669217300939783171415808233146823000766917789286154006042281423733706462905243774854543127239500245873582012663666430583862778167369547603016344242729592244544608279405999759391099775667746401633668308698186721172238255007962658564443858927634850415775348839052026675785694826386930175303143450046575460843879941791946313299322976993405829119
BATCH_SIZE = 10000  # number of ballots to "encrypt" at a time
BALLOTS_PER_SHARD_ENCRYPT = (
    4  # number of ballots to feed to the encrypt function at a time and partially tally
)
BALLOTS_PER_SHARD_TALLY = 10  # number of partial tallies to accumulate at once

PLAINTEXT_TYPE = Dict[str, int]
TALLY_TYPE = Dict[str, "Ciphertext"]

# make this larger than one, and it's as if you improved the performance
SLEEP_SPEEDUP = 1.0


@dataclass
class Ciphertext:
    # so cheesy it hurts!
    a: int
    b: int

    def decrypt(self) -> int:
        return self.a - self.b

    def __add__(self, other: "Ciphertext") -> "Ciphertext":
        return Ciphertext(self.a + other.a, self.b + other.b)


def add_tallies(*tallies: Optional[TALLY_TYPE]) -> Optional[TALLY_TYPE]:
    result: TALLY_TYPE = {}
    for ptally in tallies:
        if ptally is None:
            return None
        for k in ptally.keys():
            if k not in result:
                result[k] = ptally[k]
            else:
                result[k] = result[k] + ptally[k]
    return result


def partial_tally(
    progressbar_actor: Optional[ActorHandle], *ptallies: Optional[TALLY_TYPE]
) -> Optional[TALLY_TYPE]:
    num_ptallies = len(ptallies)

    result: Optional[TALLY_TYPE] = add_tallies(*ptallies)
    sleep(0.3 * len(ptallies) / SLEEP_SPEEDUP)
    if progressbar_actor is not None:
        progressbar_actor.update_completed.remote("Tallies", num_ptallies)
    return result


@ray.remote
def r_partial_tally(
    progressbar_actor: Optional[ActorHandle],
    *ptallies: Optional[TALLY_TYPE],
) -> Optional[TALLY_TYPE]:  # pragma: no cover
    """
    This is a front-end for `partial_tally`, that can be called remotely via Ray.
    """
    try:
        result = partial_tally(progressbar_actor, *ptallies)
        return result
    except Exception as e:
        print(f"Unexpected exception in r_partial_tally: {e}")
        return None


def encrypt_ballot(plain: PLAINTEXT_TYPE, key: int, nonce: int) -> TALLY_TYPE:
    sleep(3 / SLEEP_SPEEDUP)
    return {k: Ciphertext(plain[k] + key + nonce, key + nonce) for k in plain}


def decrypt_ballot(ciphertext: TALLY_TYPE) -> PLAINTEXT_TYPE:
    return {k: ciphertext[k].decrypt() for k in ciphertext}


def gen_nonce() -> int:
    return randint(1, P)


@ray.remote
def r_encrypt(
    progressbar_actor: Optional[ActorHandle],
    key: int,
    nonces: List[int],
    *ballots: PLAINTEXT_TYPE,
) -> Optional[TALLY_TYPE]:
    try:
        num_ballots = len(ballots)
        cballots: List[TALLY_TYPE] = []
        result: Optional[TALLY_TYPE] = {}
        for i in range(0, num_ballots):
            cballot = encrypt_ballot(ballots[i], key, nonces[i])
            cballots.append(cballot)
            if progressbar_actor is not None:
                progressbar_actor.update_completed.remote("Ballots", 1)
            result = add_tallies(result, cballot)
            sleep(0.3 / SLEEP_SPEEDUP)
            if progressbar_actor is not None:
                progressbar_actor.update_completed.remote("Tallies", 1)
        return result
    except Exception as e:
        print(f"Unexpected failure: {e}")
        return None


def tally_everything(
    ballots: List[PLAINTEXT_TYPE], use_progressbar: bool = True
) -> PLAINTEXT_TYPE:
    num_ballots = len(ballots)
    progressbar = (
        ProgressBar(
            {
                "Ballots": num_ballots,
                "Tallies": num_ballots,
                "Iterations": 0,
                "Batch": 0,
            }
        )
        if use_progressbar
        else None
    )
    progressbar_actor = progressbar.actor if progressbar is not None else None

    batches: Sequence[Sequence[PLAINTEXT_TYPE]] = shard_list_uniform(
        ballots, BATCH_SIZE
    )
    batch_tallies: List[ObjectRef] = []

    key_ref = ray.put(P)

    for batch in batches:
        if progressbar_actor:
            progressbar_actor.update_completed.remote("Batch", 1)

        sharded_inputs: Sequence[Sequence[PLAINTEXT_TYPE]] = shard_list_uniform(
            batch, BALLOTS_PER_SHARD_ENCRYPT
        )

        partial_tally_refs = [
            r_encrypt.remote(
                progressbar_actor,
                key_ref,
                [gen_nonce() for _ in sharded_inputs],
                *shard,
            )
            for shard in sharded_inputs
        ]

        btally = ray_reduce_with_ray_wait(
            partial_tally_refs,
            BALLOTS_PER_SHARD_TALLY,
            progressbar_actor,
            r_partial_tally.remote,
            progressbar,
            "Tallies",
            timeout=0.5,
        )

        batch_tallies.append(btally)

    if len(batch_tallies) > 1:
        btally = ray_reduce_with_ray_wait(
            batch_tallies,
            BALLOTS_PER_SHARD_TALLY,
            progressbar_actor,
            r_partial_tally.remote,
            progressbar,
            "Tallies",
            timeout=0.5,
        )
        tally = ray.get(btally)
    else:
        tally = ray.get(batch_tallies[0])

    if progressbar:
        progressbar.close()

    return decrypt_ballot(tally)


def tally_trivial(ballots: List[PLAINTEXT_TYPE]) -> PLAINTEXT_TYPE:
    result: PLAINTEXT_TYPE = {}
    for ballot in ballots:
        for k in ballot.keys():
            if k not in result:
                result[k] = ballot[k]
            else:
                result[k] = result[k] + ballot[k]
    return result
