# Released upgrade and rollback drill

On 2026-10-25, the actual published Portal v2026.43.2 and both native Status
releases completed a disposable local API-only lifecycle drill. No browser window
was opened, no production URL was accepted, and no real provider or notification
destination was configured. This closes the isolated released-installer rollback
gap; it does not claim that production was downgraded.

## Inputs and assertions

The inputs were the checksum-verified official Portal binary and immutable Status
Beta.2/Beta.3 release directories. Each directory supplied `release.json`,
`status.zip` and the matching native service archive. The archive and ZIP hashes
matched the public release metadata; both ZIP manifests retained only
`extension.read` and `extension.manage`. The drill also compared every installed
frontend asset with its corresponding ZIP after each installation.

| Stage | Observed result |
| --- | --- |
| Beta.2 initial installation | Released Portal installed the old ZIP; a new fixture backend was deliberately paired; one administrator-only component, disabled monitor and sealed disposable credential were created through supported APIs |
| Beta.3 upgrade | Old process stopped; old executable created an offline backup; normal installer replaced the frontend; old token received 403; backend was disabled with no key until deliberate re-pairing; released Beta.3 started with the same independent store/key |
| Beta.2 rollback | New process stopped; new executable created another offline backup; normal installer installed the immutable old ZIP; old token again received 403; another deliberate pairing started the old service against the retained store |
| Continuity | Component, monitor, credential and grant rows matched their initial fingerprints; the original component remained readable after each pairing; database integrity was `ok`; three installation identities were distinct |
| Safety | Probes and notification publication remained paused, anonymous projection remained disabled and the fixture monitor remained disabled |
| Uninstall | Backend registration and installed asset returned 404; the independent Status service remained ready; Portal health, account, home and queue APIs remained available |
| Cleanup | All fixture processes stopped and temporary databases, passwords and keys were removed; the receipt contains no credentials |

The production rollout independently retained 2,297 historical observations and
all four real monitors/three sealed credentials. This smaller disposable lifecycle
fixture does not substitute for that production data-continuity evidence.

## Reproduce without controlling the desktop

First download both versions' artifacts and metadata from their official immutable
GitHub releases and verify their published checksums/source. The helper's hashes
detect disagreement with those reviewed inputs; they do not authenticate a metadata
file from an arbitrary source. Verify the Portal archive and extracted executable
against its official release before passing its binary path.

Use a private IPv4 address belonging to the local machine. The script verifies it
can bind that interface and allows only its exact address/ephemeral service port
in the disposable Portal connection. It does not enable a loopback SSRF exception.
Service scheduling stays paused throughout, so the disabled `.invalid` fixture
target is never probed.

From the repository root, replacing the example artifact paths and interface:

```sh
python3 scripts/status-released-lifecycle.py \
  --portal /absolute/path/to/verified/report-portal \
  --old-artifacts /absolute/path/to/status-beta2-artifacts \
  --new-artifacts /absolute/path/to/status-beta3-artifacts \
  --private-address 192.168.1.20 \
  --receipt /absolute/path/to/new-lifecycle-receipt.json
```

The receipt path must not exist. A successful command records version identities,
installed-byte checks, revocation, data continuity and safety boundaries. A failure
stops the fixtures and refuses to emit a success receipt. The script does not
start a browser or interact with an existing Portal session. Local regression
checks and the normal catalogue CI cover damaged checksums, unexpected scope
expansion, archive traversal and symlinks:

```sh
python3 -m unittest discover -s scripts/tests -p 'test_status_released_lifecycle.py' -v
```

Actual execution used the published Darwin arm64 archives. The helper also selects
Linux amd64/arm64 archives on matching hosts; execution on those platforms is not
claimed by this receipt. Both Linux image executables and storage reopen/restore
were independently verified during the production rollout.
