# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####


import bpy

from sverchok.node_tree import SverchCustomTreeNode
from sverchok.data_structure import updateNode, repeat_last
from sverchok.utils.avl_tree import AVLTree
from sverchok.utils.dcel import Debugger as D


x, y, z = 0, 1, 2
test_hedge = []
test_intersections = []
test_event_point = []


def is_ccw(a, b, c):
    """
    Tests whether the turn formed by A, B, and C is counter clockwise
    :param a: 2d point - any massive
    :param b: 2d point - any massive
    :param c: 2d point - any massive
    :return: True if turn is counter clockwise else False
    """
    return (b[x] - a[x]) * (c[y] - a[y]) > (b[y] - a[y]) * (c[x] - a[x])


def is_ccw_polygon(all_verts=None, most_lefts=None):
    """
    The function get either all points or most left point and its two neighbours of the polygon
    and returns True if order of points are in counterclockwise
    :param all_verts: [(x, y, z) or (x, y), ...]
    :param most_lefts: [(x, y, z) or (x, y), ...]
    :return: bool
    """
    def is_vertical(points):
        # is 3 most left points vertical
        if points[0][x] == points[1][x] == points[2][x]:
            return True
        else:
            return False
    if all([all_verts, most_lefts]) or not any([all_verts, most_lefts]):
        raise ValueError('The function get either all points or most left point and its two neighbours of the polygon.')
    if all_verts:
        x_min = min(range(len(all_verts)), key=lambda i: all_verts[i][x])
        most_lefts = [all_verts[(x_min - 1) % len(all_verts)], all_verts[x_min], all_verts[(x_min + 1) % len(all_verts)]]
    if is_vertical(most_lefts):
        # here is handled corner case when most left points are vertical
        return True if most_lefts[0][y] > most_lefts[1][y] else False
    else:
        return True if is_ccw(*most_lefts) else False


def cross_product(v1, v2):
    """
    Cross product of two any dimension vectors
    :param v1: any massive
    :param v2: any massive
    :return: list
    """
    out = []
    l = len(v1)
    for i in range(l):
        out.append(v1[(i + 1) % l] * v2[(i + 2) % l] - v1[(i + 2) % l] * v2[(i + 1) % l])
    return out


def convert_homogeneous_to_cartesian(v):
    """
    Convert from homogeneous to cartesian system coordinate
    :param v: massive of any length
    :return: list
    """
    w = v[-1]
    out = []
    for s in v[:-1]:
        out.append(s / w)
    return out


def intersect_lines_2d(a1, a2, b1, b2):
    """
    Find intersection of two lines determined by two coordinates
    :param a1: point 1 of line a - any massive
    :param a2: point 2 of line a - any massive
    :param b1: point 1 of line b - any massive
    :param b2: point 2 of line b - any massive
    :return: returns intersection point (list) if lines are not parallel else returns False
    """
    cross_a = cross_product((a1[x], a1[y], 1), (a2[x], a2[y], 1))
    cross_b = cross_product((b1[x], b1[y], 1), (b2[x], b2[y], 1))
    hom_v = cross_product(cross_a, cross_b)
    if hom_v[2] != 0:
        return convert_homogeneous_to_cartesian(hom_v)
    elif not any(hom_v):
        return False  # two lines ara overlaping
    else:
        return False  # two lines are parallel


def dot_product(v1, v2):
    """
    Calculate dot product of two vectors
    :param v1: massive of any length
    :param v2: massive of any length
    :return: float
    """
    out = 0
    for i in range(len(v1)):
        out += v1[i] * v2[i]
    return out


def almost_equal(v1, v2, epsilon=1e-6):
    """
    Compare floating values
    :param v1: int, float
    :param v2: int, float
    :param epsilon: value of accuracy
    :return: True if values are equal else False
    """
    return abs(v1 - v2) < epsilon


def is_less(v1, v2, epsilon=1e-6):
    return v2 - v1 > epsilon


def is_more(v1, v2, epsilon=1e-6):
    return v1 - v2 > epsilon


def is_edges_intersect_2d(a1, b1, a2, b2):
    """
    Returns True if line segments a1b1 and a2b2 intersect
    If point of one edge lays on another edge this recognize like intersection
    :param a1: first 2d point of fist segment - any massive
    :param b1: second 2d point of fist segment - any massive
    :param a2: first 2d point of second segment - any massive
    :param b2: second 2d point of second segment - any massive
    :return: True if edges are intersected else False
    """
    return ((is_ccw(a1, b1, a2) != is_ccw(a1, b1, b2) or is_ccw(b1, a1, a2) != is_ccw(b1, a1, b2)) and
            (is_ccw(a2, b2, a1) != is_ccw(a2, b2, b1) or is_ccw(b2, a2, a1) != is_ccw(b2, a2, b1)))


