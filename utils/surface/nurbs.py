
import numpy as np
from collections import defaultdict

from sverchok.utils.geom import Spline
from sverchok.utils.nurbs_common import (
        SvNurbsMaths, SvNurbsBasisFunctions,
        nurbs_divide, from_homogenous
    )
from sverchok.utils.curve import knotvector as sv_knotvector
from sverchok.utils.curve.algorithms import interpolate_nurbs_curve
from sverchok.utils.surface import SvSurface, SurfaceCurvatureCalculator, SurfaceDerivativesData
from sverchok.dependencies import geomdl

if geomdl is not None:
    from geomdl import operations
    from geomdl import NURBS

##################
#                #
#  Surfaces      #
#                #
##################

class SvNurbsSurface(SvSurface):
    """
    Base abstract class for all supported implementations of NURBS surfaces.
    """
    NATIVE = SvNurbsMaths.NATIVE
    GEOMDL = SvNurbsMaths.GEOMDL

    U = 'U'
    V = 'V'

    @classmethod
    def build(cls, implementation, degree_u, degree_v, knotvector_u, knotvector_v, control_points, weights=None, normalize_knots=False):
        return SvNurbsMaths.build_surface(implementation,
                    degree_u, degree_v,
                    knotvector_u, knotvector_v,
                    control_points, weights,
                    normalize_knots)

    @classmethod
    def get(cls, surface, implementation = NATIVE):
        if isinstance(surface, SvNurbsSurface):
            return surface
        if hasattr(surface, 'to_nurbs'):
            return surface.to_nurbs(implementation=implementation)
        return None

    @classmethod
    def get_nurbs_implementation(cls):
        raise Exception("NURBS implementation is not defined")

    def insert_knot(self, direction, parameter, count=1):
        raise Exception("Not implemented!")

    def swap_uv(self):
        degree_u = self.get_degree_u()
        degree_v = self.get_degree_v()
        knotvector_u = self.get_knotvector_u()
        knotvector_v = self.get_knotvector_v()

        control_points = self.get_control_points()
        weights = self.get_weights()

        control_points = np.transpose(control_points, axes=(1,0,2))
        weights = weights.T

        return SvNurbsSurface.build(self.get_nurbs_implementation(),
                degree_v, degree_u,
                knotvector_v, knotvector_u,
                control_points, weights)

    def elevate_degree(self, direction, delta=None, target=None):
        if delta is None and target is None:
            delta = 1
        if delta is not None and target is not None:
            raise Exception("Of delta and target, only one parameter can be specified")
        if direction == SvNurbsSurface.U:
            degree = self.get_degree_u()
        else:
            degree = self.get_degree_v()
        if delta is None:
            delta = target - degree
            if delta < 0:
                raise Exception(f"Surface already has degree {degree}, which is greater than target {target}")
        if delta == 0:
            return self

        implementation = self.get_nurbs_implementation()

        if direction == SvNurbsSurface.U:
            new_points = []
            new_weights = []
            new_u_degree = None
            for i in range(self.control_points.shape[1]):
                fixed_v_points = self.control_points[:,i]
                fixed_v_weights = self.weights[:,i]
                fixed_v_curve = SvNurbsMaths.build_curve(implementation,
                                    self.degree_u, self.knotvector_u,
                                    fixed_v_points, fixed_v_weights)
                fixed_v_curve = fixed_v_curve.elevate_degree(delta)
                fixed_v_knotvector = fixed_v_curve.get_knotvector()
                new_u_degree = fixed_v_curve.get_degree()
                fixed_v_points = fixed_v_curve.get_control_points()
                fixed_v_weights = fixed_v_curve.get_weights()
                new_points.append(fixed_v_points)
                new_weights.append(fixed_v_weights)

            new_points = np.transpose(np.array(new_points), axes=(1,0,2))
            new_weights = np.array(new_weights).T

            return SvNurbsSurface.build(self.get_nurbs_implementation(),
                    new_u_degree, self.degree_v,
                    fixed_v_knotvector, self.knotvector_v,
                    new_points, new_weights)

        elif direction == SvNurbsSurface.V:
            new_points = []
            new_weights = []
            new_v_degree = None
            for i in range(self.control_points.shape[0]):
                fixed_u_points = self.control_points[i,:]
                fixed_u_weights = self.weights[i,:]
                fixed_u_curve = SvNurbsMaths.build_curve(implementation,
                                    self.degree_v, self.knotvector_v,
                                    fixed_u_points, fixed_u_weights)
                fixed_u_curve = fixed_u_curve.elevate_degree(delta)
                fixed_u_knotvector = fixed_u_curve.get_knotvector()
                new_v_degree = fixed_u_curve.get_degree()
                fixed_u_points = fixed_u_curve.get_control_points()
                fixed_u_weights = fixed_u_curve.get_weights()
                new_points.append(fixed_u_points)
                new_weights.append(fixed_u_weights)

            new_points = np.array(new_points)
            new_weights = np.array(new_weights)

            return SvNurbsSurface.build(implementation,
                    self.degree_u, new_v_degree,
                    self.knotvector_u, fixed_u_knotvector,
                    new_points, new_weights)

    def get_degree_u(self):
        raise Exception("Not implemented!")

    def get_degree_v(self):
        raise Exception("Not implemented!")

    def get_knotvector_u(self):
        """
        returns: np.array of shape (X,)
        """
        raise Exception("Not implemented!")

    def get_knotvector_v(self):
        """
        returns: np.array of shape (X,)
        """
        raise Exception("Not implemented!")

    def get_control_points(self):
        """
        returns: np.array of shape (n_u, n_v, 3)
        """
        raise Exception("Not implemented!")

    def get_weights(self):
        """
        returns: np.array of shape (n_u, n_v)
        """
        raise Exception("Not implemented!")

