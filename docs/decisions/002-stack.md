# 002: Phase 0 runs on Apple devices, Python, a JavaScript sync function and GitHub Actions, with a macOS box

Status: accepted. Issues: #6, #9.

Phase 0 needed a stack before dispatch. The tablets, the box and the cloud are different runtimes, and Couchbase
Lite's Multipeer Replicator only meshes iOS with Android from 4.1 on both sides.

1. **The choice.**
   - Tablets and phone: two iPads and an iPhone, one Swift/SwiftUI app, iOS 17+, Couchbase Lite Swift 4.x. One
     platform avoids the cross-platform mesh caveat; Vector Search (Phase 1) is officially supported on Swift.
     Rejected: Android or a mix (more risk for no gain on the owner's devices).
   - Box agent, Capella tooling, the reference ledger and the HQ screen: Python 3.12, one `uv` project. The sync
     function is JavaScript (App Services requires it), tested with `node --test`.
   - The box: a **macOS laptop** is the supported Phase 0 box. The owner's Raspberry Pi runs Debian Trixie, which is
     not a supported Edge Server 1.1 ARM64 platform (only Ubuntu 22.04+ is), so the Pi is optional and best-effort.
   - CI: GitHub Actions, a Linux job and a macOS job. The repository was made public on 2026-10-07, so the macOS job
     runs on every PR at no cost.
   - Apple developer account: free for now.
2. **What it costs.** A free account's device installs expire after seven days, so devices are re-installed before
   each rehearsal and on demo day. The "store in a backpack" picture is a laptop, not a Pi, until the Pi is verified.
3. **When to revisit.** Before Phase 1 (a paid Apple account; the small model runtime decides laptop versus Pi), or
   if Edge Server adds Debian ARM64 support.

Contract change: none.
