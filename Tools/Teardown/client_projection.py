"""Scalar world projection from qualified native camera matrices; no pixels."""
import math


def world_to_screen(camera, position_xyz):
    """Return floating viewport coordinates; reject points outside the frustum.

    Matrices are column-major, with native upper-left viewport origin. Native
    8b891c applies view then projection and homogeneous division. The caller
    must still establish UI/target/input guards; projection is not a click.
    """
    view, projection, dimensions = (camera.get(k) for k in ('view', 'projection', 'dimensions'))
    fields = ((view, 16), (projection, 16), (dimensions, 2), (position_xyz, 3))
    if any(not isinstance(v, (list, tuple)) or len(v) != n for v, n in fields):
        raise ValueError('invalid world projection shape')
    if not all(type(x) in (int, float) and math.isfinite(x) for v, _ in fields for x in v):
        raise ValueError('nonfinite world projection data')
    if any(not 0 < x <= 8192 or int(x) != x for x in dimensions):
        raise ValueError('invalid viewport dimensions')
    def multiply(matrix, vector):
        return [sum(matrix[4*j+i] * vector[j] for j in range(4)) for i in range(4)]
    clip = multiply(projection, multiply(view, list(position_xyz) + [1]))
    if not all(math.isfinite(x) for x in clip) or clip[3] <= 1e-6:
        raise ValueError('world point behind/at camera')
    normalized = [x / clip[3] for x in clip[:3]]
    if any(abs(x) > 1 for x in normalized):
        raise ValueError('world point outside camera frustum')
    return [(normalized[0] + 1) * dimensions[0] / 2,
            (1 - normalized[1]) * dimensions[1] / 2]