class SvGeomdlSurface(SvNurbsSurface):
    def __init__(self, surface):
        self.surface = surface
        self.u_bounds = (0, 1)
        self.v_bounds = (0, 1)
        self.__description__ = f"Geomdl NURBS (degree={surface.degree_u}x{surface.degree_v}, pts={len(surface.ctrlpts2d)}x{len(surface.ctrlpts2d[0])})"

    @classmethod
    def get_nurbs_implementation(cls):
        return SvNurbsSurface.GEOMDL

    def insert_knot(self, direction, parameter, count=1):
        if direction == SvNurbsSurface.U:
            uv = [parameter, None]
            counts = [count, 0]
        elif direction == SvNurbsSurface.V:
            uv = [None, parameter]
            counts = [0, count]
        surface = operations.insert_knot(self.surface, uv, counts)
        return SvGeomdlSurface(surface)

    def get_degree_u(self):
        return self.surface.degree_u

    def get_degree_v(self):
        return self.surface.degree_v

    def get_knotvector_u(self):
        return self.surface.knotvector_u

    def get_knotvector_v(self):
        return self.surface.knotvector_v

    def get_control_points(self):
        pts = []
        for row in self.surface.ctrlpts2d:
            new_row = []
            for point in row:
                if len(point) == 4:
                    x,y,z,w = point
                    new_point = (x/w, y/w, z/w)
                else:
                    new_point = point
                new_row.append(new_point)
            pts.append(new_row)
        return np.array(pts)

    def get_weights(self):
        if isinstance(self.surface, NURBS.Surface):
            weights = [[pt[3] for pt in row] for row in self.surface.ctrlpts2d]
        else:
            weights = [[1.0 for pt in row] for row in self.surface.ctrlpts2d]
        return np.array(weights)

    @classmethod
    def build_geomdl(cls, degree_u, degree_v, knotvector_u, knotvector_v, control_points, weights, normalize_knots=False):

        def convert_row(verts_row, weights_row):
            return [(x*w, y*w, z*w, w) for (x,y,z), w in zip(verts_row, weights_row)]

        if weights is None:
            surf = BSpline.Surface(normalize_kv = normalize_knots)
        else:
            surf = NURBS.Surface(normalize_kv = normalize_knots)
        surf.degree_u = degree_u
        surf.degree_v = degree_v
        ctrlpts = list(map(convert_row, control_points, weights))
        surf.ctrlpts2d = ctrlpts
        surf.knotvector_u = knotvector_u
        surf.knotvector_v = knotvector_v

        result = SvGeomdlSurface(surf)
        result.u_bounds = surf.knotvector_u[0], surf.knotvector_u[-1]
        result.v_bounds = surf.knotvector_v[0], surf.knotvector_v[-1]
        return result

    @classmethod
    def from_any_nurbs(cls, surface):
        if not isinstance(surface, SvNurbsSurface):
            raise TypeError("Invalid surface")
        if isinstance(surface, SvGeomdlSurface):
            return surface
        return SvGeomdlSurface.build_geomdl(surface.get_degree_u(), surface.get_degree_v(),
                    surface.get_knotvector_u(), surface.get_knotvector_v(),
                    surface.get_control_points(),
                    surface.get_weights())

    @classmethod
    def build(cls, implementation, degree_u, degree_v, knotvector_u, knotvector_v, control_points, weights=None, normalize_knots=False):
        return SvGeomdlSurface.build_geomdl(degree_u, degree_v, knotvector_u, knotvector_v, control_points, weights, normalize_knots)

    def get_input_orientation(self):
        return 'Z'

    def get_coord_mode(self):
        return 'UV'

    def get_u_min(self):
        return self.u_bounds[0]

    def get_u_max(self):
        return self.u_bounds[1]

    def get_v_min(self):
        return self.v_bounds[0]

    def get_v_max(self):
        return self.v_bounds[1]

    @property
    def u_size(self):
        return self.u_bounds[1] - self.u_bounds[0]

    @property
    def v_size(self):
        return self.v_bounds[1] - self.v_bounds[0]

    @property
    def has_input_matrix(self):
        return False

    def evaluate(self, u, v):
        vert = self.surface.evaluate_single((u, v))
        return np.array(vert)

    def evaluate_array(self, us, vs):
        uv_coords = list(zip(list(us), list(vs)))
        verts = self.surface.evaluate_list(uv_coords)
        verts = np.array(verts)
        return verts

    def normal(self, u, v):
        return self.normal_array(np.array([u]), np.array([v]))[0]

    def normal_array(self, us, vs):
        if geomdl is not None:
            uv_coords = list(zip(list(us), list(vs)))
            spline_normals = np.array( operations.normal(self.surface, uv_coords) )[:,1,:]
            return spline_normals

    def derivatives_list(self, us, vs):
        result = []
        for u, v in zip(us, vs):
            ds = self.surface.derivatives(u, v, order=2)
            result.append(ds)
        return np.array(result)

    def curvature_calculator(self, us, vs, order=True):
        surf_vertices = self.evaluate_array(us, vs)

        derivatives = self.derivatives_list(us, vs)
        # derivatives[i][j][k] = derivative w.r.t U j times, w.r.t. V k times, at i'th pair of (u, v)
        fu = derivatives[:,1,0]
        fv = derivatives[:,0,1]

        normal = np.cross(fu, fv)
        norm = np.linalg.norm(normal, axis=1, keepdims=True)
        normal = normal / norm

        fuu = derivatives[:,2,0]
        fvv = derivatives[:,0,2]
        fuv = derivatives[:,1,1]

        nuu = (fuu * normal).sum(axis=1)
        nvv = (fvv * normal).sum(axis=1)
        nuv = (fuv * normal).sum(axis=1)

        duu = np.linalg.norm(fu, axis=1) **2
        dvv = np.linalg.norm(fv, axis=1) **2
        duv = (fu * fv).sum(axis=1)

        calc = SurfaceCurvatureCalculator(us, vs, order=order)
        calc.set(surf_vertices, normal, fu, fv, duu, dvv, duv, nuu, nvv, nuv)
        return calc

    def derivatives_data_array(self, us, vs):
        surf_vertices = self.evaluate_array(us, vs)
        derivatives = self.derivatives_list(us, vs)
        # derivatives[i][j][k] = derivative w.r.t U j times, w.r.t. V k times, at i'th pair of (u, v)
        du = derivatives[:,1,0]
        dv = derivatives[:,0,1]
        return SurfaceDerivativesData(surf_vertices, du, dv)

