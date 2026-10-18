# Engine folder

`scripts/setup_edax.py` fills `engine/<platform>/` with the Edax executable,
`data/eval.dat` (evaluation weights) and `data/book.dat` (opening book).
Everything here except this file, the patch and the Apple Silicon build is
ignored by git.

## darwin-arm64/mEdax (shipped)

A ready-made build for Apple Silicon Macs, provided so Mac users don't need
Xcode. It is Edax by Richard Delorme and Toshihiko Okuhara, GPL-3.0:

- source: https://github.com/abulmo/edax-reversi, commit
  `786421f355219ade872ce7285c1cab1eaf67836a` (version 4.7, one commit after tag v4.7)
- plus `edax-macos-fixes.patch` in this folder (a missing `#include <time.h>` and a
  use-after-return bug in the pthread `thrd_create` wrapper, which made Edax crash on macOS)
- built with `make build ARCH=armv8.5-a OS=osx CC=clang` (Apple clang 21)

To rebuild it yourself:

```sh
git clone https://github.com/abulmo/edax-reversi && cd edax-reversi
git checkout 786421f
git apply path/to/edax-macos-fixes.patch
cd src && make build ARCH=armv8.5-a OS=osx CC=clang && ls ../bin
```

As required by the GPL, the complete corresponding source of this binary is the
upstream repository at that commit plus the patch above.
