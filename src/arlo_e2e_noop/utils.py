from math import ceil, floor
from typing import (
    TypeVar,
    Sequence,
    Iterable,
)

T = TypeVar("T")
U = TypeVar("U")


def shard_list(input: Iterable[T], num_per_group: int) -> Sequence[Sequence[T]]:
    """
    Breaks a list up into a list of lists, with `num_per_group` entries in each group,
    except for the final group which might be smaller. Useful for many things, including
    dividing up work units for parallel dispatch.
    """
    assert num_per_group >= 1, "need a positive number of list elements per group"
    input_list = list(input)
    length = len(input_list)
    return [input_list[i : i + num_per_group] for i in range(0, length, num_per_group)]


def shard_list_uniform(input: Iterable[T], num_per_group: int) -> Sequence[Sequence[T]]:
    """
    Similar to `shard_list`, but using a error residual propagation technique
    to ensure that the minimum and maximum number of elements per shard differ
    by at most one. The maximum number of elements per group will be less than
    or equal to `num_per_group`.
    """
    assert num_per_group >= 1, "need a positive number of list elements per group"
    input_list = list(input)
    length = len(input_list)
    if length == 0:
        return []

    num_groups = ceil(length / num_per_group)

    # this will be a floating point number, not an integer
    num_per_group_revised = length / num_groups

    output = []

    # leftover error, akin to Floyd-Steinberg dithering
    # (https://en.wikipedia.org/wiki/Floyd%E2%80%93Steinberg_dithering)
    residual = 0.0

    while input_list:
        current_num_per_group_float = num_per_group_revised + residual
        current_num_per_group_int = floor(num_per_group_revised + residual)
        residual = current_num_per_group_float - current_num_per_group_int

        # With floating point approximations, we might get really close but not quite, so we'll compensate
        # for this by saying if we're within epsilon of adding one more, we'll treat it as good enough.
        if residual > 0.99:
            current_num_per_group_int += 1
            residual = current_num_per_group_float - current_num_per_group_int

        output.append(input_list[:current_num_per_group_int])
        input_list = input_list[current_num_per_group_int:]

    return output
