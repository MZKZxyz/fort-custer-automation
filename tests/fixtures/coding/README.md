# Coding canary offline evidence

`real_sol_low_comment.json` is the unmodified user-supplied Experiment 8 sanitized
capture, SHA-256 `af0f2f5c66f10b5763de321f35486d11eb59f9c530d435c03e43ef647f9ed211`.
Its original `capture_sha256` field is retained as provenance, not recomputable
integrity evidence: the original unsanitized capture was not supplied.

`source-objects.json.gz` is a deterministic gzip JSON map of Git object SHA to
`[type, base64(raw_object_body)]`, SHA-256
`f031db01ca56b8bb7b9601284818eb3236c28b9e4279d78682daae21503fc373`.
It holds 33 blobs, 15 trees, and the exact original signed commit at
https://github.com/MZKZxyz/fort-custer-server/commit/c4f480abb309a7a4d141b20ab462552a868ef0e3
retrieved using the connected read-only GitHub Git-data endpoints. Every object
body was checked against its Git SHA. The original commit was reconstructed from
its GitHub verification payload/signature and its SHA was verified; tests do not
claim independent PGP signature verification. The parent commit is deliberately
outside the fixture and marked shallow on import.

The full pinned source manifest is
`c6a8168073de8f0efc839f1a10892bb9619c6a92f1a02be5a04e68f5921a1848`.
No application source was simplified, patched or regenerated. Both original and
candidate analyzer tests run without dependency installation. Model output and
usage in the mock Responses envelope come from the capture; the envelope itself
is synthetic and not represented as the missing original provider response.
