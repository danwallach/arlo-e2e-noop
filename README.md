# Arlo-e2e no-op simulator

This repo simulates the behavior of how arlo-e2e drives Ray for remote encryption and tallying.
Typical usage for a local run:

```
% python main.py --local --progress --num-ballots 100
```

For a remote run, something more like:
```
% ray submit main.py aws-config.yaml -- --progress --num-ballots 100000
```

Dropping the `--progress` flag will eliminate the progressbar and its associated
remote actor. Another flag that might be useful is `--ballot-size N` where `N` specifies
how big each ballot will be, and thus there will be that much larger messages on the network.

Another useful flag is `--speedup` which lets you vary the amount of time spent simulating computation.
`--speedup 2.0` makes things much faster. `--speedup 0.5` makes things much slower. This lets you
control the volume of communication over time.