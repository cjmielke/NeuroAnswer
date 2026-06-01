import base64
import concurrent.futures
import logging
import os
import caveclient
import neuroglancer
from neuroglancer.credentials_provider import CredentialsProvider
from neuroglancer.default_credentials_manager import default_credentials_manager
from mcp.types import ImageContent
from mcp_src.core import mcp_server
from pydantic import Field

neuroglancer.set_server_bind_address(
    bind_address=os.environ.get('NEUROGLANCER_HOST', '0.0.0.0'),
    bind_port=int(os.environ.get('NEUROGLANCER_PORT', 8675)),
)

class MiddleAuthProvider(CredentialsProvider):
    def __init__(self, token: str):
        super().__init__()
        self._token = token

    def get_new(self):
        f: concurrent.futures.Future = concurrent.futures.Future()
        f.set_result({"tokenType": "Bearer", "accessToken": self._token})
        return f

default_credentials_manager.register(
    "middleauthapp",
    lambda _origin: MiddleAuthProvider(os.environ["CAVE_TOKEN"]),
)

viewer = neuroglancer.Viewer(
    token=os.environ.get('NEUROGLANCER_TOKEN', 'neuroanswer'),
    allow_credentials=True,
)


def on_select(action_state):
    logging.info(action_state.to_json())  # see what fires
def on_state_change():
  state = viewer.state.to_json()
  logging.info(state)  # see if selected segment appears anywhere on click

viewer.shared_state.add_changed_callback(on_state_change)
viewer.actions.add('select', on_select)


ds = 'minnie65_public'
client = caveclient.CAVEclient(ds, auth_token=os.environ['CAVE_TOKEN'])
em_source = client.info.image_source()
seg_source = client.info.segmentation_source()
# Ensure middleauth prefix is present for the graphene part
if 'graphene://https://' in seg_source:
    seg_source = seg_source.replace('graphene://https://', 'graphene://middleauth+https://')

logging.info(f'Seg_source : {seg_source}     EM_source: {em_source}')

@mcp_server.tool()
def get_neuroglancer_link():
    """Call this took to get the link to the NeuroAnswer server, and *provide it to the server*"""
    return viewer.get_viewer_url()

@mcp_server.tool()
def reset_neuroglancer_view():
    """ Resets all layers and loads the minnie connectome data. Two layers are added by default : EM_Background and  3D_Meshes, with no segmentations loaded"""

    # load minnie dataset to get started
    with viewer.txn() as s:
        s.layers['EM_Background'] = neuroglancer.ImageLayer(source=em_source)
        s.layers['3D_Meshes'] = neuroglancer.SegmentationLayer(source=seg_source)
        s.position = [962560, 831488, 854400]
        s.dimensions = neuroglancer.CoordinateSpace(
            names=['x', 'y', 'z'], units='nm', scales=[1, 1, 1]
        )
        s.layout = 'xy-3d'
        s.show_slices = False

reset_neuroglancer_view()       # run first at startup to set the stage

@mcp_server.tool()
def clear_neuroglancer_layers():
    """Remove all layers you've added to the NeuroGlancer viewer, leaving just the EM_Background and 3D_Meshes layers"""
    with viewer.txn() as s:
        to_remove = [k for k in s.layers.keys() if k not in ('EM_Background', '3D_Meshes')]
        for k in to_remove:
            del s.layers[k]
        s.layers['3D_Meshes'].segments = set()


# start = time.time()
# viewer = (
#     statebuilder.ViewerState(dimensions=[1, 1, 1], position=[962560, 831488, 854400], infer_coordinates=False)
#     .add_image_layer(name='EM_Background', source=em_source)
#     .add_segmentation_layer(name='3D_Meshes', source=seg_source, segments=[])
# )
# print(f'took {time.time() - start} seconds to make viewer')
# start = time.time()
# scene_url = viewer.to_url(target_url='https://neuroglancer-demo.appspot.com/')


logging.info(f'Starting NeuroGlancer server at : {viewer.get_viewer_url()}')

'''
viewer.state.to_json()
Out[18]: 
{'dimensions': {'x': [1e-09, 'm'], 'y': [1e-09, 'm'], 'z': [1e-09, 'm']},
 'position': [962560, 831488, 854400],
 'crossSectionScale': 1,
 'projectionOrientation': [0.2036268413066864,
  0.1348494291305542,
  0.09058087319135666,
  -0.9654775261878967],
 'projectionScale': 2097152,
 'layers': [{'type': 'image',
   'source': 'precomputed://https://bossdb-open-data.s3.amazonaws.com/iarpa_microns/minnie/minnie65/em',
   'tab': 'source',
   'name': 'EM_Background'},
  {'type': 'segmentation',
   'source': 'graphene://middleauth+https://minnie.microns-daf.com/segmentation/table/minnie65_public',
   'tab': 'source',
   'segments': ['864691135750050089'],
   'name': '3D_Meshes'}],
 'showSlices': False,
 'layout': 'xy-3d'}
'''


