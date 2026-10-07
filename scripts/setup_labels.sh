#!/usr/bin/env bash
# Create the labels the foreman loop relies on. Safe to re-run (existing labels are left alone).
set -u
repo="${1:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
mk() { gh label create "$1" --repo "$repo" --color "$2" --description "$3" 2>/dev/null && echo "created $1" || echo "exists  $1"; }
mk for-foreman        D93F0B "A note, question or decision request for the foreman"
mk contract-change    5319E7 "A proposed change to the shared contracts"
mk deferred           BFD4F2 "Owner-deferred: tracked, revisit at the named trigger"
mk needs-verification FBCA04 "Not verified by the author: how to check it is in the issue; blocks the milestone tag"
mk bug                D73A4A "A defect, with a reproduction"
mk blog-worthy        0E8A16 "A lesson, mishap or decision worth writing up"
# One label per workstream, e.g.:  mk ws:1-loader 1D76DB "Workstream 1"
