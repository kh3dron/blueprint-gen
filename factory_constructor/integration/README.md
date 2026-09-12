Constructor engine evidence

Both declarations were compiled from fresh observations, serialized to JSON, and interpreted
by the same `Executor` and `PlayerPort` on Factorio 2.1.17. Each program completed its observed
subgoals and passed the independent connected-production verifier.

| Declaration | Generated lines / builds | Measured plates/min, five minutes | Connected coal buffer gain | Execution time |
| --- | --- | --- | --- | --- |
| 10 iron plates/min | 1 / 44 | 15, 15, 15, 15, 15 | 45 coal | 46.102 s |
| 20 iron plates/min | 2 / 62 | 30, 30, 30, 30, 30 | 25 coal | 150.433 s |

The first run used the paid iron-ready checkpoint. The second started from feed-ready,
completed that existing prerequisite, and executed the generated procurement bill: 104 iron
ore, 7 copper ore, 14 coal, 20 stone and a request for 6 wood. Whole-tree harvesting yielded
8 wood, which the final inventory ledger accounts for. Time includes the second run's feed
setup and procurement, and excludes approximately five seconds of client shutdown. Neither run
captured images. Both final saves passed ZIP integrity validation before shutdown.

Raw runs are `/tmp/constructor-iron-10-03` and `/tmp/constructor-iron-20-01`. Their client logs
record `Disconnecting multiplayer connection. Reason: Quit.` followed by `Goodbye`. The test
runner closes the client deliberately; the disconnect handshake took about five seconds.

`fixtures/iron-10.json.gz` and `fixtures/iron-20.json.gz` contain ordinary JSON compressed to
62,119 and 79,337 bytes. They preserve the program, execution state, compact report and all
inputs needed to replay the service/payment verifier. Earlier action receipts outside the
constructor's revision boundary are excluded. Existing prerequisite evidence remains in the
numbered experiment fixtures. The legacy service verifier's `goal_complete: false` refers to
the unfinished red-science milestone; `summary.goal_complete` and the program execution state
refer to the actual iron declaration.

The regression tests replay both physical verifications, bind every native action to its plan
node and declared goal, verify the generated procurement, and reject false idle-recipe evidence.
The one-line run exposed a native furnace boundary state: an empty furnace can clear its recipe
between deliveries. That state is accepted only with zero progress and empty input/output;
native products, ore consumption, collected plates and fuel must still balance over every window.
The earlier direction-drift rejection tests remain in experiment 13. A negative probe is not
part of the user's normal construction program.

Retain another successful run with:

```sh
.venv/bin/python -m factory_constructor.integration.retain_evidence \
  /tmp/constructor-iron-new factory_constructor/integration/fixtures/iron-new.json.gz
```

This is a bounded proof of goal-dependent construction and player interpretation. The initial
coal/power boundary is established by earlier experiments. Recursive composition, incremental
deployment reuse, arbitrary terrain and automatic red science remain unproven.