class SvNativeNurbsSurface(SvNurbsSurface):
    def __init__(self, degree_u, degree_v, knotvector_u, knotvector_v, control_points, weights, normalize_knots=False):
        self.degree_u = degree_u
        self.degree_v = degree_v
        self.knotvector_u = np.array(knotvector_u)
        self.knotvector_v = np.array(knotvector_v)
        if normalize_knots:
            self.knotvector_u = sv_knotvector.normalize(self.knotvector_u)
            self.knotvector_v = sv_knotvector.normalize(self.knotvector_v)
        self.control_points = np.array(control_points)
        self.weights = np.array(weights)
        c_ku, c_kv, _ = self.control_points.shape
        w_ku, w_kv = self.weights.shape
        if c_ku != w_ku or c_kv != w_kv:
            raise Exception(f"Shape of control_points ({c_ku}, {c_kv}) does not match to shape of weights ({w_ku}, {w_kv})")
        self.basis_u = SvNurbsBasisFunctions(knotvector_u)
        self.basis_v = SvNurbsBasisFunctions(knotvector_v)
        self.u_bounds = (self.knotvector_u.min(), self.knotvector_u.max())
        self.v_bounds = (self.knotvector_v.min(), self.knotvector_v.max())
        self.normal_delta = 0.0001
        self.__description__ = f"Native NURBS (degree={degree_u}x{degree_v}, pts={self.control_points.shape[0]}x{self.control_points.shape[1]})"

    @classmethod
    def build(cls, implementation, degree_u, degree_v, knotvector_u, knotvector_v, control_points, weights=None, normalize_knots=False):
        return SvNativeNurbsSurface(degree_u, degree_v, knotvector_u, knotvector_v, control_points, weights, normalize_knots)

    @classmethod
    def get_nurbs_implementation(cls):
        return SvNurbsSurface.NATIVE

    def insert_knot(self, direction, parameter, count=1):
        if direction == SvNurbsSurface.U:
            new_points = []
            new_weights = []
            new_u_degree = None
            for i in range(self.control_points.shape[1]):
                fixed_v_points = self.control_points[:,i]
                fixed_v_weights = self.weights[:,i]
                fixed_v_curve = SvNurbsMaths.build_curve(SvNurbsMaths.NATIVE,
                                    self.degree_u, self.knotvector_u,
                                    fixed_v_points, fixed_v_weights)
                fixed_v_curve = fixed_v_curve.insert_knot(parameter, count)
                fixed_v_knotvector = fixed_v_curve.get_knotvector()
                new_u_degree = fixed_v_curve.get_degree()
                fixed_v_points = fixed_v_curve.get_control_points()
                fixed_v_weights = fixed_v_curve.get_weights()
                new_points.append(fixed_v_points)
                new_weights.append(fixed_v_weights)

            new_points = np.transpose(np.array(new_points), axes=(1,0,2))
            new_weights = np.array(new_weights).T

            return SvNativeNurbsSurface(new_u_degree, self.degree_v,
                    fixed_v_knotvector, self.knotvector_v,
                    new_points, new_weights)

        elif direction == SvNurbsSurface.V:
            new_points = []
            new_weights = []
            new_v_degree = None
            for i in range(self.control_points.shape[0]):
                fixed_u_points = self.control_points[i,:]
                fixed_u_weights = self.weights[i,:]
                fixed_u_curve = SvNurbsMaths.build_curve(SvNurbsMaths.NATIVE,
                                    self.degree_v, self.knotvector_v,
                                    fixed_u_points, fixed_u_weights)
                fixed_u_curve = fixed_u_curve.insert_knot(parameter, count)
                fixed_u_knotvector = fixed_u_curve.get_knotvector()
                new_v_degree = fixed_u_curve.get_degree()
                fixed_u_points = fixed_u_curve.get_control_points()
                fixed_u_weights = fixed_u_curve.get_weights()
                new_points.append(fixed_u_points)
                new_weights.append(fixed_u_weights)

            new_points = np.array(new_points)
            new_weights = np.array(new_weights)

            return SvNativeNurbsSurface(self.degree_u, new_v_degree,
                    self.knotvector_u, fixed_u_knotvector,
                    new_points, new_weights)
        else:
            raise Exception("Unsupported direction")

    def get_degree_u(self):
        return self.degree_u

    def get_degree_v(self):
        return self.degree_v

    def get_knotvector_u(self):
        return self.knotvector_u

    def get_knotvector_v(self):
        return self.knotvector_v

    def get_control_points(self):
        return self.control_points

    def get_weights(self):
        return self.weights

    def get_u_min(self):
        return self.u_bounds[0]

    def get_u_max(self):
        return self.u_bounds[1]

    def get_v_min(self):
        return self.v_bounds[0]

    def get_v_max(self):
        return self.v_bounds[1]

    def evaluate(self, u, v):
        return self.evaluate_array(np.array([u]), np.array([v]))[0]

    def fraction(self, deriv_order_u, deriv_order_v, us, vs):
        pu = self.degree_u
        pv = self.degree_v
        ku, kv, _ = self.control_points.shape
        nsu = np.array([self.basis_u.derivative(i, pu, deriv_order_u)(us) for i in range(ku)]) # (ku, n)
        nsv = np.array([self.basis_v.derivative(i, pv, deriv_order_v)(vs) for i in range(kv)]) # (kv, n)
        nsu = np.transpose(nsu[np.newaxis], axes=(1,0,2)) # (ku, 1, n)
        nsv = nsv[np.newaxis] # (1, kv, n)
        ns = nsu * nsv # (ku, kv, n)
        weights = np.transpose(self.weights[np.newaxis], axes=(1,2,0)) # (ku, kv, 1)
        coeffs = ns * weights # (ku, kv, n)
        coeffs = np.transpose(coeffs[np.newaxis], axes=(3,1,2,0)) # (n,ku,kv,1)
        controls = self.control_points # (ku,kv,3)

        numerator = coeffs * controls # (n,ku,kv,3)
        numerator = numerator.sum(axis=1).sum(axis=1) # (n,3)
        denominator = coeffs.sum(axis=1).sum(axis=1)

        return numerator, denominator

    def evaluate_array(self, us, vs):
        numerator, denominator = self.fraction(0, 0, us, vs)
        return numerator / denominator

    def normal(self, u, v):
        return self.normal_array(np.array([u]), np.array([v]))[0]

    def normal_array(self, us, vs):
        numerator, denominator = self.fraction(0, 0, us, vs)
        surface = numerator / denominator
        numerator_u, denominator_u = self.fraction(1, 0, us, vs)
        numerator_v, denominator_v = self.fraction(0, 1, us, vs)
        surface_u = (numerator_u - surface*denominator_u) / denominator
        surface_v = (numerator_v - surface*denominator_v) / denominator
        normal = np.cross(surface_u, surface_v)
        n = np.linalg.norm(normal, axis=1, keepdims=True)
        normal = normal / n
        return normal

    def derivatives_data_array(self, us, vs):
        numerator, denominator = self.fraction(0, 0, us, vs)
        surface = numerator / denominator
        numerator_u, denominator_u = self.fraction(1, 0, us, vs)
        numerator_v, denominator_v = self.fraction(0, 1, us, vs)
        surface_u = (numerator_u - surface*denominator_u) / denominator
        surface_v = (numerator_v - surface*denominator_v) / denominator
        return SurfaceDerivativesData(surface, surface_u, surface_v)

    def curvature_calculator(self, us, vs, order=True):
    
        numerator, denominator = self.fraction(0, 0, us, vs)
        surface = numerator / denominator
        numerator_u, denominator_u = self.fraction(1, 0, us, vs)
        numerator_v, denominator_v = self.fraction(0, 1, us, vs)
        surface_u = (numerator_u - surface*denominator_u) / denominator
        surface_v = (numerator_v - surface*denominator_v) / denominator

        normal = np.cross(surface_u, surface_v)
        n = np.linalg.norm(normal, axis=1, keepdims=True)
        normal = normal / n

        numerator_uu, denominator_uu = self.fraction(2, 0, us, vs)
        surface_uu = (numerator_uu - 2*surface_u*denominator_u - surface*denominator_uu) / denominator
        numerator_vv, denominator_vv = self.fraction(0, 2, us, vs)
        surface_vv = (numerator_vv - 2*surface_v*denominator_v - surface*denominator_vv) / denominator

        numerator_uv, denominator_uv = self.fraction(1, 1, us, vs)
        surface_uv = (numerator_uv - surface_v*denominator_u - surface_u*denominator_v - surface*denominator_uv) / denominator

        nuu = (surface_uu * normal).sum(axis=1)
        nvv = (surface_vv * normal).sum(axis=1)
        nuv = (surface_uv * normal).sum(axis=1)

        duu = np.linalg.norm(surface_u, axis=1) **2
        dvv = np.linalg.norm(surface_v, axis=1) **2
        duv = (surface_u * surface_v).sum(axis=1)

        calc = SurfaceCurvatureCalculator(us, vs, order=order)
        calc.set(surface, normal, surface_u, surface_v, duu, dvv, duv, nuu, nvv, nuv)
        return calc

