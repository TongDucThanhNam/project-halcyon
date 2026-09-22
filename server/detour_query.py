"""Explicitly configured native-route query; no download/build or default activation.

Qualified against the owned client steering routine, not official server rules.
The authoritative integration stays fixed-point; public Detour builds are pinned.
"""
import ctypes
import hashlib
import json
import math
from pathlib import Path
from .navigation import DEFAULT_CLASSIC_NAVMESH

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_SHA256 = '8b50c62177249554b226514b307e6c529934a62b3926822777bf6abb8906a155'
MESH_SHA256 = '9145ded654b5e0b6a542af63e00da09d40c3e24e75301bd7cda9267ff71a3fe2'


def point(value):
    if len(value) != 3 or not all(type(v) in (int,float) and math.isfinite(v) for v in value):
        raise ValueError('expected three finite world coordinates')
    return tuple(value)


class DetourRouteQuery:
    def __init__(self, library, mesh=DEFAULT_CLASSIC_NAVMESH):
        library, mesh = Path(library).resolve(), Path(mesh).resolve()
        manifest = json.loads(library.with_suffix('.build.json').read_text())
        source = ROOT/'Tools/Teardown/detour_route_oracle.cpp'
        if (manifest.get('schema') != 1 or manifest.get('archive_sha256') != ARCHIVE_SHA256
                or manifest.get('source_sha256') != hashlib.sha256(source.read_bytes()).hexdigest()
                or manifest.get('library_sha256') != hashlib.sha256(library.read_bytes()).hexdigest()):
            raise ValueError('oracle build/source/library qualification failed')
        if hashlib.sha256(mesh.read_bytes()).hexdigest() != MESH_SHA256:
            raise ValueError('oracle requires the pinned owned Classic baked navigation asset')
        self.manifest, self.library_path = manifest, str(library)
        self.lib = ctypes.CDLL(str(library))
        self.lib.hc_error.restype = ctypes.c_char_p
        self.lib.hc_open.argtypes = [ctypes.c_char_p]
        self.lib.hc_open.restype = ctypes.c_void_p
        self.lib.hc_close.argtypes = [ctypes.c_void_p]
        self.lib.hc_close.restype = None
        self.lib.hc_path.argtypes = [ctypes.c_void_p,ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),ctypes.POINTER(ctypes.c_float),ctypes.POINTER(ctypes.c_int)]
        self.lib.hc_path.restype = ctypes.c_int
        # Mesh path is local and ASCII in the qualified Windows build.
        self.handle = self.lib.hc_open(str(mesh).encode('ascii'))
        if not self.handle:
            raise ValueError(self.lib.hc_error().decode())

    def close(self):
        if getattr(self,'handle',None):
            self.lib.hc_close(self.handle)
            self.handle = None

    def __del__(self):
        self.close()

    def query(self,start,end):
        if not self.handle:
            raise ValueError('oracle is closed')
        start,end = point(start),point(end)
        output,meta = (ctypes.c_float*384)(),(ctypes.c_int*5)()
        count = self.lib.hc_path(self.handle,(ctypes.c_float*3)(*start),
                                (ctypes.c_float*3)(*end),output,meta)
        if not 1 <= count <= 128:
            raise ValueError(self.lib.hc_error().decode() or 'invalid route count')
        points = [list(point(output[3*i:3*i+3])) for i in range(count)]
        return {'points':points,'corridor_count':meta[0], 'ended':bool(meta[1]),
                'destination_polygon_reached':bool(meta[2]), 'capped':bool(meta[3]),
                'height_fallbacks':meta[4]}
