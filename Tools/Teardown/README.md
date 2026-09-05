# Teardown tools

Original, read-only inspectors used by
`../../Docs/Teardown/vainglory-artifact-reproduction.md`. They do not extract or
write proprietary payloads.

## Requirements

- Python 3.11 or newer.
- `lz4` and `zstandard` only for the bounded codec probe:

```powershell
python -m pip install lz4 zstandard
```

## Content-store inventory

```powershell
python Tools\Teardown\inspect_vainglory_store.py `
  'D:\Downloads\vg\pc\Vainglory 4.13\Vainglory\Data'
```

Add `--include-ui-paths` only when individual structural path evidence is
needed. Default output contains aggregate counts and the two pretarget records.

## Embedded-path dump

```powershell
python Tools\Teardown\extract_vainglory_paths.py `
  'D:\Downloads\vg\pc\Vainglory 4.13\Vainglory\Data' > paths.tsv
```

Prints every self-declared path (RSC0 header records + surface records) as
`kind\tpath`, one per line, in sorted order. Read-only; used by
`Docs/Teardown/vainglory-3v3-map-structure.md`.

## BC1 texture locator/renderer

```powershell
python Tools\Teardown\render_vainglory_bc1.py `
  'D:\Downloads\vg\pc\Vainglory 4.13\Vainglory\Data' C:\temp\vg_tex
```

Finds standalone textures whose 28-byte header (`size, mips, 1, format, width,
height, flags`) validates arithmetically against BC1 mip-chain lengths, lists
them and renders top-mip thumbnails of the largest ones to the output
directory. Decoded images stay out of the repository.

## NavMesh parser/renderer

```powershell
python Tools\Teardown\render_vainglory_navmesh.py `
  'D:\Downloads\vg\pc\Vainglory 4.13\Vainglory\Data' C:\temp\vg_nav `
  4B/4BD271EAAC785AEB0C2BCED99515D401
```

Parses the fully decoded nav record format (min/max world bounds, 24-byte
vertex records, adaptive u8/u16 triangle indices — see
`Docs/Teardown/vainglory-3v3-map-structure.md` §4, which also names the
store-relative hashes of the 3v3 and tutorial records) and renders the
walkable triangle mesh top-down. The parser accounts for 100% of both sample
payloads; rendered images stay out of the repository.

## Bounded codec probe

```powershell
python Tools\Teardown\probe_vainglory_codecs.py `
  'D:\Downloads\vg\pc\Vainglory 4.13\Vainglory\Data\C4\C41CC38B5CEADF09048A3750D045E47B'
```

The probe caps decompressed output, records failures and never writes decoded
content. A zero-success result rejects only the listed codec/framing/offset
combinations; it is not proof of encryption.
