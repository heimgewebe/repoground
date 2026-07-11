# RepoBrief upgrade and rollback

## Upgrade preconditions

An operator records:

- current deployed commit;
- target candidate commit and Git tree from the release manifest;
- candidate archive SHA-256;
- current configuration and runtime data backup;
- successful candidate verification.

Upgrade is performed by checking out the exact target commit, installing the
appropriate hash lock with `--require-hashes`, then running the repository test
and service smoke contracts. A candidate hash is never treated as permission
to deploy automatically.

## Rollback

Rollback means returning source and dependencies to the previously recorded
commit and lock files:

1. stop new jobs and preserve logs;
2. restore the previous exact commit in a clean checkout;
3. create a fresh environment from that commit's hash lock;
4. restore configuration or data only from the pre-upgrade backup when needed;
5. run the same smoke checks before reopening work;
6. record the failed target commit and reason.

Do not reuse a partially upgraded virtual environment. The lock files belong to
their commit, so rollback recreates the environment instead of attempting an
in-place package downgrade.

## Limits

This procedure proves neither data-migration reversibility nor compatibility
with every deployment host. Any future stateful migration requires its own
forward and reverse evidence before deployment.