def unify_degrees(curves):
    max_degree = max(curve.get_degree() for curve in curves)
    curves = [curve.elevate_degree(target=max_degree) for curve in curves]
    return curves

def unify_curves(curves):
    curves = [curve.reparametrize(0.0, 1.0) for curve in curves]

    dst_knots = defaultdict(int)
    for curve in curves:
        m = sv_knotvector.to_multiplicity(curve.get_knotvector())
        for u, count in m:
            u = round(u, 6)
            dst_knots[u] = max(dst_knots[u], count)

    result = []
#     for i, curve1 in enumerate(curves):
#         for j, curve2 in enumerate(curves):
#             if i != j:
#                 curve1 = curve1.to_knotvector(curve2)
#         result.append(curve1)

    for curve in curves:
        diffs = []
        kv = np.round(curve.get_knotvector(), 6)
        ms = dict(sv_knotvector.to_multiplicity(kv))
        for dst_u, dst_multiplicity in dst_knots.items():
            src_multiplicity = ms.get(dst_u, 0)
            diff = dst_multiplicity - src_multiplicity
            diffs.append((dst_u, diff))
        #print(f"Src {ms}, dst {dst_knots} => diff {diffs}")

        for u, diff in diffs:
            if diff > 0:
                curve = curve.insert_knot(u, diff)
        result.append(curve)
        
    return result

