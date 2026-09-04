"""Cluster Field - paste into a Rhino 8 "Python 3 Script" component.

APPROACH: Voronoi/Delaunay mesh + native Kangaroo relaxation (no parametric
funnels). The form comes out of the physics, not a formula.

TYPOLOGY (matches the reference plan + renders):
    - a COLUMN sits at the CENTRE of every Voronoi cell -> those points are
      pinned to the ground (anchors)
    - every other vertex carries an UP-load that grows with distance from its
      nearest column, so the sheet billows up between the columns
    - the cell boundaries, furthest from any column, rise highest -> the RIM
      arches you walk under
Kangaroo's edge springs + the bending goal keep it a smooth membrane.

INPUTS  - same slider names as before, Item Access:
    count     int    scatter points -> Voronoi cells                (~140)
    clump     float  0..1 pull toward attractors                    (~0.4)
    seed      int    master random seed
    clusters  int    number of separate pavilion patches            (1..4)
    grow      num    SOLIDITY: cells per patch. 0..1 or 2..10 = fraction of
                     all cells shared between patches; >10 = literal count
    feet      num    COLUMN FOOT RADIUS in field units (~7) - each column
                     pins a small disc, not a point, so the stem flares
    sx, sy    float  field extent                                   (~300)
    hmin      float  rim lift of the smallest cell                  (~40)
    hmax      float  rim lift of the largest / most central cell    (~110)
    subdiv    int    OPTIONAL mesh subdivision before Kangaroo (default 1)

OUTPUTS - unchanged names:
    mesh      connected, cluster-clipped, subdivided triangular mesh
    anchors   column foot discs -> Kangaroo "Anchor" : Point (pinned at z=0)
    verts     every mesh vertex, in order -> "Load" : Point
    loadvecs  per-vertex up-vector, (0,0,0) at the column feet
    cellcrv   Voronoi cells, plan reference
    info      text summary
"""
import math
import random

import Rhino.Geometry as rg
import ghpythonlib.components as ghc


def clumped_points(n, clump, seed, clusters, sx, sy):
    """`n` DISTINCT points; a `clump` fraction gauss-scattered around attractors.
    Distinctness matters - a duplicate makes Voronoi drop a cell."""
    rnd = random.Random(seed)
    attractors = [(rnd.uniform(0, sx), rnd.uniform(0, sy))
                  for _ in range(max(2, clusters))]
    spread = 0.18 * min(sx, sy)
    pts, seen, tries = [], set(), 0
    while len(pts) < n and tries < n * 50:
        tries += 1
        if rnd.random() < clump:
            ax, ay = rnd.choice(attractors)
            ang = rnd.uniform(0, 2 * math.pi)
            rad = abs(rnd.gauss(0, spread))
            x = min(max(ax + rad * math.cos(ang), 0.0), sx)
            y = min(max(ay + rad * math.sin(ang), 0.0), sy)
        else:
            x, y = rnd.uniform(0, sx), rnd.uniform(0, sy)
        key = (round(x, 2), round(y, 2))
        if key in seen:
            continue
        seen.add(key)
        pts.append(rg.Point3d(x, y, 0.0))
    return pts


def delaunay(pts):
    out = ghc.DelaunayMesh(pts, rg.Plane.WorldXY)
    return out if isinstance(out, rg.Mesh) else out[0]


def adjacency(dmesh):
    adj = [set() for _ in range(dmesh.Vertices.Count)]
    for k in range(dmesh.Faces.Count):
        f = dmesh.Faces[k]
        tri = (f.A, f.B, f.C)
        for i in tri:
            for j in tri:
                if i != j:
                    adj[i].add(j)
    return adj


def grow_clusters(adj, clusters, per_patch, seed):
    """Round-robin flood fill from `clusters` random seed vertices, each patch
    capped at `per_patch` vertices."""
    n = len(adj)
    rnd = random.Random(seed + 1)
    starts = rnd.sample(range(n), min(clusters, n))
    cid = [-1] * n
    front = []
    for k, s in enumerate(starts):
        cid[s] = k
        front.append([s])
    size = [1] * len(starts)
    busy = True
    while busy:
        busy = False
        for k in range(len(starts)):
            if size[k] >= per_patch or not front[k]:
                continue
            nxt = []
            for v in front[k]:
                for w in adj[v]:
                    if cid[w] == -1 and size[k] < per_patch:
                        cid[w] = k
                        size[k] += 1
                        nxt.append(w)
            front[k] = nxt
            busy = busy or bool(nxt)
    return cid


def _largest_components(faces, nverts, cid):
    """Union-find over the kept faces; per patch keep only its biggest connected
    blob so a patch is always ONE piece, never scattered islands."""
    parent = list(range(nverts))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, c in faces:
        for u, v in ((a, b), (b, c)):
            ra, rb = find(u), find(v)
            if ra != rb:
                parent[ra] = rb
    size = {}
    for a, b, c in faces:
        r = find(a)
        size[r] = size.get(r, 0) + 1
    best = {}
    for a, b, c in faces:
        p, r = cid[a], find(a)
        if p not in best or size[r] > size[best[p]]:
            best[p] = r
    roots = set(best.values())
    return [t for t in faces if find(t[0]) in roots]


