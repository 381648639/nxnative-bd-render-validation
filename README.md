# Brilliant Diamond legacy Metal renderer verification

This public repository contains renderer patches, production replay
regressions and a real game visual inspection harness for the open source
NxNative project. It checks the legacy Metal path used on iOS 16, including the
no-BC texture path. The upstream source is pinned to
`seedds/nxnative@1942eaa5e2a767809868994c27dfc5d692439fdc`.

Game inputs, keys, screenshots, logs and saves stay in a separate private
repository or the temporary runner filesystem. No game data enters public Git
history, public artifacts or public caches. The workflow is manual only. It
uses the standard `xcode-27` runner and does not select a paid larger runner or
increase any spending limit.

Two Actions secrets are required: `BD_PRIVATE_REPO_TOKEN`, used only to access
the owner's private input/evidence release, and `BD_PROD_KEYS`, copied from a
local key file. Neither is included in this repository.

Compile and GPU regression results alone do not establish gameplay correctness.
Inspect actual characters, indoor and outdoor scenes and save reloads. Mac
captures do not replace a final A15/iPhone check.