class EdgeSweepLine:
    # Special class for storing in status data structure
    global_event_point = None

    def __init__(self, v1, v2, i1, i2):
        self.v1 = v1
        self.v2 = v2
        self.i1 = i1
        self.i2 = i2

        self.last_event = None
        self.last_intersection = None
        self.last_product = None

        self.cross = cross_product((self.v1[x], self.v1[y], 1), (self.v2[x], self.v2[y], 1))
        self.up_i = self.i1 if self.get_low_index() == 1 else self.i2
        self.low_i = self.i2 if self.up_i == self.i1 else self.i1
        self.up_v = self.v1 if self.get_low_index() == 1 else self.v2
        self.low_v = self.v1 if self.get_low_index() == 0 else self.v2
        self.is_horizontal = almost_equal(self.up_v[y], self.low_v[y])
        self.direction = self.get_direction()

        self.low_hedge = None
        self.up_hedge = None
        self.coincidence = []

        self.helper = None

    def __str__(self):
        return 'Edge({}, {})({})'.format(self.i1, self.i2, self.subdivision)

    def __lt__(self, other):
        #debug("~~~~~~~~Start to compare {} < {}".format(self, other))
        # when edge are inserting to the three
        if isinstance(other, EdgeSweepLine):
            # if two edges intersect in one point less edge will be with bigger angle with X coordinate
            if almost_equal(self.intersection, other.intersection):
                #Debugger.print_e([self, other], "Edges intersects in the same point")
                if almost_equal(self.product, other.product):
                    # two edges are overlapping each other, there is no need of storing them together in tree
                    # longest edge should take place in tree with information of both overlapping edges
                    # input can have equal edges, such cases should be handled externally
                    return False
                else:
                    return self.product < other.product
            else:
                #Debugger.print_e(self, '{}-intersections'.format(self.intersection))
                #Debugger.print_e(other, '{}-intersections'.format(other.intersection))
                return self.intersection < other.intersection
        # this part is for searching edges by value of x coordinate of event point
        else:
            #debug("Edge is compared with value {}, intersection: {} < {}".format(self, self.intersection, other))
            if almost_equal(self.intersection, other):
                #debug("Edge and value are equal")
                return False
            else:
                #debug("Edge < value ?")
                return self.intersection < other

    def __gt__(self, other):
        #debug("~~~~~~~~~Start to compare {} > {}".format(self, other))
        # when edge are inserting to the three
        if isinstance(other, EdgeSweepLine):
            # if two edges intersect in one point bigger edge will be with less angle with X coordinate
            if almost_equal(self.intersection, other.intersection):
                #Debugger.print_e([self, other], "Edges intersects in the same point")
                if almost_equal(self.product, other.product):
                    # two edges are overlapping each other, there is no need of storing them together in tree
                    # longest edge should take place in tree with information of both overlapping edges
                    # input can have equal edges, such cases should be handled externally
                    return False
                else:
                    return self.product > other.product
            else:
                #debug("Self.intersection: {} > other.intersection: {}".format(self.intersection, other.intersection))
                return self.intersection > other.intersection
        # this part is for searching edges by value of x coordinate of event point
        else:
            #debug("Edge is compared with value {}, intersection: {} > {}".format(self, self.intersection, other))
            if almost_equal(self.intersection, other):
                #debug("Edge and value are equal")
                return False
            else:
                #debug("Edge < value ?")
                return self.intersection > other

    @property
    def intersection(self):
        # find intersection current edge with sweeping line
        if self.is_horizontal:
            return self.event_point.co[x]
        if self.event_point != self.last_event:
            self.update_params()
        return self.last_intersection

    @property
    def product(self):
        # if edges has same point of intersection with sweep line they are sorting by angle to sweep line
        if self.is_horizontal:
            # if inserting edge is horizontal it always bigger for storing it to the end of sweep line
            return 1
        if self.event_point != self.last_event:
            self.update_params()
        return self.last_product

    def update_params(self):
        # when new event point some parameters should be recalculated
        self.last_intersection = (self.event_point.co[y] * self.cross[y] + self.cross[z]) / -self.cross[x]
        self.last_product = dot_product(self.direction, (1, 0))
        self.last_event = self.event_point

    def get_low_index(self):
        # find index in edge of index of lowest point
        if is_more(self.v1[y], self.v2[y]):
            out = 1
        elif is_less(self.v1[y], self.v2[y]):
            out = 0
        else:
            if is_less(self.v1[x], self.v2[x]):
                out = 1
            else:
                out = 0  # Исправить в алгоритме пересечений отрезков !!!
        return out

    @property
    def is_c(self):
        # returns True if current event point is intersection point of current edge
        return not (almost_equal(self.low_v[x], self.event_point.co[x]) and
                    almost_equal(self.low_v[y], self.event_point.co[y]))

    @property
    def event_point(self):
        # get actual event point
        if EdgeSweepLine.global_event_point is not None:
            return EdgeSweepLine.global_event_point
        else:
            raise Exception('Sweep line should be initialized before')

    def get_direction(self):
        # get downward direction of edge
        vector = (self.low_v[x] - self.up_v[x], self.low_v[y] - self.up_v[y])
        v_len = (vector[x] ** 2 + vector[y] ** 2) ** 0.5
        return (vector[x] / v_len, vector[y] / v_len)

    @property
    def low_dot_length(self):
        vector = [ax1 - ax2 for ax1, ax2 in zip(self.event_point.co, self.low_v)]
        return dot_product(vector, vector)

    def get_angle(self):
        # this does not take in account cases with c edges
        if self.is_horizontal:
            pass

    @property
    def inner_hedge(self):
        return self.low_hedge if self.low_hedge.i == self.event_point.i else self.up_hedge

    @property
    def outer_hedge(self):
        return self.low_hedge if self.low_hedge.i != self.event_point.i else self.up_hedge

    @property
    def subdivision(self):
        if self.up_hedge is None:
            return None
        else:
            return {v for s in [self.up_hedge, self.low_hedge] for v in s.subdivision}

    def set_low_i(self, i):
        self.i1, self.i2 = (i, self.i2) if self.low_i == self.i1 else (self.i1, i)
        self.low_i = i
        self.low_hedge.i = i

    def set_up_i(self, i):
        self.i1, self.i2 = (i, self.i2) if self.up_i == self.i1 else (self.i1, i)
        self.up_i = i
        self.up_hedge.i = i


