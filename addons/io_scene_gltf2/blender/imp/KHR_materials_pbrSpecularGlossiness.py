# Copyright 2018-2021 The glTF-Blender-IO authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import bpy
from ...io.com.gltf2_io import TextureInfo
from .pbrMetallicRoughness import \
    base_color, emission, normal, occlusion, make_settings_node
from .material_utils import color_factor_and_texture # Keep this for specular color
from .texture import texture # Keep this for texture node creation
# Removed imports for get_source, BlenderImage, np as make_roughness_image is removed

# --- Function removed ---
# def make_roughness_image(mh, glossiness_factor, tex_info):
#    """
#    This function is no longer needed as roughness is calculated via nodes.
#    """
#    pass


def glossiness(mh, ext, location, roughness_socket):
    # Glossiness = glossinessFactor * specularGlossinessTexture.alpha
    # Roughness = 1 - Glossiness

    factor = ext.get('glossinessFactor', 1.0) # Default to 1.0 float
    tex_info_dict = ext.get('specularGlossinessTexture')
    tex_info = TextureInfo.from_dict(tex_info_dict) if tex_info_dict else None

    x, y = location

    # Handle case with no texture
    if tex_info is None:
        # Roughness = 1 - factor
        roughness_socket.default_value = max(0.0, min(1.0, 1.0 - factor)) # Clamp result
        return

    # --- Node-based Roughness Calculation ---

    # 1. Create the Subtract Node (1 - Glossiness)
    subtract_node = mh.nodes.new('ShaderNodeMath')
    subtract_node.label = '1 - Glossiness'
    subtract_node.operation = 'SUBTRACT'
    subtract_node.location = x - 140, y - 50 # Place slightly offset from texture
    subtract_node.inputs[0].default_value = 1.0
    subtract_node.use_clamp = True # Ensure output is 0-1
    # Connect the final result to the PBR roughness input
    mh.links.new(subtract_node.outputs[0], roughness_socket)
    # The second input of Subtract node needs the Glossiness value
    glossiness_input_socket = subtract_node.inputs[1]

    current_gloss_value_socket = None # This will point to the socket providing the glossiness value

    # 2. Create Multiply Node if factor is not 1.0 (Glossiness = Factor * Texture.alpha)
    if factor != 1.0:
        multiply_node = mh.nodes.new('ShaderNodeMath')
        multiply_node.label = 'Glossiness Factor'
        multiply_node.operation = 'MULTIPLY'
        multiply_node.location = x - 340, y # Place before Subtract node
        multiply_node.inputs[1].default_value = factor
        multiply_node.use_clamp = True # Clamp glossiness 0-1 before subtraction
        # Connect Multiply output to Subtract input
        mh.links.new(multiply_node.outputs[0], glossiness_input_socket)
        # The input for the texture alpha is now the first input of the Multiply node
        current_gloss_value_socket = multiply_node.inputs[0]
        x_texture = x - 540 # Adjust location for the texture node
    else:
        # No multiplication needed, connect texture alpha directly to Subtract input
        current_gloss_value_socket = glossiness_input_socket
        x_texture = x - 340 # Adjust location for the texture node

    # 3. Create the Texture Node for SpecularGlossinessTexture
    texture(
        mh,
        tex_info=tex_info,
        location=(x_texture, y),
        label='SPECULAR GLOSSINESS',
        # Use alpha channel for glossiness value (scalar data)
        color_socket=None,
        alpha_socket=current_gloss_value_socket, # Connect to Multiply input or Subtract input
        is_data=True # Alpha channel is linear scalar data
    )


def pbr_specular_glossiness(mh):
    """Creates node tree for pbrSpecularGlossiness materials."""
    ext = mh.get_ext('KHR_materials_pbrSpecularGlossiness', {})

    pbr_node = mh.nodes.new('ShaderNodeBsdfPrincipled')
    out_node = mh.nodes.new('ShaderNodeOutputMaterial')
    pbr_node.location = 10, 300
    out_node.location = 300, 300
    mh.links.new(pbr_node.outputs[0], out_node.inputs[0])

    locs = calc_locations(mh, ext) # Use the same location calculation

    base_color(
        mh,
        is_diffuse=True,
        location=locs['diffuse'],
        color_socket=pbr_node.inputs['Base Color'],
        alpha_socket=pbr_node.inputs['Alpha'],
    )

    emission(
        mh,
        location=locs['emission'],
        color_socket=pbr_node.inputs['Emission Color'],
        strength_socket=pbr_node.inputs['Emission Strength'],
    )

    normal(
        mh,
        location=locs['normal'],
        normal_socket=pbr_node.inputs['Normal'],
    )

    if mh.pymat.occlusion_texture is not None:
        if mh.settings_node is None:
            mh.settings_node = make_settings_node(mh)
            mh.settings_node.location = 10, 425
            mh.settings_node.width = 240
        occlusion(
            mh,
            location=locs['occlusion'],
            occlusion_socket=mh.settings_node.inputs['Occlusion'],
        )

    # The F0 color is the specular tint modulated by
    # ((1-IOR)/(1+IOR))^2. Setting IOR=1000 makes this factor
    # approximately 1.
    pbr_node.inputs['IOR'].default_value = 1000

    # Specular Color (Uses color_factor_and_texture - unchanged)
    color_factor_and_texture(
        mh,
        location=locs['specular'],
        label='Specular Color',
        socket=pbr_node.inputs['Specular Tint'],
        factor=ext.get('specularFactor', [1, 1, 1]),
        tex_info=ext.get('specularGlossinessTexture'), # Still uses the same texture info
    )

    # Glossiness (Calls the modified function)
    glossiness(
        mh,
        ext,
        location=locs['glossiness'],
        roughness_socket=pbr_node.inputs['Roughness'],
    )


def calc_locations(mh, ext):
    """Calculate locations to place each bit of the node graph at."""
    # Lay the blocks out top-to-bottom, aligned on the right
    # This calculation remains the same, as it positions the start of each "group"
    x = -200
    y = 0
    height = 460  # height of each block
    locs = {}

    locs['occlusion'] = (x, y)
    if mh.pymat.occlusion_texture is not None:
        y -= height

    locs['diffuse'] = (x, y)
    if 'diffuseTexture' in ext or mh.vertex_color:
        y -= height

    # Glossiness block might be slightly wider now with extra math nodes,
    # but the starting location logic is fine.
    locs['glossiness'] = (x, y)
    if 'specularGlossinessTexture' in ext:
         # Height is still allocated if the texture exists, regardless of factor
        y -= height

    locs['normal'] = (x, y)
    if mh.pymat.normal_texture is not None:
        y -= height

    # Specular color block uses the same texture, allocate space if texture exists
    locs['specular'] = (x, y)
    if 'specularGlossinessTexture' in ext:
        y -= height

    locs['emission'] = (x, y)
    if mh.needs_emissive(): # Use MaterialHelper method
        y -= height

    # Center things
    total_height = -y
    y_offset = total_height / 2 - 20 if total_height > 0 else 0 # Avoid negative offset if only one block
    for key in locs:
        cur_x, cur_y = locs[key]
        locs[key] = (cur_x, cur_y + y_offset)

    return locs
