from dataclasses import dataclass
from random import randint
from time import sleep
from typing import List, Dict, Optional, Sequence

import ray
from ray import ObjectRef
from ray.actor import ActorHandle

from ray_progress import ProgressBar
from utils import shard_list_uniform


# we need something roughly 4000 bits long to simulate the right data size
P = 1044388881413152506691752710716624382579964249047383780384233483283953907971553643537729993126875883902173634017777416360502926082946377942955704498542097614841825246773580689398386320439747911160897731551074903967243883427132918813748016269754522343505285898816777211761912392772914485521155521641049273446207578961939840619466145806859275053476560973295158703823395710210329314709715239251736552384080845836048778667318931418338422443891025911884723433084701207771901944593286624979917391350564662632723703007964229849154756196890615252286533089643184902706926081744149289517418249153634178342075381874131646013444796894582106870531535803666254579602632453103741452569793905551901541856173251385047414840392753585581909950158046256810542678368121278509960520957624737942914600310646609792665012858397381435755902851312071248102599442308951327039250818892493767423329663783709190716162023529669217300939783171415808233146823000766917789286154006042281423733706462905243774854543127239500245873582012663666430583862778167369547603016344242729592244544608279405999759391099775667746401633668308698186721172238255007962658564443858927634850415775348839052026675785694826386930175303143450046575460843879941791946313299322976993405829119
BATCH_SIZE = 10000  # number of ballots to "encrypt" at a time
BALLOTS_PER_SHARD_ENCRYPT = 4  # number of ballots to feed to the encrypt function at a time and partially tally
BALLOTS_PER_SHARD_TALLY = 10  # number of partial tallies to accumulate at once


@dataclass
class Ciphertext:
    # so cheesy it hurts!
    a: int
    b: int

    def decrypt(self) -> int:
        return self.a - self.b

    def __add__(self, other: 'Ciphertext') -> 'Ciphertext':
        return Ciphertext(self.a + other.a, self.b + other.b)


def add_tallies(*tallies: Dict[str, Ciphertext]) -> Dict[str, Ciphertext]:
    # this one does no waiting and no progressbars
    result: Dict[str, Ciphertext] = {}
    for ptally in tallies:
        for k in ptally.keys():
            if k not in result:
                result[k] = ptally[k]
            else:
                result[k] = result[k] + ptally[k]
    return result


def partial_tally(
    progressbar_actor: Optional[ActorHandle],
    ptallies: List[Dict[str, Ciphertext]]
) -> Dict[str, Ciphertext]:
    num_ptallies = len(ptallies)

    result: Dict[str, Ciphertext] = add_tallies(*ptallies)
    sleep(0.3 * len(ptallies))
    if progressbar_actor is not None:
        progressbar_actor.update_completed.remote("Tallies", num_ptallies)
    return result


def encrypt_ballot(plain: Dict[str, int], key: int, nonce: int) -> Dict[str, Ciphertext]:
    sleep(3)
    return {k: Ciphertext(n + key + nonce, key + nonce) for k, n in plain}


def decrypt_ballot(ciphertext: Dict[str, Ciphertext]) -> Dict[str, int]:
    sleep(0.3)
    return {k: v.decrypt() for k, v in ciphertext}


def gen_nonce() -> int:
    return randint(1, P)


@ray.remote
def r_encrypt(progressbar_actor: Optional[ActorHandle], key: int, nonces: List[int], *ballots: Dict[str, int]) -> Optional[Dict[str, Ciphertext]]:
    try:
        num_ballots = len(ballots)
        cballots: List[Dict[str, Ciphertext]] = []
        result: Dict[str, Ciphertext] = {}
        for i in range(0, num_ballots):
            cballot = encrypt_ballot(ballots[i], key, nonces[i])
            cballots.append(cballot)
            if progressbar_actor is not None:
                progressbar_actor.update_completed.remote("Ballots", 1)
            result = add_tallies(result, cballot)
            sleep(0.3)
            if progressbar_actor is not None:
                progressbar_actor.update_completed.remote("Tallies", 1)
        return result
    except Exception as e:
        print(f"Unexpected failure: {e}")
        return None


def tally_everything(ballots: List[Dict[str, int]], use_progressbar: bool = True) -> None:
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

    batches: Sequence[Sequence[Dict[str, int]]] = shard_list_uniform(ballots, BATCH_SIZE)
    batch_tallies: List[ObjectRef] = []

    key_ref = ray.put(P)

    for batch in batches:
        if progressbar_actor:
            progressbar_actor.update_completed.remote("Batch", 1)

        num_ballots_in_batch = len(batch)
        sharded_inputs: Sequence[Sequence[Dict[str, int]]] = shard_list_uniform(batch, BALLOTS_PER_SHARD_ENCRYPT)
        num_shards = len(sharded_inputs)

        partial_tally_refs = [
            r_encrypt.remote(
                progressbar_actor,
                key_ref,
                [gen_nonce() for _ in sharded_inputs]
                *shard,
            )
            for shard in sharded_inputs
        ]

        # log_and_print("Remote tallying.")
        btally = ray_tally_ballots(partial_tally_refs, progressbar)
        batch_tallies.append(btally)


