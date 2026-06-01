import logging
import time
from nglui import statebuilder
from nglui.statebuilder import PointAnnotation, LineAnnotation
from pydantic import Field
from mcp_src.core import mcp_server, cave_client, session
import pandas as pd
from typing import Literal
import json

@mcp_server.tool()
def get_downstream_synapses(
    neuron_root_id: int = Field(..., description="MUST be a 64-bit integer ID from the neuron_root_ids list. Do NOT pass a memory_reference_id here."),
    limit: int = 5,
    layer_name: str = Field('Output_Synapses', description="The layer name, shown in the neuroglancer view. You can use this to provide a custom concise name related to the input query")
) -> str:
    """
    Queries the structural graph for downstream targets of a specific cell ID.
    Returns a memory_reference_id to be passed to visualization tools.
    """
    df_synapses = cave_client.materialize.query_table(
        'synapses_pni_2',
        filter_equal_dict={'pre_pt_root_id': neuron_root_id},
        desired_resolution=[1, 1, 1]
    )
    if df_synapses.empty:
        return json.dumps({"summary": f"No outgoing synapses found for {neuron_root_id}."})
    logging.info(f'Got {len(df_synapses)} rows from pre_pt_root_id')


    # Get the strongest structural targets (ignoring ID 0)
    target_counts = df_synapses[df_synapses['post_pt_root_id'] != 0].groupby('post_pt_root_id').size()
    top_targets = target_counts.sort_values(ascending=False).head(limit)

    # Format into a dataframe to store in our session
    results_df = pd.DataFrame({
        'pt_root_id': top_targets.index,
        'synapse_count': top_targets.values
    })

    ref_id = session.store_df(results_df)

    # We return the raw IDs to Claude's context here so it can speak about them,
    # but we also return the ref_id for the visualizer.
    #return (f"Found strongest targets. IDs: {top_targets.index.tolist()}. "
    #        f"Data stored for visualization at reference: {ref_id}")


    # 2. Sort by size (if available) and limit the count
    # URLs have a maximum length, so we cannot send 5,000 synapses to the frontend.
    if 'size' in df_synapses.columns:
        df_synapses = df_synapses.sort_values('size', ascending=False)

    synapse_subset = df_synapses.head(limit)


    # 3. Build Neuroglancer Point Annotations
    annotations = []
    post_synaptic_targets = set()


    for _, row in synapse_subset.iterrows():
        # CAVE usually returns the coordinates as a single array: [x, y, z] in voxels
        pos = row['ctr_pt_position']
        pre_pos = row['pre_pt_position']
        post_pos = row['post_pt_position']

        post_synaptic_targets.add(str(row['post_pt_root_id']))      # Track the downstream neurons we are talking to

        # FIXME - inherit voxel sizes from dataset automatically
        pointAnno = PointAnnotation(
            id=str(row['id']),                                # The unique synapse ID
            point=pos,
            #point=[int(pos[0]), int(pos[1])*4, int(pos[2])*40],    # Your coordinates
            #point=[int(pos[i])*voxel_res[i] for i in range(3)],
            description=f"Target: {row['post_pt_root_id']}"   # The text label (optional)
        )
        annotations.append(pointAnno)

        lineAnno = LineAnnotation(
            id=str(row['id']),
            # Start inside the axon
            pointA=[int(pre_pos[0]), int(pre_pos[1]), int(pre_pos[2])],
            # End inside the dendrite
            pointB=[int(post_pos[0]), int(post_pos[1]), int(post_pos[2])],
            # Inject the synaptic weight into the UI hover label
            description=f"Weight: {row['size']} | Target: {row['post_pt_root_id']}"
        )
        annotations.append(lineAnno)

    seg_source = cave_client.info.segmentation_source()

    viewer = (
        statebuilder.ViewerState(dimensions=[1, 1, 1])
        .add_segmentation_layer(name='3D_Meshes', source=seg_source, segments=[neuron_root_id])
        .add_annotation_layer(name=layer_name, annotations=annotations, color='#ff0000')
    )
    state = viewer.to_dict()

    summary = (
        f"Found {len(df_synapses)} total downstream synapses for {neuron_root_id}. "
        f"I've mapped the top {limit} largest synapses to your view in red. "
        f"This neuron connects to {len(post_synaptic_targets)} unique downstream targets in this sample."
    )

    return json.dumps({
        "summary": summary,
        "layers": state.get("layers", []),
        "suggested_position": state.get("position"),
    })








#@mcp_server.tool()
def get_targeted_compartments(
        post_root_id: int,
        compartment: Literal['soma', 'shaft', 'spine'] = 'soma'
) -> str:
    """
    Finds all synapses that target a specific compartment of a postsynaptic cell.
    Use this to find the inhibitory basket (soma targets) or excitatory inputs (spine targets).

    Returns a memory_reference_id containing the 3D coordinates of those synapses.
    """
    logging.info(f"Fetching synapses targeting cell {post_root_id}...")

    # 1. Get all synapses where our cell is the receiver (post-synaptic)
    df_synapses = cave_client.materialize.query_table(
        'synapses_pni_2',
        filter_equal_dict={'post_pt_root_id': post_root_id}
    )

    if df_synapses.empty:
        return f"No synapses found targeting cell {post_root_id}."

    synapse_ids = df_synapses['id'].tolist()

    logging.info(f"Found {len(synapse_ids)} synapses. Fetching compartment predictions...")

    # 2. Surgically query the massive prediction table using ONLY our specific synapse IDs
    df_predictions = cave_client.materialize.query_table(
        'synapse_target_predictions_ssa_v2',
        filter_in_dict={'id': synapse_ids}  # This prevents the DB from crashing!
    )

    # 3. Join the tables on the shared 'id' column
    merged = pd.merge(df_synapses, df_predictions, on='id')

    # 4. Filter for the compartment Claude asked for
    # (Assuming the prediction column is named 'target_structure' or similar;
    # you may need to check the exact column name via standard df.columns if it fails)
    filtered = merged[merged['target_structure'] == compartment]

    # 5. Standardize the dataframe for the Scene Builder
    # The synapse table stores coordinates in 'ctr_pt_position', but our scene builder
    # expects 'pt_position'. We rename it here so the scene builder stays generic.
    filtered = filtered.rename(columns={'ctr_pt_position': 'pt_position'})

    # We also ensure 'pt_root_id' is set to the main cell so the mesh turns on
    filtered['pt_root_id'] = post_root_id

    # 6. Store and return the pointer
    ref_id = session.store_df(filtered)

    return f"Success. Found {len(filtered)} synapses targeting the {compartment}. Data stored at reference: {ref_id}"