class EventPoint:
    # Special class for storing in queue data structure

    max_index = -1
    monotone_current_face = None

    def __init__(self, co, index=None):
        self.co = co
        self.i = index
        self.up_edges = []  # this attribute for finding intersections algorithm
        self.hedge = None  # this attribute for making monotone algorithm
        self._type = None
        self.last_monotone_face = None
        self.check_index()

    def __str__(self):
        #return "({:.1f}, {:.1f})".format(self.co[x], self.co[y])
        return "{}".format(self.i)

    def __lt__(self, other):
        # Sorting of points from upper left point to lowest right point
        if is_less(-self.co[y], -other.co[y]):
            return True
        elif is_more(-self.co[y], -other.co[y]):
            return False
        elif is_less(self.co[x], other.co[x]):
            return True
        else:
            return False

    def __gt__(self, other):
        # Sorting of points from upper left point to lowest right point
        if is_more(-self.co[y], -other.co[y]):
            return True
        elif is_less(-self.co[y], -other.co[y]):
            return False
        elif is_more(self.co[x], other.co[x]):
            return True
        else:
            return False

    def check_index(self):
        if self.i is None:
            EventPoint.max_index += 1
            self.i = EventPoint.max_index
        elif self.i > EventPoint.max_index:
            EventPoint.max_index = self.i

    @property
    def type(self):
        # for partitioning algorithm
        # the type should be updated each time when polygon is changed in partitioning algorithm
        # during handle of polygon point does not change type
        face = self.monotone_face
        if not self._type:
            for coin_hedge in self.hedge.ccw_hedges:
                if coin_hedge.face == face:
                    hedge = coin_hedge
                    break
            next_point = hedge.next.point  # hedge.twin does not have point because points are set for current face only
            last_point = hedge.last.point
            is_up_next = next_point < self  # the less point the upper it is
            is_up_last = last_point < self
            if not is_up_next and not is_up_last:
                self._type = 'start' if self.hedge < self.hedge.last.twin else 'split'
            elif is_up_last and is_up_next:
                self._type = 'merge' if self.hedge > self.hedge.last.twin else 'end'
            else:
                self._type = 'regular'
        return self._type

    @property
    def monotone_face(self):
        if not EventPoint.monotone_current_face:
            raise Exception('Which polygon is handling should be set before')
        elif self.last_monotone_face != EventPoint.monotone_current_face:
            self.last_monotone_face = EventPoint.monotone_current_face
            self._type = None
        return self.last_monotone_face


def get_coincidence_edges(tree, x_position):
    """
    Get from status all edges and their neighbours which go through event point
    :param tree: status data structure - AVLTree
    :param x_position: x position of event point
    :return: tuple(left neighbour, adjacent edges, right neighbour) - (AVL node, [AVL node, ...], AVL node)
    """
    start_node = tree.find(x_position)
    tree_max_length = tree.max_len()
    #print("searching neighbos, start node -", start_node)
    right_part = [start_node] if start_node else []
    left_part = []
    adjacent_right = None
    adjacent_left = None

    counter = 0
    next_node = start_node
    while next_node:
        next_node = next_node.next
        if next_node and almost_equal(next_node.key.intersection, x_position):
            right_part.append(next_node)
        elif next_node:
            adjacent_right = next_node.key
            break
        if counter > tree_max_length:
            raise TimeoutError("Can't find exit from status tree, start node -", start_node)
        counter += 1

    counter = 0
    last_node = start_node
    while last_node:
        last_node = last_node.last
        if last_node and almost_equal(last_node.key.intersection, x_position):
            left_part.append(last_node)
        elif last_node:
            adjacent_left = last_node.key
            break
        if counter > tree_max_length:
            raise TimeoutError("Can't find exit from status tree, start node -", start_node)
        counter += 1

    return adjacent_left, left_part[::-1] + right_part, adjacent_right


def get_upper_vert(verts, edge):
    """
    Get index in edge of index upper point for given edge
    :param verts: vertex which are linked with edge - [(x, y), ...]
    :param edge: indexes to two vertexes - (5, 2)
    :return: 0 if vert[5][y] > vert[2][y] else 1
    """
    if verts[edge[0]][y] > verts[edge[1]][y]:
        upper_vert = 0
    elif verts[edge[0]][y] < verts[edge[1]][y]:
        upper_vert = 1
    else:
        if verts[edge[0]][x] < verts[edge[1]][x]:
            upper_vert = 0
        else:
            upper_vert = 1
    return upper_vert


class HalfEdge:

    def __init__(self, origin, i=None, face=None):
        self.origin = origin  # This just coordinates now, should be point object later
        self.i = i
        self.face = face
        self.in_faces = {face} if face else set()

        self.twin = None
        self.next = None
        self.last = None
        self.left = None
        self.point = None
        self.cash_product = None
        self.edge = None

    def __str__(self):
        return 'he-{}'.format((self.i, self.twin.i))

    def __lt__(self, other):
        # if self < other other it means that direction if closer to (-1, 0) direction
        if isinstance(other, HalfEdge):
            if almost_equal(self.product, other.product):
                return False
            else:
                return self.product < other.product
        else:
            raise TypeError('unorderable types: {} < {}'.format(type(self), type(other)))

    def __gt__(self, other):
        if isinstance(other, HalfEdge):
            if almost_equal(self.product, other.product):
                return False
            else:
                return self.product > other.product
        else:
            raise TypeError('unorderable types: {} > {}'.format(type(self), type(other)))

    @property
    def product(self):
        if not self.cash_product:
            #Debugger.print_he(self)
            #Debugger.print('is horizontal - ({})'.format(almost_equal(self.origin[y], self.twin.origin[y])),
            #              'is left directed - ({})'.format(is_more(self.origin[x], self.twin.origin[x])))
            if almost_equal(self.origin[y], self.twin.origin[y]):
                if is_more(self.origin[x], self.twin.origin[x]):
                    self.cash_product = 4
                else:
                    self.cash_product = 2
            elif self.twin.cash_product:
                self.cash_product = (self.twin.cash_product + 2) % 4
            else:
                vector = (self.twin.point.co[x] - self.point.co[x], self.twin.point.co[y] - self.point.co[y])
                v_len = (vector[x] ** 2 + vector[y] ** 2) ** 0.5
                norm_v = (vector[x] / v_len, vector[y] / v_len)
                product = dot_product(norm_v, (1, 0))
                product = product + 1 if self.point < self.twin.point else 3 - product
                self.cash_product = product
        return self.cash_product

    @property
    def subdivision(self):
        return {s for face in self.in_faces for s in face.subdivision}

    @property
    def ccw_hedges(self):
        # returns hedges originated in one point
        yield self
        next_edge = self.last.twin
        counter = 0
        while next_edge != self:
            yield next_edge
            next_edge = next_edge.last.twin
            counter += 1
            if counter > EventPoint.max_index * 2:
                raise RecursionError('Hedge - {} does not have a loop'.format(self.i))

    @property
    def loop_hedges(self):
        yield self
        next_edge = self.next
        counter = 0
        while next_edge != self:
            yield next_edge
            next_edge = next_edge.next
            counter += 1
            if counter > EventPoint.max_index * 2:
                raise RecursionError('Hedge - {} does not have a loop'.format(self.i))


