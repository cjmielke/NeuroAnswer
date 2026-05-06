import json
from typing import Optional, Literal
from mcp_src.core import mcp_server, session, cave_client
from pydantic import BaseModel, Field
from typing import List

import numpy as np
import pandas as pd

from mcp_src.scene import build_scene_from_neuron_selection


@mcp_server.tool()
def search_cells_in_view(x: float, y: float, z: float, radius_nm: float = 15000.0) -> str:
    """
    Finds excitatory cells within a specific radius of the user's current 3D coordinates.
    Input coordinates MUST be raw Neuroglancer voxels. The tool handles the nm conversion.
    """
    # 1. Access your loaded dataframe (adjust the variable name to match your code)
    # Assuming it's something like session.excitatory_cache
    df = session.excitatory_cache

    if df is None or df.empty:
        return json.dumps({"summary": "Error: Local connectome dataframe is not loaded."})

    voxel_res = cave_client.info.viewer_resolution()
    # Calculate distance in true nanometers using dynamic scaling
    distances = np.sqrt(
        ((df['pt_position_x'] - x) * voxel_res[0]) ** 2 +
        ((df['pt_position_y'] - y) * voxel_res[1]) ** 2 +
        ((df['pt_position_z'] - z) * voxel_res[2]) ** 2
    )

    # 4. Filter and sort
    mask = distances <= radius_nm
    nearby_cells = df[mask].copy()
    nearby_cells['distance_nm'] = distances[mask]
    nearby_cells = nearby_cells.sort_values('distance_nm')

    if nearby_cells.empty:
        return json.dumps({
            "summary": f"No excitatory cells found within {radius_nm}nm of voxel coordinates [{x}, {y}, {z}]."
        })

    # Build a clean markdown table for Claude to read
    # We cap it at 15 to save tokens
    results = nearby_cells.head(15)

    response = f"Found {len(nearby_cells)} cells within {radius_nm}nm. Here are the closest ones:\n\n"
    response += "| Root ID | M-Type | Distance (nm) |\n"
    response += "|---|---|---|\n"

    for _, row in results.iterrows():
        # Adjust 'pt_root_id' and 'cell_type' to match your dataframe columns
        response += f"| {row['pt_root_id']} | {row['cell_type']} | {row['distance_nm']:.1f} |\n"

    scene_url = build_scene_from_neuron_selection(results, x, y, z)
    return json.dumps(dict(summary=response, scene_url=scene_url))



class StructuralPopulationResult(BaseModel):
    """The strongly-typed output of a neuron population search."""
    mtype_searched: str = Field(description="The anatomical cell type that was queried.")
    neuron_root_ids: List[int] = Field(description="List of 64-bit integer IDs representing the discovered neurons. Pass these EXACT integers to downstream synapse tools.")
    memory_reference_id: str = Field(description="The pointer to the heavy 3D data. Pass this ONLY to the scene builder tool.")


@mcp_server.tool()
def search_excitatory_population(
        mtype: Literal[
            "L2a", "L2b", "L2c", "L3a", "L3b", "L4a", "L4b", "L4c",
            "L5a", "L5b", "L5ET", "L5NP", "L6tall-a", "L6tall-b",
            "L6tall-c", "L6short-a", "L6short-b", "PTC", "DTC", "ITC", "STC"
        ],
        limit: int = 5
) -> StructuralPopulationResult:
    """
    Finds structural IDs for EXCITATORY neurons.
    TRANSLATION MAP:
    - "Thick-tufted" / "Brainstem projecting" -> 'L5ET'
    - "Cortico-cortical" -> 'ITC'
    - "Motor output" -> 'PTC'
    - Or just pick a random layer code (e.g. 'L4a') if asked generally about a layer.

    Returns a memory_reference_id to be passed to visualization tools.
    """
    results = session.excitatory_cache[session.excitatory_cache['cell_type'] == mtype].head(limit)
    ref_id = session.store_df(results)

    if 'pt_root_id' in results.columns:
        root_ids = results['pt_root_id'].tolist()
    else:
        root_ids = results.index.tolist()

    # Return the strongly typed Pydantic model
    return StructuralPopulationResult(
        mtype_searched=mtype,
        neuron_root_ids=root_ids,
        memory_reference_id=ref_id
    )


