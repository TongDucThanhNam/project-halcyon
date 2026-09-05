# Vainglory research — stopped avenues

Avenues that were attempted and failed, with the reason. Read this before proposing
binary reverse engineering, asset extraction, or running the Vainglory client — each
of these cost real time and none of them needs repeating.

Nothing here is a Veilbound defect. This is a record about an external artifact.

> **2026-07-31 reproduction correction:** several historical measurements and
> the exact Android storefront branch were wrong. The corrected, independently
> rerunnable evidence is `vainglory-artifact-reproduction.md`. This leaf keeps
> the stopped avenues and explains why they remain stopped.

---

## Extracting the asset payload — stopped at the opaque INST transform

The envelope and chunk grammar needed for inventory were solved; the opaque
payload semantics were not:

**RSC0** — 32-byte header, now verified against all 18,136/18,136 files found by
the store inspector:

```
+00  "RSC0"
+04  uint32  size_word_1    // always filesize - 32 in this store
+08  uint32  size_word_2    // equal to size_word_1 in this store
+12  16 bytes zero
+32  payload
```

**CFF0** — a flat chunk chain starting at offset `0x40`. The trap: **the chunk size
field includes its own 8-byte header**, so advance by `size`, not `8 + size`. Getting
that wrong desyncs at the second chunk and looks like a corrupt file.

Walking the first revision of one manifest end to end, with Shannon entropy
calculated over payload bytes only:

| Tag | Size | Entropy | Meaning |
|---|---|---|---|
| `DEF0` | 16 | 2.75 | type definition, carries a type hash |
| `INST` | 19184 | 7.98844 | opaque instance data |
| `PTCH` | 6480 | 4.47654 | patch/offset table |
| `SYMB` | 32 | 3.77 | type name, e.g. `*HeroManifest*` |

The selected `INST` body did not decompress under the bounded probe. Tested at
five starting offsets each: zlib, raw-deflate, LZMA, bzip2, LZ4 block (three
output-size guesses), LZ4 frame and Zstandard. All 45 combinations failed.

The near-max-entropy `INST` with no recognized framing, sitting beside a much
lower-entropy `PTCH`, makes per-chunk encryption the strongest hypothesis. It
does not prove a cipher: custom compression or another transform remains
possible. Distinguishing them requires the loader, which runs into the next
dead end without changing a current Veilbound decision.

## Binary reverse engineering — no anchors

`lib/arm64-v8a/libGameKindred.so`, 45 MB:

- No `.symtab`. Fully stripped.
- 532 unique `_ZT[IVS]` dynamic names with the LLVM counting method used in the
  reproduction. After filtering and inspecting eight candidates, zero useful
  game class types remain. The older 390 count used an undocumented method.
- 19,877,380 bytes of `.text` with no class structure to anchor on.

The common RTTI heuristic (`grep -E '^N?[0-9]{1,3}[A-Z]'`) returns 64 hits, and every
one is a false positive: localisation keys such as `5V5_LOADING_SCREEN_TIP_1`, and hex
hashes. `Vainglory.exe` on Windows is 29.5 MB, unsigned, with no VersionInfo resource,
and would need the same treatment.

Conclusion: opening a disassembler here is a multi-week effort with no structural
foothold. It was correctly ruled out before starting.

## Running the Android client — blocked by absent data in this sideload

The APK is a stub downloader; `assets/Data/` contains only a 128-byte
`Startup.ini`. A fresh `apktool 3.0.3 d -r -f` decode confirms that the license
checker returns success unconditionally, so licensing blocks nothing. The
installer then branches on asset size:

```
SizeOfAssetsMB() == 0  ->  tryDownloadAssets()
SizeOfAssetsMB() != 0  ->  unpack from APK/OBB
```

With no OBB present the size is zero, so it takes `tryDownloadAssets()`.
Resource startup values are `storefront=GOOGLE`, `DIST=false` and
`INSTALL_ASSETS=true`. Therefore:

```
runtime STOREFRONT becomes GOOGLE
ENABLE_GOOGLE_DOWNLOAD = (GOOGLE && DIST) = false
downloader is not constructed
GOOGLE branch calls downloader.BeginDownload()
the exception is caught and the installer finishes
```

The prior note confused `TRUE_STOREFRONT=NONE` with runtime `STOREFRONT` and
predicted the non-Google dialog. That exact branch claim is withdrawn. The
high-level missing-payload blocker remains supported, but no fresh device was
connected for this reproduction.

The preserved phone logs contain a `Bundle.getString` NullPointerException after
the installer activity, but those runs were manually disturbed. Conversely,
the two files named `phone_clean*.log` show that the package was not installed,
so they cannot disprove the exception. Its causal role remains unresolved; the
smali missing-data chain is the reliable finding.

## What did work, if the client is ever needed again

The preserved prior run record says the Windows build reached the main menu with
no OBB or patching. This pass did not relaunch the unsigned executable. The
Internet Archive item `vainglory-4.13.7z` is 1,768,729,926 bytes with verified
MD5 `475f03dca1d3cca71588cd4f0c4323f0`; its extracted `Data/` store is
3,498,231,637 bytes and supplies the independently parsed structural findings.

Provenance caveat worth stating: the MD5 match proves the download is intact,
not that the 2024 uploader shipped a clean build. `Vainglory.exe` is unsigned
with no VersionInfo.

## Backend liveness — not established and irrelevant here

> **2026-09-03 update — superseded.** Liveness *was* subsequently
> established and measured, without ever probing their infrastructure: the
> community backend held live sessions from both the PC and Android clients,
> and the rooted emulator produced preserved counter-based traffic windows
> through a full solo-bot match. Full evidence and topology:
> `vainglory-netcode-backend.md`. The 2026-07-31 caution below remains true
> as a method lesson (reachable ≠ working), and Veilbound stays offline by
> design.

Certificate Transparency, DNS and one bootstrap response show that names and
routing existed on 2026-07-31. An older prose report lists client sockets, but
the raw socket snapshot was not preserved and was not reproduced here. Neither
class of evidence proves login, matchmaking or a playable service. Reachable
infrastructure is not a working application; that distinction caused an earlier
wrong conclusion.

Recorded only to close the question. Veilbound is offline by design — backend,
accounts and matchmaking remain deferred/non-goals in `CLAUDE.md` and `GOAL.md`.

## Breaking the INST codec — stop, and the route that replaced it

> **2026-09-03 update — route closed, replaced by a sanctioned one.** The 45-combination
> decompression sweep (store leaf §5) stays the final word on *cracking* the
> codec: it is per-chunk encryption, and breaking it would also cross this
> project's no-decryption boundary. What replaced it is sanctioned and
> cheaper: the running process decodes its own blueprints, so the decoded
> placement table was read from the heap instead
> (`vainglory-runtime-reconstruction.md`). Do not reopen the codec; go back
> to the runtime route.