class Face:
    def __init__(self, i, subdivision=None):
        self.i = i
        self.outer = None
        self.inners = []
        self.subdivision = set()
        if subdivision:
            self.subdivision = subdivision

    def __str__(self):
        return 'f{}{}'.format(self.i, self.subdivision)

    @property
    def outer_hedges(self):
        if not self.outer:
            raise StopIteration
        yield self.outer
        next_hedge = self.outer.next
        count = 0
        while next_hedge != self.outer:
            yield next_hedge
            next_hedge = next_hedge.next
            count += 1
            if count > EventPoint.max_index * 2:
                raise RecursionError('Face ({}), consists hedge '
                                     'which has wrong links to other neighbours'.format(self.i))

    @property
    def inner_hedges(self):
        if not self.inners:
            raise StopIteration
        for hedge in self.inners:
            yield hedge
            next_hedge = hedge.next
            count = 0
            while next_hedge != hedge:
                yield next_hedge
                next_hedge = next_hedge.next
                count += 1
                if count > EventPoint.max_index * 2:
                    raise RecursionError('Face ({}), consists hedge '
                                         'which has wrong links to other neighbours'.format(self.i))

    @property
    def all_hedges(self):
        yield from self.outer_hedges
        yield from self.inner_hedges


class Debugger(D):

    @staticmethod
    def print_n(node, msg=None):
        # print node of binary tree
        def print_node(node, msg=None):
            if not D.to_print:
                return
            print('{} - {}'.format(D.count, msg or 'Node'))
            D.count += 1
            D.data.append([node.key.v1, node.key.v2])
        print_node(node, msg)
        if node.leftChild:
            print_node(node.leftChild, 'left child')
        if node.rightChild:
            print_node(node.rightChild, 'right child')


def create_half_edges(verts, faces):
    # this function generates only outer faces
    # this function should be accurate in generation half edges data
    # it this implementation there is important parameter as total number of points
    # this parameter responsible for raising errors during iteration via half edges
    # it will be better to create separate module for DCEL data structure - http://www.holmes3d.net/graphics/dcel/
    # where this issue will be encapsulated
    # todo: self intersection polygons? double repeated polygons???
    half_edges_list = dict()
    points = [EventPoint(co) for co in verts]
    for i_face, face in enumerate(faces):
        face = face if is_ccw_polygon([verts[i] for i in face]) else face[::-1]
        f = Face(i_face, {0})
        loop = []
        for i in range(len(face)):
            origin_i = face[i]
            next_i = face[(i + 1) % len(face)]
            half_edge = HalfEdge(verts[origin_i], origin_i, f)
            half_edge.point = points[origin_i]
            loop.append(half_edge)
            half_edges_list[(origin_i, next_i)] = half_edge
        for i in range(len(face)):
            loop[i].last = loop[(i - 1) % len(face)]
            loop[i].next = loop[(i + 1) % len(face)]
        f.outer = loop[0]
        #Debugger.print_he(loop, 'face from sv edges', 'next')
    outer_half_edges = dict()
    for key in half_edges_list:
        half_edge = half_edges_list[key]
        if key[::-1] in half_edges_list:
            half_edge.twin = half_edges_list[key[::-1]]
        else:
            outer_edge = HalfEdge(verts[key[1]], key[1])
            outer_edge.point = points[key[1]]
            half_edge.twin = outer_edge
            outer_edge.twin = half_edge
            if key[::-1] in outer_half_edges:
                raise Exception("It looks like input mesh has adjacent faces with only one common point"
                                "Handle such meshes does not implemented yet.")
            outer_half_edges[key[::-1]] = outer_edge
    for key in outer_half_edges:
        outer_edge = outer_half_edges[key]
        next_edge = outer_edge.twin
        while next_edge:
            next_edge = next_edge.last.twin
            if not next_edge.face:
                break
        outer_edge.next = next_edge
        next_edge.last = outer_edge
    return list(half_edges_list.values()) + list(outer_half_edges.values())


def merge_two_half_edges_list(a, b, len_verts_a=None):
    out = list(a)
    faces = set()
    for half_edge in b:
        if len_verts_a:
            half_edge.i += len_verts_a
        if half_edge.face:
            faces.add(half_edge.face)
        out.append(half_edge)
    for face in faces:
        face.subdivision = {v + 1 for v in face.subdivision}
    if len_verts_a:
        EventPoint.max_index += len_verts_a
    return out


def to_sv_mesh_from_faces(hedges, faces):
    used = set()
    sv_verts = []
    for hedge in hedges:
        counter = 0
        if hedge in used:
            continue
        sv_verts.append(hedge.origin)
        for h in hedge.ccw_hedges:
            used.add(h)
            h.i = len(sv_verts) - 1

    # This part of function creates faces in SV format.
    # It ignores  boundless super face
    sv_faces = []
    mask_a = []
    mask_b = []
    mask_c_index_a = []
    mask_c_index_b = []
    for face in faces:
        #Debugger.print_f(face, 'build face')
        if face.inners and face.outer:
            print('Face ({}) has inner components! Make bug report please.'.format(face.i))
        if not face.outer:
            continue
        #Debugger.print_he(face.outer, 'build face from')
        sv_faces.append([hedge.i for hedge in face.outer.loop_hedges])

        mask_a.append(1 if 0 in face.outer.subdivision else 0)
        mask_b.append(1 if 1 in face.outer.subdivision else 0)
        indexes_a = [face.i for face in face.outer.in_faces if 0 in face.subdivision]
        indexes_b = [face.i for face in face.outer.in_faces if 1 in face.subdivision]
        mask_c_index_a.append(min(indexes_a) if indexes_a else -1)
        mask_c_index_b.append(min(indexes_b) if indexes_b else -1)

    return sv_verts, sv_faces, mask_a, mask_b, mask_c_index_a, mask_c_index_b