@mcp_server.tool()
def get_neuroglancer_viewer_state():
    coords = viewer.state.voxel_coordinates

    # for now, could just lazily return the json - but a pydantic class might be better in the future
    return viewer.state.to_json()

@mcp_server.tool()
def get_neuroglancer_screenshot():
    """Call this tool to see exactly what the user can see in the current NeuroGlancer viewport"""
    future = concurrent.futures.ThreadPoolExecutor(max_workers=1).submit(viewer.screenshot)
    try:
        action_state = future.result(timeout=15)
    except concurrent.futures.TimeoutError:
        return "Screenshot timed out — open the Neuroglancer viewer in a browser tab first."
    return [ImageContent(type="image", data=base64.b64encode(action_state.screenshot.image).decode(), mimeType="image/png")]


@mcp_server.tool()
def show_neuron_segmentation(
    neuron_root_id: int = Field(..., description="MUST be a 64-bit integer ID from the neuron_root_ids list. Do NOT pass a memory_reference_id here."),
    layer_name: str = Field('Layer_Name', description="The layer name, shown in the neuroglancer view. You can use this to provide a custom concise name related to the input query")
) -> str:

    with viewer.txn() as s:
        s.layers[layer_name] = neuroglancer.SegmentationLayer(
            source=seg_source,
            segments=[neuron_root_id]
        )

    return 'success!'


@mcp_server.tool()
def zoom_neuroglancer(
        factor: float = Field(description="Scale factor. For example, 2 will double the current projectionScale of the 3D view and the cross_section_scale of the 2D EM view")
):
    with viewer.txn() as s:
        s.cross_section_scale = factor * viewer.state.cross_section_scale
        s.projection_scale = factor * viewer.state.projection_scale



# # Add annotations:
# with viewer.txn() as s:
#     s.layers['synapses'] = neuroglancer.AnnotationLayer()
#     # add point annotations for synapse locations

@mcp_server.tool()
def change_camera_position(
        x: int = Field(..., description="Position in nanometers along the X axis"),
        y: int = Field(..., description="Position in nanometers along the Y axis"),
        z: int = Field(..., description="Position in nanometers along the Z axis"),
) -> None:
    with viewer.txn() as s:
        s.position = [x, y, z]




'''
  reset_camera_orientation():
  with viewer.txn() as s:
      s.projection_orientation = None   # try this first — may snap to default
      # if not: s.projection_orientation = [0, 0, 0, 1]  # identity quaternion

  set_layer_visibility(layer_name, visible):
  with viewer.txn() as s:
      s.layers[layer_name].visible = visible
      
  add_point_annotation(x, y, z, label) — coordinates in nm same as position:
  with viewer.txn() as s:
      if 'annotations' not in s.layers:
          s.layers['annotations'] = neuroglancer.AnnotationLayer()
      s.layers['annotations'].annotations.append(
          neuroglancer.PointAnnotation(id=label, point=[x, y, z])
      )   
      
  show_synapses(root_id, direction) — the coordinate conversion is the tricky part (CAVE stores at 8×8×40nm voxels, viewer is in nm):
  syn = client.materialize.synapse_query(pre_ids=[root_id])  # or post_ids
  pts = syn['ctr_pt_position'].tolist()  # [[x,y,z], ...] in CAVE voxels
  with viewer.txn() as s:
      s.layers['synapses'] = neuroglancer.AnnotationLayer(
          annotations=[
              neuroglancer.PointAnnotation(id=str(i), point=[p[0]*8, p[1]*8, p[2]*40])
              for i, p in enumerate(pts)
          ]   
      )   
      
  focus_on_neuron(root_id) — nucleus table gives a reliable centroid:
  nucs = client.materialize.query_table('nucleus_detection_v0',
                                         filter_equal_dict={'pt_root_id': root_id})
  pt = nucs.iloc[0]['pt_position']  # CAVE voxels
  with viewer.txn() as s:
      s.layers[f'neuron_{root_id}'] = neuroglancer.SegmentationLayer(
          source=seg_source, segments=[root_id])
      s.position = [pt[0]*8, pt[1]*8, pt[2]*40]
      
  get_cell_type(root_id):
  result = client.materialize.query_table(
      'aibs_metamorph_nuc_metamorph_cells_v661',
      filter_equal_dict={'pt_root_id': root_id}
  )
  return result[['pt_root_id', 'cell_type']].iloc[0].to_dict()

  get_segment_at_position(x_nm, y_nm, z_nm) — reverse lookup from nm → root ID:
  vox = [x_nm // 8, y_nm // 8, z_nm // 40]
  root_id = client.chunkedgraph.get_root_id(
      client.chunkedgraph.get_atomic_id_from_coord(*vox, volume_is_sharded=True)
  )



'''

