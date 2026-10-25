# Mandatory window lifecycle evidence for new private deliveries

`deliver_binary.py --policy window-lifecycle-v1` requires three original artifact ZIPs in addition to the existing delivery contract. `delivery-provenance.json` now uses schema 2 and records `deliveryPolicy: window-lifecycle-v1`. The command refuses missing or different policies before querying GitHub. There is no fallback based on missing artifacts or an application version string.

Historical deliveries, manifests and receipts remain historical evidence under their original committed controllers. Their absence of lifecycle reports is not converted into a lifecycle pass. The ten-name legacy native inventory, the 50-file cross inventory and the 42-file preview inventory remain unchanged.

| Artifact | Exact successful inventory | Scope |
| --- | --- | --- |
| `PDF-window-lifecycle-macos-26` | `early.json`, `early-receipt.json`, `early.log`, `installed.json`, `installed-receipt.json`, `installed.log` | Minimal diagnostic and complete source-installed application on macOS 26 |
| `PDF-window-lifecycle-xcode-27` | Same six filenames | Minimal diagnostic and complete source-installed application on macOS 27 |
| `PDF-cross-lifecycle` | `cross.json`, `cross-receipt.json`, `cross.log` | Unchanged delivered macOS 26 package installed on macOS 27 |

Failed runs may retain partial diagnostic artifacts. They are not eligible for delivery: the exact run/attempt/jobs and every required lifecycle step must succeed, and every listed file must exist. Selection verifies same repository, source/controller SHA, upload time inside the corresponding job, nonexpired identity, size and GitHub SHA-256 digest. ZIP extraction rejects unexpected paths, duplicates, special files, unsafe compression and excessive expansion before validation.

Per-file limits are 2 MiB for the native JSON, 64 KiB for the receipt and 64 MiB for the original log. ZIP downloads retain the existing 256 MiB artifact cap; extraction is additionally limited to the sum of the exact inventory's individual caps. JSON rejects duplicate keys and nonfinite numbers. All twelve checks, the recorded events, report hash, scopes, original false approval flags, deadlines and report time inside the authenticated job are mandatory.

The controller's `scripts/check_window_lifecycle.py` must match the bytes from the authenticated original source archive. Downloaded Python code is never loaded. Both native source scopes must retain the original production Info.plist identity, but their executable hashes are not equated to the later relocated/signed distribution. Only `cross-installed-binary` must match both `PDF.app/Contents/MacOS/PDF` and `PDF.app/Contents/Info.plist` in the independently authenticated delivered tar manifest.

The report validator's `sourceCommitAuthenticatedByThisValidator: false` remains false. Authentication is supplied separately by the exact repository/run/job/artifact and verified source archive. The diagnostics do not approve the whole application, demonstrate the historical timeout's cause, validate preview screenshots, or prove human VoiceOver or physical M4 behavior.

## Delivery assets and readback

The three unchanged ZIPs become separate release assets with the `.zip` suffix. Internal JSON/log files are validated in private scratch directories and are not added to the flat cross inventory or published as extra standalone assets. Their per-file hashes and scope results are retained under `windowLifecycleEvidence` in provenance. The original ZIP hashes also appear in `files` and `DELIVERY-SHA256SUMS`.

For the existing single-tar contract the resulting asset count is **76**: 73 previous assets plus three original lifecycle ZIPs. Split packages still derive the count from the verified part plan; they must not be forced to 76. The workflow rereads all final assets before returning `windowLifecycleChecksPassed: true`, the policy identifier and its actual asset count. Existing published releases or changed assets are refused; the workflow only creates/completes a private draft.

## Collector update after the actual source/cross runs complete

1. Bind the new source SHA/run, cross controller/run, approved tar hash and eventual delivery controller/run explicitly. Do not reuse the failed cross run for 81769db or the previous 73-asset collector as approval.
2. Authenticate each lifecycle artifact from its completed exact run/attempt/job, preserve the original API JSON and ZIP, verify size/upstream digest and extract the exact bounded inventory above. Keep partial failed-run artifacts labeled as failure evidence.
3. Reuse `delivery_lifecycle.verify` from the reviewed delivery controller, with the authenticated source archive fingerprints. Pass the authenticated tar manifest only for cross. Preserve each original receipt's unsupported-claim flags.
4. For the final draft require schema 2, `deliveryPolicy`, `windowLifecycleChecksPassed`, `requiredWindowLifecycleDiagnostics`, all three lifecycle artifact identities, and their per-file records. Derive asset names/count from the actual single-tar or part plan, retaining the old inventories unchanged.
5. The collector may download the five small release controls and compare the three lifecycle release ZIP digests/sizes to already authenticated local originals; no repeat tar download is needed. Describe full workflow readback and these narrower collector reads separately. Preserve complete delivery job logs and check that the draft/assets remain unchanged at the end.

Offline JSON/ZIP fixtures exercise this policy and refusal before any release write. They are parser/provenance tests, not substitutes for actual AppKit, source-matrix or cross-binary execution.