def build_faces_list(hedges):
    used = set()
    inner_hedges = []
    super_face = Face(0)
    faces = [super_face]

    # build outer faces and detect inner faces (holes)
    # if face is not ccw and there is no left neighbour it is boundless super face
    # if there is left neighbour the face should be stored with only inner component,
    # outer component will be find further
    for hedge in hedges:
        if hedge in used:
            continue
        min_hedge = min([hedge for hedge in hedge.loop_hedges], key=lambda hedge: (hedge.origin[x], hedge.origin[y]))
        _is_ccw = is_ccw_polygon(most_lefts=[min_hedge.last.origin, min_hedge.origin, min_hedge.next.origin])
        # min hedge should be checked whether it look to the left or to the right
        # if to the right previous hedge should be taken
        # https://github.com/nortikin/sverchok/issues/2497#issuecomment-526096898
        min_hedge = min_hedge if min_hedge.product > 2 else min_hedge.last
        Debugger.print_he(min_hedge, 'min hedge has left component - {}'.format(bool(min_hedge.left)))
        if _is_ccw:
            face = Face(len(faces))
            face.outer = hedge
            faces.append(face)
            for h in hedge.loop_hedges:
                used.add(h)
                h.face = face
        elif not min_hedge.in_faces:
            super_face.inners.append(min_hedge)
            for h in min_hedge.loop_hedges:
                used.add(h)
                h.face = super_face
        else:
            if not min_hedge.left:
                Debugger.print_he(min_hedge, 'where is left neighbour???')
                raise AttributeError('One of inner hedges inside a outer polygon dose not have left neighbour')
            inner_hedges.append(min_hedge)
            [used.add(hedge) for hedge in hedge.loop_hedges]

    used.clear()
    # add inner component to faces
    for hedge in inner_hedges:
        Debugger.print_he(hedge, 'inner hedge')
        if hedge in used:
            continue
        left_hedges = [hedge]
        count = 0
        # while most left hedge of inner polygon does not have left neighbour with outer face
        # switch ot polygon of neighbour, search most left hedge and test whether it has neighbour with outer face
        # left_hedges contains one hedge of all holes belonging to current outer face or boundless face
        while not left_hedges[-1].left.face or not left_hedges[-1].left.face.outer:
            for n, h in enumerate(left_hedges[-1].left.loop_hedges):
                if h in inner_hedges:
                    left_hedges.append(h)
                    break
            count += n
            if count > len(hedges):
                Debugger.print_he(hedge, 'Hedge of hole cant find outer face')
                raise RecursionError('Hedge of hole cant find outer face')

        outer_face = left_hedges[-1].left.face
        for lh in left_hedges:
            outer_face.inners.append(lh)
            for h in lh.loop_hedges:
                used.add(h)
                h.face = outer_face

    return faces


def map_overlay(verts_a, faces_a, verts_b, faces_b):
    Debugger.clear(False)
    half_edges = merge_two_half_edges_list(create_half_edges(verts_a, faces_a), create_half_edges(verts_b, faces_b),
                                           len(verts_a))
    find_intersections(half_edges)
    faces = build_faces_list(half_edges)
    new_half_edges = []
    for face in faces:
        if face.outer and face.inners:
            new_half_edges.extend(make_monotone(face))
    if new_half_edges:
        half_edges.extend(new_half_edges)
        faces = rebuild_face_list(half_edges)
    return to_sv_mesh_from_faces(half_edges, faces)


def init_event_queue(event_queue, half_edges):
    EventPoint.max_index = -1
    EdgeSweepLine.global_event_point = None
    used = set()
    for hedge in half_edges:
        if hedge.twin in used:
            continue
        edge = EdgeSweepLine(hedge.origin, hedge.twin.origin, hedge.i, hedge.twin.i)
        edge.up_hedge, edge.low_hedge = (hedge, hedge.twin) if hedge.i == edge.up_i else (hedge.twin, hedge)
        up_node = event_queue.insert(EventPoint(edge.up_v, edge.up_i))
        up_node.key.up_edges += [edge]
        event_queue.insert(EventPoint(edge.low_v, edge.low_i))
        used.add(hedge)


def find_intersections(half_edges):
    """
    Initializing of searching intersection algorithm, read Computational Geometry by Mark de Berg
    :param verts: [(x, y) or (x, y, z), ...]
    :param edges: [(1, 5), ...]
    :return: [(3d dimensional intersection point, [edge1 involved in intersection, edge2, ...]), ...]
    """
    status = AVLTree()
    event_queue = AVLTree()
    test_event_point.clear()
    init_event_queue(event_queue, half_edges)
    out = []
    while event_queue:
        event_node = event_queue.find_smallest()
        intersection = handle_event_point(status, event_queue, event_node.key, half_edges)
        if intersection:
            out.append(intersection)
        event_queue.remove_node(event_node)
    test_intersections.clear()
    test_intersections.extend(out)
    return out


