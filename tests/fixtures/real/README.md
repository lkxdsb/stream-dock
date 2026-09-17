# Real conversion fixtures

`archive.7z` is the 215-byte public libarchive test fixture (`test-archives/archive.7z`).
It contains `7zip-archive/hello` and `7zip-archive/world`, including Unix mode and timestamp metadata.
The golden-file runner uses it to exercise the real libarchive/bsdtar extraction path; it is not a mocked archive.

`archive.rar` is `rarfile` 4.2's public `test/files/rar5-subdirs.rar` fixture (ISC-licensed project).
It contains nested directories, spaces, Unicode decomposed filenames, and text files for real RAR extraction checks.

`rar5-vols.part1.rar` through `part3.rar` are `rarfile` 4.2's public multi-volume fixtures.
They exercise actual split-archive discovery and bounded extraction across all volumes.
