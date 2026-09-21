# Backup, Restore and Cryptographic Replay

Run `JMORAIS_TEST_POSTGRES_URL=... python scripts/validate_backup_restore_replay.py` only against a disposable validation database. The command requires a valid source replay, creates a logical PostgreSQL backup, rebuilds the schema, restores it with `ON_ERROR_STOP`, and independently replays every stream. Command failure, tampering, or inventory mismatch fails closed.

Production restores must target a new isolated database. Promote only after migration consistency, `VALID` replay, package reconstruction, artifact checksum and operator approval are recorded. Never overwrite the sole database or backup.