def handle_event_point(status, event_queue, event_point, half_edges):
    # Read Computational Geometry by Mark de Berg
    EdgeSweepLine.global_event_point = event_point
    test_event_point.append(event_point)
    out = []
    is_overlapping_points = False
    #Debugger.print_p(event_point, 'event_point')
    left_l_candidate, coincidence, right_l_candidate = get_coincidence_edges(status, event_point.co[x])
    c = [node for node in coincidence if node.key.is_c]
    l = [node for node in coincidence if not node.key.is_c]
    [status.remove_node(node) for node in c]
    [status.remove_node(node) for node in l]

    lc = []
    uc_edges = []
    for node in coincidence:
        edge = node.key
        #print('edge {}, up hedge {}, low hedge {}'.format(edge, edge.up_hedge, edge.low_hedge))
        if edge.is_c:
            # split edge on low und up sides
            low_edge = EdgeSweepLine(edge.up_v, event_point.co, edge.up_i, event_point.i)
            up_edge = EdgeSweepLine(event_point.co, edge.low_v, event_point.i, edge.low_i)
            # assign to new edges existing half edges of initial edge
            low_edge.up_hedge = edge.up_hedge
            up_edge.low_hedge = edge.low_hedge
            # copy pare of half edges from existing half edges and create appropriate links
            up_hedge_twin = HalfEdge(event_point.co, event_point.i, edge.low_hedge.face)
            up_hedge_twin.point = event_point
            up_hedge_twin.next = edge.low_hedge.next
            edge.low_hedge.next.last = up_hedge_twin
            low_hedge_twin = HalfEdge(event_point.co,event_point.i, edge.up_hedge.face)
            low_hedge_twin.point = event_point
            low_hedge_twin.next = edge.up_hedge.next
            edge.up_hedge.next.last = low_hedge_twin
            # add information about belonging to other faces only for new half edge of low edge
            # and delete outdate information about belonging for low half edge of up edge
            up_hedge_twin.in_faces = set(edge.low_hedge.in_faces)
            up_edge.low_hedge.in_faces = {up_edge.low_hedge.face} if up_edge.low_hedge.face else set()
            up_edge.low_hedge.left = None
            # apply new half edges to new edges
            low_edge.low_hedge = up_hedge_twin
            up_edge.up_hedge = low_hedge_twin
            # link half edges to each other
            low_edge.up_hedge.twin = low_edge.low_hedge
            low_edge.low_hedge.twin = low_edge.up_hedge
            up_edge.up_hedge.twin = up_edge.low_hedge
            up_edge.low_hedge.twin = up_edge.up_hedge
            half_edges.extend([up_hedge_twin, low_hedge_twin])
            #Debugger.print_he([up_hedge_twin, low_hedge_twin], 'new hedges')
            node.key = low_edge
            uc_edges.append(up_edge)
            #print('low edge {}, up_hedge {}, low hedge {}'.format(low_edge, low_edge.up_hedge, low_edge.low_hedge))
            #print('up edge {}, up hedge {}, low hedge {}'. format(up_edge, up_edge.up_hedge, up_edge.low_hedge))
        else:
            if edge.low_i != event_point.i:
                # check overlapping points
                edge.set_low_i(event_point.i)
                is_overlapping_points = True
        lc.append(node)
    #print('lc -', *lc)

    u = []
    for edge in event_point.up_edges + uc_edges:
        if edge.up_i != event_point.i:
            # check overlapping points
            edge.set_up_i(event_point.i)
            is_overlapping_points = True
        node = status.insert(edge)
        if edge != node.key:
            if edge.low_dot_length > node.key.low_dot_length:
                edge.coincidence.append(node.key)
                node.key = edge
            else:
                node.key.coincidence.append(edge)
        u.append(node)
    left_u_candidate, uc, right_u_candidate = get_coincidence_edges(status, event_point.co[x])
    left_neighbor = left_l_candidate if left_l_candidate else left_u_candidate
    right_neighbor = right_l_candidate if right_l_candidate else right_u_candidate
    #print('uc -', *uc)
    #print('left and right neighbors -', left_neighbor, right_neighbor)

    rotation_nodes = uc + lc[::-1]
    if left_neighbor:
        #Debugger.print_e(rotation_nodes[0].key, 'set left neighbour')
        rotation_nodes[0].key.outer_hedge.left = left_neighbor.up_hedge
    if c or is_overlapping_points:
        #print('uc lc -', *rotation_nodes)
        for i in range(len(rotation_nodes)):
            edge = rotation_nodes[i].key
            #print('edge -', edge)
            next_i = (i + 1) % len(rotation_nodes)
            last_i = (i - 1) % len(rotation_nodes)
            edge.outer_hedge.next = rotation_nodes[last_i].key.inner_hedge
            edge.inner_hedge.last = rotation_nodes[next_i].key.outer_hedge
            #print('outer hedge {}, next {}, last {}'.format(edge.outer_hedge, edge.outer_hedge.next, edge.outer_hedge.last))
            #print('inner hedge {}, next {}, last {}'.format(edge.inner_hedge, edge.inner_hedge.next, edge.inner_hedge.last))

        sub_status = set(rotation_nodes[-1].key.inner_hedge.in_faces)
        for i in range(len(rotation_nodes)):
            edge = rotation_nodes[i].key
            sub_status -= edge.outer_hedge.in_faces
            edge.outer_hedge.in_faces |= sub_status
            sub_status |= edge.inner_hedge.in_faces
            edge.inner_hedge.in_faces |= sub_status
            #print('Marck edge {}, outer_subd {}, inner_subd {}'.format(edge, edge.outer_hedge.subdivision, edge.inner_hedge.subdivision))
    else:
        sub_status = set(left_neighbor.up_hedge.in_faces) if left_neighbor else set()
        for node in uc:
            edge = node.key
            sub_status -= edge.outer_hedge.in_faces
            edge.outer_hedge.in_faces |= sub_status
            sub_status |= edge.inner_hedge.in_faces
            edge.inner_hedge.in_faces |= sub_status
            #print('Marck edge {}, outer_subd {}, inner_subd {}'.format(edge, edge.outer_hedge.subdivision, edge.inner_hedge.subdivision))

    if c or len(set([node.key.up_i for node in u] + [node.key.low_i for node in l])) > 1:
        #print('Intersection point -', event_point.co)
        point = tuple(list(event_point.co) + [0]) if len(event_point.co) == 2 else tuple(event_point.co)
        out.append(point)

    if not uc:
        if left_neighbor and right_neighbor:
            find_new_event(left_neighbor, right_neighbor, event_queue, event_point)
    else:
        leftmost_node = uc[0]
        rightmost_node = uc[-1]
        #print('leftmost_node', leftmost_node)
        #print('rightmost_node', rightmost_node)
        if left_neighbor:
            find_new_event(leftmost_node.key, left_neighbor, event_queue, event_point)
        if right_neighbor:
            find_new_event(rightmost_node.key, right_neighbor, event_queue, event_point)
    #print(status.out())
    if out:
        return out


