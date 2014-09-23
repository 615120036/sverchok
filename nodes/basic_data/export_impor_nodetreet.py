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

import json
import pprint
import os
import re

import bpy
from bpy.types import EnumProperty

from node_tree import SverchCustomTreeNode


def find_enumerators(node):
    ignored_enums = ['bl_icon', 'bl_static_type', 'type']
    node_props = node.bl_rna.properties[:]
    f = filter(lambda p: isinstance(p, EnumProperty), node_props)
    return [p.identifier for p in f if not p.identifier in ignored_enums]


def compile_socket(link):
    return (link.from_node.name,
            link.from_socket.name,
            link.to_node.name,
            link.to_socket.name)

def write_json(layout_dict, destination_path):
    m = json.dumps(layout_dict, sort_keys=True, indent=2)
    # optional post processing step
    post_processing = False
    if post_processing:
        flatten = lambda match: r' {}'.format(match.group(1), m)
        m = re.sub(r'\s\s+(\d+)', flatten , m)

    with open(destination_path, 'w') as node_tree:
        node_tree.writelines(m)


def export_tree(ng, destination_path):
    nodes = ng.nodes
    layout_dict = {}
    nodes_dict = {}

    ''' get nodes and params '''

    for node in nodes:
        node_dict = {}
        node_items = {}
        node_enums = find_enumerators(node)
        
        for k, v in node.items():
            if isinstance(v, (float, int, str)):
                node_items[k] = v
            else:
                node_items[k] = v[:]

            if k in node_enums:
                v = getattr(node, k)
                node_items[k] = v

        node_dict['params'] = node_items
        node_dict['location'] = node.location[:]
        node_dict['bl_idname'] = node.bl_idname
        node_dict['height'] = node.height
        node_dict['width'] = node.width
        node_dict['label'] = node.label
        node_dict['hide'] = node.hide
        node_dict['color'] = node.color[:]
        nodes_dict[node.name] = node_dict

    layout_dict['nodes'] = nodes_dict

    ''' get connections '''
        
    links = (compile_socket(l) for l in ng.links)
    connections_dict = {idx: link for idx, link in enumerate(links)}
    layout_dict['connections'] = connections_dict

    write_json(layout_dict, destination_path)

        
def import_tree(ng, fullpath):

    nodes = ng.nodes

    def resolve_socket(from_node, from_socket, to_node, to_socket):
        return (ng.nodes[from_node].outputs[from_socket], 
                ng.nodes[to_node].inputs[to_socket])

    with open(fullpath) as fp:
        nodes_json = json.load(fp)

    ''' first create all nodes. '''

    nodes_to_import = nodes_json['nodes']
    for n in sorted(nodes_to_import):
        node_ref = nodes_to_import[n]

        bl_idname = node_ref['bl_idname']
        node = nodes.new(bl_idname)
        
        if not (node.name == n):
           node.name = n

        params = node_ref['params']
        for p in params:
            val = params[p]
            setattr(node, p, val)
            
        node.location = node_ref['location']
        node.height = node_ref['height']
        node.width = node_ref['width']
        node.label = node_ref['label']
        node.hide = node_ref['hide']
        node.color = node_ref['color']
        
    ''' now connect them '''
    
    connections = nodes_json['connections']
    for idx, link in connections.items():
        ng.links.new(*resolve_socket(*link))


class SvImportExportNodeTree(bpy.types.Node, SverchCustomTreeNode):
    ''' SvImportExportNodeTree '''
    bl_idname = 'SvImportExportNodeTree'
    bl_label = 'Sv Import Export NodeTree'
    bl_icon = 'OUTLINER_OB_EMPTY'

    def init(self, context):
        pass

    def draw_buttons(self, context, layout):
        pass

    def update(self):
        pass

    def update_socket(self, context):
        self.update()


def register():
    bpy.utils.register_class(SvImportExportNodeTree)


def unregister():
    bpy.utils.unregister_class(SvImportExportNodeTree)
