from typing import Optional, Literal
from mcp_src.core import mcp_server, session
from pydantic import BaseModel, Field
from typing import List



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