def clipped_mesh(dmesh, cid, n_seed):
    """Keep faces whose 3 vertices share one patch, then reduce each patch to
    its single largest connected component. Carry a flag marking which kept
    vertices are original seed points (the cell centres)."""
    keep = []
    for k in range(dmesh.Faces.Count):
        f = dmesh.Faces[k]
        if cid[f.A] >= 0 and cid[f.A] == cid[f.B] == cid[f.C]:
            keep.append((f.A, f.B, f.C))
    keep = _largest_components(keep, dmesh.Vertices.Count, cid)
    used = sorted({i for tri in keep for i in tri})
    remap = {old: new for new, old in enumerate(used)}
    m = rg.Mesh()
    for old in used:
        m.Vertices.Add(dmesh.Vertices[old])
    for a, b, c in keep:
        m.Faces.AddFace(remap[a], remap[b], remap[c])
    m.Faces.CullDegenerateFaces()
    m.Compact()
    m.RebuildNormals()
    return (m, [cid[o] for o in used], [o < n_seed for o in used])


def split_once(m, vcid, seedflag):
    """One level of midpoint subdivision: each tri -> 4. Original vertices keep
    their index and their seed flag; new edge-midpoint vertices are never seeds."""
    nm = rg.Mesh()
    for i in range(m.Vertices.Count):
        nm.Vertices.Add(m.Vertices[i])
    nvcid, nseed, mids = list(vcid), list(seedflag), {}

    def mid(a, b):
        key = (a, b) if a < b else (b, a)
        if key not in mids:
            pa, pb = rg.Point3d(m.Vertices[a]), rg.Point3d(m.Vertices[b])
            mids[key] = nm.Vertices.Add((pa.X + pb.X) * 0.5,
                                        (pa.Y + pb.Y) * 0.5,
                                        (pa.Z + pb.Z) * 0.5)
            ca, cb = vcid[a], vcid[b]
            nvcid.append(ca if ca == cb else max(ca, cb))
            nseed.append(False)
        return mids[key]

    for k in range(m.Faces.Count):
        f = m.Faces[k]
        a, b, c = f.A, f.B, f.C
        ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
        nm.Faces.AddFace(a, ab, ca)
        nm.Faces.AddFace(b, bc, ab)
        nm.Faces.AddFace(c, ca, bc)
        nm.Faces.AddFace(ab, bc, ca)
    nm.RebuildNormals()
    return nm, nvcid, nseed


def foot_discs(m, seed_idx, radius):
    """Grow each column-centre vertex into a small ground disc so the stem
    flares from a footprint, not a spike."""
    seeds = [rg.Point3d(m.Vertices[i]) for i in seed_idx]
    disc = set(seed_idx)
    for i in range(m.Vertices.Count):
        p = rg.Point3d(m.Vertices[i])
        for s in seeds:
            if p.DistanceTo(s) <= radius:
                disc.add(i)
                break
    if len(disc) > 0.30 * m.Vertices.Count:      # too much pinned -> points only
        return set(seed_idx)
    return disc


def nearest_dist(p, seeds):
    return min(p.DistanceTo(s) for s in seeds) if seeds else 0.0


def _param(name, default):
    value = globals().get(name, None)
    return default if value is None else value


count = int(_param("count", 140))
clump = float(_param("clump", 0.4))
seed = int(_param("seed", 3))
clusters = max(1, int(_param("clusters", 2)))
base_r = float(_param("feet", 7.0)) or 7.0
sx = float(_param("sx", 300.0))
sy = float(_param("sy", 300.0))
hmin = float(_param("hmin", 40.0))
hmax = float(_param("hmax", 110.0))
subdiv = int(_param("subdiv", 1))

_graw = float(_param("grow", 0.5))
if _graw > 10.0:
    per_patch = int(_graw)
else:
    _frac = _graw if _graw <= 1.0 else _graw / 10.0
    per_patch = max(3, int(round(_frac * count / clusters)))

_pts = clumped_points(count, clump, seed, clusters, sx, sy)
_del = delaunay(_pts)
_cid = grow_clusters(adjacency(_del), clusters, per_patch, seed)
mesh, _vcid, _seed = clipped_mesh(_del, _cid, len(_pts))
for _ in range(max(0, subdiv)):
    mesh, _vcid, _seed = split_once(mesh, _vcid, _seed)

_seed_idx = [i for i in range(mesh.Vertices.Count) if _seed[i]]
_foot = foot_discs(mesh, _seed_idx, base_r)
_footpts = [rg.Point3d(mesh.Vertices[i]) for i in sorted(_foot)]

# typical cell radius -> normalises the lift falloff
_typ = 0.62 * math.sqrt(sx * sy / max(1, count))

verts, loadvecs, anchors = [], [], []
for i in range(mesh.Vertices.Count):
    p = rg.Point3d(mesh.Vertices[i])
    verts.append(p)
    if i in _foot:
        loadvecs.append(rg.Vector3d(0, 0, 0))
        anchors.append(p)
    else:
        t = min(1.0, nearest_dist(p, _footpts) / _typ)     # 0 at stem, 1 at rim
        loadvecs.append(rg.Vector3d(0, 0, hmin + (hmax - hmin) * t))

try:
    _rect = rg.Rectangle3d(rg.Plane.WorldXY,
                           rg.Interval(-0.05 * sx, 1.05 * sx),
                           rg.Interval(-0.05 * sy, 1.05 * sy))
    cellcrv = ghc.Voronoi(_pts, None, _rect, rg.Plane.WorldXY)
except Exception:
    cellcrv = None

info = ("pts=%d  cells_built=%d  patches=%d  subdiv=%d  base_r=%.1f  "
        "verts=%d  faces=%d  columns=%d  lift=%.0f..%.0f") % (
    len(_pts), sum(1 for s in _seed if s), clusters, subdiv, base_r,
    mesh.Vertices.Count, mesh.Faces.Count, len(anchors), hmin, hmax)
