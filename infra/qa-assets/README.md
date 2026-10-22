# Operator-provisioned QA assets (not included)

Prepare in a separate registry-only disposable environment, without secrets.
Do not copy a developer HOME, npmrc, credentials, database data or browser profiles.

Required layout: `manifest.json` mapping each relative asset path to its SHA-256,
`npm-cache/` with the exact reviewed lockfile dependency cache,
`mongodb/mongod` (checksum-verified MongoDB 8.0.16), and `browsers/` with the exact
Playwright 1.62.1 browser bundle for the client. Include every regular asset file
in the manifest and reject symlinks. Record the exact source/lock SHA and image ID
outside the image. No actual assets or package downloads are supplied by this PR.
The Node image build fails if manifest/assets are missing or mismatched.

Server native dependencies may require a separately reviewed prebuilt native
artifact staging step; do not enable lifecycle scripts on a trusted host.