def find_new_event(edge1, edge2, event_queue, event_point):
    # Read Computational Geometry by Mark de Berg
    #print('intersection test -', edge1, edge2)
    if is_edges_intersect_2d(edge1.v1, edge1.v2, edge2.v1, edge2.v2):
        intersection = intersect_lines_2d(edge1.v1, edge1.v2, edge2.v1, edge2.v2)
        if intersection:
            new_event_point = EventPoint(intersection + [0], None)
            if new_event_point > event_point:
                event_queue.insert(new_event_point)
                #print('past new event point {}: \n'.format(new_event_point.co), *event_queue.inorder_non_recursive())


# ======================== - partitioning to monotone pieces algorithm - ===========================
def rebuild_face_list(hedges):
    for hedge in hedges:
        if hedge.face:
            continue
        face = Face(0)
        face.outer = hedge
        for h in hedge.loop_hedges:
            h.face = face
    used = set()
    faces = []
    for hedge in hedges:
        if hedge not in used:
            Debugger.print_he(hedge, 'hedge with face - rebuild')
            Debugger.print_f(hedge.face, 'rebuild face')
            faces.append(hedge.face)
            [used.add(h) for h in hedge.loop_hedges]
    return faces


def build_points_list(hedges):
    # build list of points for partitioning algorithm
    # add links from hedges to point and from point to hedges
    # for normal working twins of hedges of face with holes also should be assigned to new points
    # point should have link to edge of polygon which is splitting to monotone pieces
    used = set()
    verts = []
    for hedge in hedges:
        if hedge in used:
            continue
        used.add(hedge)
        point = EventPoint(hedge.origin, len(verts))
        point.hedge = hedge
        hedge.point = point
        hedge.last.twin.point = point
        verts.append(point)
        for coin_hedge in hedge.ccw_hedges:
            used.add(coin_hedge)
    return verts


def insert_edge(up_p, low_p):

    up_hedge = HalfEdge(up_p.co, up_p.i)
    up_hedge.point = up_p
    low_hedge = HalfEdge(low_p.co, low_p.i)
    low_hedge.point = low_p
    up_hedge.twin = low_hedge
    low_hedge.twin = up_hedge

    up_ccw_hedges = []
    status = 1
    for h in up_p.hedge.ccw_hedges:
        #Debugger.print_he(h, 'append to up_ccw_hedges')
        up_ccw_hedges.append(h)
        if h.twin.face and h.twin.face == up_p.hedge.face:
            status -= 1
            break
    if status != 0:
        raise Exception('Hedge ({}) does not have neighbour with the same face'.format(up_p.hedge.i))

    if len(up_ccw_hedges) == 2:
        up_next = up_ccw_hedges[0]
    elif 2 < len(up_ccw_hedges) < 5:
        if up_ccw_hedges[0] > up_hedge:
            if ((up_ccw_hedges[2] < up_hedge and up_ccw_hedges[2] < up_ccw_hedges[0]) or
                    (up_ccw_hedges[2] > up_hedge and up_ccw_hedges[2] > up_ccw_hedges[0])):
                up_next = up_ccw_hedges[2]
            elif ((up_ccw_hedges[1] < up_hedge and up_ccw_hedges[1] < up_ccw_hedges[0]) or
                    (up_ccw_hedges[1] > up_hedge and up_ccw_hedges[1] > up_ccw_hedges[0])):
                up_next = up_ccw_hedges[1]
            else:
                up_next = up_ccw_hedges[0]
        else:
            up_next = up_ccw_hedges[1] if up_ccw_hedges[0] < up_ccw_hedges[1] < up_hedge else up_ccw_hedges[0]
    else:
        raise Exception('Unexpected number of half edges in point {}'.format(up_p))

    low_ccw_hedges = []
    status = 1
    for h in low_p.hedge.ccw_hedges:
        #Debugger.print_he(h, 'append to low_ccw_hedges')
        low_ccw_hedges.append(h)
        if h.twin.face and h.twin.face == low_p.hedge.face:
            status -= 1
            break
    if status != 0:
        raise Exception('Hedge ({}) does not have neighbour with the same face'.format(low_p.hedge.i))

    if len(low_ccw_hedges) == 2:
        low_next = low_ccw_hedges[0]
    elif len(low_ccw_hedges) == 3:
        if low_ccw_hedges[0] > low_hedge:
            if ((low_ccw_hedges[0] > low_ccw_hedges[1] < low_hedge) or
                    (low_ccw_hedges[0] < low_ccw_hedges[1] > low_hedge)):
                low_next = low_ccw_hedges[1]
            else:
                low_next = low_ccw_hedges[0]
        else:
            low_next = low_ccw_hedges[1] if low_ccw_hedges[0] < low_ccw_hedges[1] < low_hedge else low_ccw_hedges[0]
    else:
        raise Exception('Unexpected number of half edges in point {}'.format(low_p))
    up_hedge.last = up_next.last
    up_hedge.next = low_next
    low_hedge.next = up_next
    low_hedge.last = low_next.last
    up_next.last.next = up_hedge
    up_next.last = low_hedge
    low_next.last.next = low_hedge
    low_next.last = up_hedge
    up_hedge.in_faces = set(up_hedge.next.in_faces)
    low_hedge.in_faces = set(low_hedge.next.in_faces)

    return [up_hedge, low_hedge]


def make_monotone(face):
    EventPoint.monotone_current_face = face
    points = build_points_list(face.all_hedges)
    new_hedges = []
    status = AVLTree()
    q = sorted(points)[::-1]
    [Debugger.print_p(point, point.type) for point in q]
    while q:
        event_point = q.pop()
        EdgeSweepLine.global_event_point = event_point  # Don't comment this string!!!!!!!
        Debugger.print_p(event_point, 'event point - {}'.format(event_point.type))
        Debugger.print_he(event_point.hedge, 'hedge of event point')
        event_hedges = handle_functions[event_point.type](event_point, status)
        #Debugger.print_e(status.as_list(0))
        if event_hedges:
            Debugger.print_he(event_hedges, 'new hedges')
            new_hedges.extend(event_hedges)
    return new_hedges