def build_from_curves(curves, degree_u = None, implementation = SvNurbsSurface.NATIVE):
    curves = unify_curves(curves)
    degree_v = curves[0].get_degree()
    if degree_u is None:
        degree_u = degree_v
    control_points = [curve.get_control_points() for curve in curves]
    control_points = np.array(control_points)
    weights = np.array([curve.get_weights() for curve in curves])
    knotvector_u = sv_knotvector.generate(degree_u, len(curves))
    #knotvector_v = curves[0].get_knotvector()
    knotvector_v = sv_knotvector.average([curve.get_knotvector() for curve in curves])

    surface = SvNurbsSurface.build(implementation,
                degree_u, degree_v,
                knotvector_u, knotvector_v,
                control_points, weights)

    return curves, surface

def simple_loft(curves, degree_v = None, knots_u = 'UNIFY', metric='DISTANCE', implementation=SvNurbsSurface.NATIVE):
    """
    Loft between given NURBS curves (a.k.a skinning).

    inputs:
    * degree_v - degree of resulting surface along V parameter; by default - use the same degree as provided curves
    * knots_u - one of:
        - 'UNIFY' - unify knotvectors of given curves by inserting additional knots
        - 'AVERAGE' - average knotvectors of given curves; this will work only if all curves have the same number of control points
    * metric - metric for interpolation; most useful are 'DISTANCE' and 'CENTRIPETAL'
    * implementation - NURBS maths implementation

    output: tuple:
        * list of curves - input curves after unification
        * generated NURBS surface.
    """
    if knots_u not in {'UNIFY', 'AVERAGE'}:
        raise Exception(f"Unsupported knots_u option: {knots_u}")
    curve_class = type(curves[0])
    curves = unify_degrees(curves)
    if knots_u == 'UNIFY':
        curves = unify_curves(curves)
    else:
        kvs = [len(curve.get_control_points()) for curve in curves]
        max_kv, min_kv = max(kvs), min(kvs)
        if max_kv != min_kv:
            raise Exception(f"U knotvector averaging is not applicable: Curves have different number of control points: {kvs}")

    degree_u = curves[0].get_degree()
    if degree_v is None:
        degree_v = degree_u

    src_points = [curve.get_homogenous_control_points() for curve in curves]
