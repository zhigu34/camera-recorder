# camera-recorder Development Workflow

This repository uses a fast, risk-based development workflow.

## Deployment

Keep deployment unchanged unless explicitly requested:

```bash
git pull && ./deploy.sh
```

Do not replace this flow or add extra required deployment commands by default.

## Default development flow

For normal changes:

1. Implement the approved bounded change on a branch.
2. Add only the regression tests that protect important behavior; avoid tests that merely lock implementation details or styling internals.
3. Open one PR.
4. Run PR CI once.
5. Review the diff.
6. If CI is green and review finds no blocking issue, merge directly.
7. Do not wait for a second `main` CI run by default.

A second CI run is only needed when the merge introduces additional code, resolves conflicts, picks up concurrent `main` changes, or there is another concrete reason to distrust the PR result.

If CI fails naturally, diagnose and fix the failure, then rerun the PR CI. Do not create intentional failing CI runs for routine UI work.

## Risk-based testing

### Pure UI and low-risk frontend changes

Examples: CSS, spacing, typography, icons, copy, layout, visual polish, straightforward event bindings.

- Do not deliberately create a RED CI run.
- Add or update only useful regression tests.
- Prefer semantic tests over brittle CSS or exact implementation assertions.
- One PR CI is enough before merge.

### Medium-risk frontend behavior

Examples: playback controls, timeline interactions, state synchronization, navigation behavior.

- Test the user-visible behavior that could regress.
- Do not test every helper or internal branch unless it protects a real failure mode.
- One PR CI is enough before merge.

### High-risk backend and media logic

Examples: recording capture, FFmpeg/remux, recording deletion or cleanup, database migrations, WebSocket/media state machines, export processing, destructive operations, core backend business logic.

- Use stricter TDD and targeted regression coverage.
- Verify safety properties such as source-file immutability, path containment, migration correctness, and failure recovery where relevant.
- Still prefer a single PR CI before merge unless there is a concrete reason for additional verification.

## Media behavior constraints

- Entering Live, Playback, or recording-related pages must not automatically start media solely because of navigation or a deep link.
- Live media starts only after an explicit user action.
- Playback starts only after an explicit play, timeline, event, or other deliberate playback action.
- Preserve this manual-media-start policy in UI refactors.

## Visual direction

The product should continue moving toward a UniFi Protect-like experience: restrained chrome, compact hierarchy, low visual noise, strong media focus, consistent spacing, and purpose-built media controls rather than generic admin-form styling.