def handle_start_point(point, status):
    edge = EdgeSweepLine(point.co, point.hedge.twin.point.co, point.i, point.hedge.twin.point.i)
    point.hedge.edge = edge
    point.hedge.twin.edge = edge
    edge.helper = point
    status.insert(edge)


def handle_end_point(point, status):
    status.remove(point.hedge.last.edge)
    helper = point.hedge.last.edge.helper
    if helper.type == 'merge':
        return insert_edge(helper, point)


def handle_split_point(point, status):
    left_node = status.find_nearest_left(point.co[x])
    #Debugger.print_e(left_node.key, 'nearest left edge')
    #Debugger.print_p(left_node.key.helper, 'split helper')
    new_hedges = insert_edge(left_node.key.helper, point)
    left_node.key.helper = point
    edge = EdgeSweepLine(point.co, point.hedge.twin.point.co, point.i, point.hedge.twin.point.i)
    point.hedge.edge = edge
    point.hedge.twin.edge = edge
    edge.helper = point
    status.insert(edge)
    return new_hedges


def handle_merge_point(point, status):
    right_helper = point.hedge.last.edge.helper
    new_hedges = []
    last_hedge = point.hedge.last
    if right_helper.type == 'merge':
        new_hedges.extend(insert_edge(right_helper, point))
    status.remove(last_hedge.edge)
    left_node = status.find_nearest_left(point.co[x])
    left_helper = left_node.key.helper
    if left_helper.type == 'merge':
        new_hedges.extend(insert_edge(left_helper, point))
    left_node.key.helper = point
    return new_hedges


def handle_regular_point(point, status):
    if point < point.hedge.twin.point:
        right_helper = point.hedge.last.edge.helper
        status.remove(point.hedge.last.edge)
        edge = EdgeSweepLine(point.co, point.hedge.twin.point.co, point.i, point.hedge.twin.point.i)
        point.hedge.edge = edge
        point.hedge.twin.edge = edge
        edge.helper = point
        Debugger.print_e(edge, 'insert edge')
        status.insert(edge)
        if right_helper.type == 'merge':
            return insert_edge(right_helper, point)
    else:
        left_node = status.find_nearest_left(point.co[x])
        left_helper = left_node.key.helper
        left_node.key.helper = point
        if left_helper.type == 'merge':
            return insert_edge(left_helper, point)


handle_functions = {'start': handle_start_point, 'end': handle_end_point, 'split': handle_split_point,
                    'merge': handle_merge_point, 'regular': handle_regular_point}


class MergeMesh2D(bpy.types.Node, SverchCustomTreeNode):
    """
    Triggers: like boolean
    Tip

    Tip
    """
    bl_idname = 'MergeMesh2D'
    bl_label = 'Merge mesh 2D'
    bl_icon = 'AUTOMERGE_ON'

    def update_sockets(self, context):
        links = {sock.name: [link.to_socket for link in sock.links] for sock in self.outputs}
        [self.outputs.remove(sock) for sock in self.outputs[2:]]
        new_socks = []
        if self.simple_mask:
            new_socks.append(self.outputs.new('StringsSocket', 'MaskA'))
            new_socks.append(self.outputs.new('StringsSocket', 'MaskB'))
        if self.index_mask:
            new_socks.append(self.outputs.new('StringsSocket', 'MaskIndexA'))
            new_socks.append(self.outputs.new('StringsSocket', 'MaskIndexB'))
        [[self.id_data.links.new(sock, link) for link in links[sock.name]] for sock in new_socks if sock.name in links]
        updateNode(self, context)

    simple_mask = bpy.props.BoolProperty(name='Simple mask', description='Switching between two type of masks',
                                         update=update_sockets, default=True)
    index_mask = bpy.props.BoolProperty(name="Index mask",
                                        description="Mask of output mesh represented indexes"
                                                    " of faces from mesh A and Mesh B", update=update_sockets)

    def draw_buttons_ext(self, context, layout):
        col = layout.column(align=True)
        col.prop(self, 'simple_mask', toggle=True)
        col.prop(self, 'index_mask', toggle=True)

    def sv_init(self, context):
        self.inputs.new('VerticesSocket', 'VertsA')
        self.inputs.new('StringsSocket', 'FacesA')
        self.inputs.new('VerticesSocket', 'VertsB')
        self.inputs.new('StringsSocket', 'FacesB')
        self.outputs.new('VerticesSocket', 'Verts')
        self.outputs.new('StringsSocket', 'Faces')
        self.outputs.new('StringsSocket', 'MaskA')
        self.outputs.new('StringsSocket', 'MaskB')

    def process(self):
        if not all([input.is_linked for input in self.inputs]):
            return None
        verts_a = self.inputs['VertsA'].sv_get()
        faces_a = self.inputs['FacesA'].sv_get()
        verts_b = self.inputs['VertsB'].sv_get()
        faces_b = self.inputs['FacesB'].sv_get()
        meshes = []
        for va, fa, vb, fb in zip(verts_a, faces_a, repeat_last(verts_b), repeat_last(faces_b)):
            meshes.append(map_overlay(va, fa, vb, fb))
        v, f, ma, mb, mia, mib = zip(*meshes)
        self.outputs['Verts'].sv_set(v)
        self.outputs['Faces'].sv_set(f)
        if self.simple_mask:
            self.outputs['MaskA'].sv_set(ma)
            self.outputs['MaskB'].sv_set(mb)
        if self.index_mask:
            self.outputs['MaskIndexA'].sv_set(mia)
            self.outputs['MaskIndexB'].sv_set(mib)


def register():
    bpy.utils.register_class(MergeMesh2D)


def unregister():
    bpy.utils.unregister_class(MergeMesh2D)