#     lens = [len(pts) for pts in src_points]
#     max_len, min_len = max(lens), min(lens)
#     if max_len != min_len:
#         raise Exception(f"Unify error: curves have different number of control points: {lens}")

    src_points = np.array(src_points)
    #print("Src:", src_points)
    src_points = np.transpose(src_points, axes=(1,0,2))

    v_curves = [interpolate_nurbs_curve(curve_class, degree_v, points, metric) for points in src_points]
    control_points = [curve.get_homogenous_control_points() for curve in v_curves]
    control_points = np.array(control_points)
    #weights = [curve.get_weights() for curve in v_curves]
    #weights = np.array([curve.get_weights() for curve in curves]).T
    n,m,ndim = control_points.shape
    control_points = control_points.reshape((n*m, ndim))
    control_points, weights = from_homogenous(control_points)
    control_points = control_points.reshape((n,m,3))
    weights = weights.reshape((n,m))

    mean_v_vector = control_points.mean(axis=0)
    tknots_v = Spline.create_knots(mean_v_vector, metric=metric)
    knotvector_v = sv_knotvector.from_tknots(degree_v, tknots_v)
    if knots_u == 'UNIFY':
        knotvector_u = curves[0].get_knotvector()
    else:
        knotvectors = np.array([curve.get_knotvector() for curve in curves])
        knotvector_u = knotvectors.mean(axis=0)
    
    surface = SvNurbsSurface.build(implementation,
                degree_u, degree_v,
                knotvector_u, knotvector_v,
                control_points, weights)
    return curves, v_curves, surface

SvNurbsMaths.surface_classes[SvNurbsMaths.NATIVE] = SvNativeNurbsSurface
if geomdl is not None:
    SvNurbsMaths.surface_classes[SvNurbsMaths.GEOMDL] = SvGeomdlSurface

