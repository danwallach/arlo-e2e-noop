# Arlo-e2e no-op simulator

This repo simulates the behavior of how arlo-e2e drives Ray for remote encryption and tallying.
Typical usage for a local run:

```
% python main.py --local --progress --num-ballots 100
```

For a remote run:
```
% python main.py --progress --num-ballots 100000
```

Dropping the `--progress` flag will eliminate the progressbar and its associated
remote actor. Another flag that might be useful is `--ballot-size N` where `N` specifies
how big each ballot will be, and thus there will be that much larger messages on the network.