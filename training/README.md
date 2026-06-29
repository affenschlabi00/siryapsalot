# Training (Phase 5 — distill, then RLVR)

Checkpoints are gitignored. Phase 5 supervised-fine-tunes on distilled (intent → IR) data,
then runs RL with the harness as the verifiable reward (dense reward ladder: IR validates →
builds → loadable → runs → k/n tests → all tests → fewer instructions). Gated on a compute
decision (see `decisions.md`). Not yet built.
