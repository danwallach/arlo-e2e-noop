# This is an attempt to build a more sophisticated reducer that takes as much advantage of the
# associate & commutative nature of what we're doing -- that is, we can compute the ballot tallies
# in any order.

# The implementation seems to run correctly, and slightly faster than the version that does everything
# in order, but the progress-bar support is somehow broken. (Stutters, pauses. Doesn't terminate at
# 100%.) And it's deeply unclear that this code scales to huge clusters. ray.wait() may or may not
# be able to handle that many ObjectRefs.

from typing import Iterable, Callable, Optional, List, Tuple, Any, Sequence

import ray
from ray import ObjectRef

from arlo_e2e_noop.ray_progress import ProgressBar
from arlo_e2e_noop.utils import shard_list_uniform


def ray_reduce_with_ray_wait(
    inputs: Iterable[ObjectRef],
    shard_size: int,
    reducer_first_arg: Any,
    reducer: Callable,  # Callable[[Any, VarArg(ObjectRef)], ObjectRef]
    progressbar: Optional[ProgressBar] = None,
    progressbar_key: Optional[str] = None,
    timeout: float = None,
    verbose: bool = False,
) -> ObjectRef:
    assert (
        progressbar_key and progressbar
    ) or not progressbar, "progress bar requires a key string"
    assert shard_size > 1, "shard_size must be greater than one"
    assert timeout is None or timeout > 0, "negative timeouts aren't allowed"

    iteration_count = 0
    inputs = list(inputs)
    result: Optional[ObjectRef] = None

    while inputs:
        if progressbar:
            progressbar.actor.update_completed.remote("Iterations", 1)
            progressbar.print_update()

        iteration_count += 1
        # log_and_print(
        #     f"REDUCER ITERATION {iteration_count}: starting with {len(inputs)}",
        #     verbose=verbose,
        # )
        num_inputs = len(inputs)
        max_returns = shard_size * shard_size
        num_returns = max_returns if num_inputs >= max_returns else num_inputs
        tmp: Tuple[List[ObjectRef], List[ObjectRef]] = ray.wait(
            inputs, num_returns=num_returns, timeout=timeout
        )
        ready_refs, pending_refs = tmp
        num_ready_refs = len(ready_refs)
        num_pending_refs = len(pending_refs)
        assert (
            num_inputs == num_pending_refs + num_ready_refs
        ), "ray.wait fail: we lost some inputs!"

        # log_and_print(
        #     f"ray.wait() returned: ready({num_ready_refs}), pending({num_pending_refs})",
        #     verbose=verbose,
        # )

        if num_ready_refs == 1 and num_pending_refs == 0:
            # terminal case: we have one result ready and nothing pending; we're done!
            # log_and_print("Complete!", verbose=verbose)
            result = ready_refs[0]
            break
        if num_ready_refs >= 2:
            # general case: we have at least two results ready

            shards = shard_list_uniform(ready_refs, shard_size)
            size_one_shards = [s for s in shards if len(s) == 1]
            usable_shards = [s for s in shards if len(s) > 1]
            total_usable = sum(len(s) for s in usable_shards)
            # log_and_print(
            #     f"launching reduction: {total_usable} total usable values in {len(usable_shards)} shards, {len(size_one_shards)} size-one shards",
            #     verbose=verbose,
            # )

            if progressbar:
                progressbar.actor.update_total.remote(progressbar_key, total_usable)

            # dispatches jobs to remote workers, returns immediately with ObjectRefs
            partial_results = [reducer(reducer_first_arg, *s) for s in usable_shards]

            inputs = list(
                partial_results + pending_refs + [x[0] for x in size_one_shards]
            )

            assert len(inputs) < num_inputs, "reducer fail: we didn't shrink the inputs"
        else:
            # annoying case: we have exactly one result and nothing useful to do with it
            pass

    assert result is not None, "reducer fail: somehow exited the loop with no result"
    return result
