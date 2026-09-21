# Software Supply-Chain Security

## Trust chain and release identity

RC artifacts follow `source revision → hash-locked dependencies → build → SBOM → SCA/SAST/secret scan → artifact digest → provenance → signature → verification`. `jmoraIs.__version__` is the sole application-version source; packaging reads it dynamically, deployment audit imports it, and OCI labels receive the same value as an explicit build argument.

`ReleaseIdentity` binds application version, full Git revision, build ID, Python version, Alembic head, production-lock SHA-256, container/archive SHA-256, UTC build timestamp and `supply-chain-policy-v1`. The release manifest stores only report paths and digests, plus measured test/coverage and approved COMPLETE_CASE/replay decisions. Historical release evidence is never rewritten.

## Dependency and SBOM controls

`requirements-production.lock` pins every production dependency and all available distribution hashes. Production installation uses `pip --require-hashes`; the application wheel is installed separately with `--no-deps` and is content-addressed by the release manifest. Build tooling is hash-locked separately in `requirements-build.lock`. Security tools are isolated in `requirements-security.lock` and never enter the runtime image. The Python base is pinned by multi-architecture manifest digest.

Regenerate locks only during reviewed dependency maintenance:

```text
python -m piptools compile --generate-hashes --allow-unsafe --strip-extras --output-file requirements-production.lock requirements-production.in
python -m piptools compile --generate-hashes --allow-unsafe --strip-extras --output-file requirements-build.lock requirements-build.in
python -m piptools compile --generate-hashes --allow-unsafe --strip-extras --output-file requirements-security.lock requirements-security.in
```

The RC workflow emits CycloneDX JSON for Python and the container and joins them in a digest index. It emits pip-audit and Trivy reports, Bandit JSON, the deterministic repository-sensitive-data result, and an in-toto/SLSA v1 provenance statement. Generated evidence belongs under `artifacts/` and is not source.

## Vulnerability and exception policy

`config/vulnerability-policy.json` governs severity. CRITICAL blocks unconditionally. HIGH blocks unless a documented, time-bound acceptance identifies the finding, component, rationale, compensating control, owner and expiry. MEDIUM requires review and tracking; LOW is tracked. Scanner ignores and baselines are prohibited unless represented by the same governance fields. Expired or incomplete exceptions fail closed.

The custom sensitive-data scan detects private keys, credentials, raw JWTs, production DSNs, direct-identity literals and local paths. Only exact synthetic development values listed in the scanner are excluded. This does not authorize those values outside local/CI fixtures.

## Signing and provenance

`Ed25519SignatureVerifier` is provider-neutral and accepts only trusted public-key references. Private keys are never accepted by the repository, manifest or image. Unit tests use an ephemeral deterministic test key only to prove tamper rejection; it is not a production signature.

Institutional release signing must use GitHub keyless OIDC with an approved identity or a KMS/HSM-backed signing key through the existing secrets boundary. Until that identity and trust root exist, generated manifests are explicitly `INSTITUTIONAL_SIGNING_PENDING`. Software-boundary verification may use `--allow-pending`; production promotion must not.

Provenance binds the exact Git commit, builder identity, invocation/build ID, lock digest, SBOM digest and artifact digest. The fixed timestamp used for reproducibility checks is evidence-only; the canonical release identity records the authorized UTC build timestamp.

## Verification and reproducibility

Canonical verification is:

```text
python scripts/release_manifest.py verify --root . --manifest artifacts/release-manifest.json
```

It fails on missing reports, path escape, digest mismatch, source/version/migration mismatch, signature failure, coverage below 90%, incomplete COMPLETE_CASE or invalid replay. `--allow-pending` is restricted to pre-institutional software-boundary verification.

Equivalent source and locks must produce the same dependency graph, application contents, OCI labels and report linkages. The current image is not claimed byte-for-byte reproducible. Two clean builds from the same source and locks produced identical OCI labels and dependency versions, but different application-wheel hashes; wheel ZIP/install timestamps and BuildKit/OCI serialization remain nondeterministic. RC promotion therefore compares normalized labels and dependency state while recording the exact digest of the artifact actually scanned and verified. Byte reproducibility requires a separately validated `SOURCE_DATE_EPOCH` build toolchain.

## Institutional prerequisites

- approved keyless CI identity or KMS/HSM signing key, public trust root and rotation/revocation runbook;
- immutable external release-evidence storage and retention policy;
- pinned action commits and approved scanner/container registries;
- an approved base-image digest refresh process with an OS package update SLA;
- named security owner and vulnerability exception approver;
- independent signature/provenance verification before promotion.
