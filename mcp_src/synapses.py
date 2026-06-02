import logging
import pandas as pd
from typing import Literal
from pydantic import Field
import neuroglancer

from mcp_src.core import mcp_server, cave_client


# ---------------------------------------------------------------------------
# Data functions — plain Python, no MCP, importable into the analysis sandbox
# ---------------------------------------------------------------------------

def get_downstream_synapses_df(root_id: int, limit: int = None) -> pd.DataFrame:
    """Fetch outgoing synapses for a neuron. Coordinates returned in nm."""
    df = cave_client.materialize.query_table(
        'synapses_pni_2',
        filter_equal_dict={'pre_pt_root_id': root_id},
        desired_resolution=[1, 1, 1]
    )
    if limit:
        df = df.head(limit)
    return df


def get_upstream_synapses_df(root_id: int, limit: int = None) -> pd.DataFrame:
    """Fetch incoming synapses for a neuron. Coordinates returned in nm."""
    df = cave_client.materialize.query_table(
        'synapses_pni_2',
        filter_equal_dict={'post_pt_root_id': root_id},
        desired_resolution=[1, 1, 1]
    )
    if limit:
        df = df.head(limit)
    return df


def get_synapse_partners_df(
    root_id: int,
    direction: Literal['pre', 'post'] = 'pre',
    limit: int = 10
) -> pd.DataFrame:
    """Top synaptic partners ranked by synapse count. direction='pre' → downstream."""
    src_col = 'pre_pt_root_id' if direction == 'pre' else 'post_pt_root_id'
    partner_col = 'post_pt_root_id' if direction == 'pre' else 'pre_pt_root_id'
    df = cave_client.materialize.query_table(
        'synapses_pni_2',
        filter_equal_dict={src_col: root_id},
        desired_resolution=[1, 1, 1]
    )
    return (
        df[df[partner_col] != 0]
        .groupby(partner_col)
        .size()
        .sort_values(ascending=False)
        .head(limit)
        .rename('synapse_count')
        .reset_index()
        .rename(columns={partner_col: 'pt_root_id'})
    )


def get_targeted_compartments_df(
    post_root_id: int,
    compartment: Literal['soma', 'shaft', 'spine'] = 'soma'
) -> pd.DataFrame:
    """Synapses onto a specific compartment of a postsynaptic cell."""
    df_synapses = cave_client.materialize.query_table(
        'synapses_pni_2',
        filter_equal_dict={'post_pt_root_id': post_root_id}
    )
    if df_synapses.empty:
        return df_synapses
    df_predictions = cave_client.materialize.query_table(
        'synapse_target_predictions_ssa_v2',
        filter_in_dict={'id': df_synapses['id'].tolist()}
    )
    merged = pd.merge(df_synapses, df_predictions, on='id')
    return merged[merged['target_structure'] == compartment]


# ---------------------------------------------------------------------------
# Viewer functions — mutate the neuroglancer viewer directly
# ---------------------------------------------------------------------------

def show_synapse_annotations(df: pd.DataFrame, layer_name: str = 'Synapses'):
    """Render a synapse dataframe as point annotations in the neuroglancer viewer."""
    from mcp_src.ng import viewer  # late import avoids circular import at module load
    annotations = []
    for _, row in df.iterrows():
        pos = row['ctr_pt_position']
        point = pos.tolist() if hasattr(pos, 'tolist') else list(pos)
        annotations.append(neuroglancer.PointAnnotation(
            id=str(row['id']),
            point=point,
            description=f"{row.get('pre_pt_root_id', '?')} → {row.get('post_pt_root_id', '?')} | size: {row.get('size', '?')}"
        ))
    with viewer.txn() as s:
        s.layers[layer_name] = neuroglancer.AnnotationLayer(annotations=annotations)
    logging.info(f"Rendered {len(annotations)} synapse annotations in layer '{layer_name}'")


# ---------------------------------------------------------------------------
# MCP tools — thin wrappers over the functions above
# ---------------------------------------------------------------------------

@mcp_server.tool()
def get_downstream_synapses(
    root_id: int = Field(..., description="64-bit neuron root ID"),
    limit: int = Field(200, description="Max synapses to render in viewer"),
    layer_name: str = Field('Output_Synapses', description="Layer name shown in the viewer"),
) -> str:
    """Show the outgoing synapses of a neuron as point annotations in the viewer."""
    df = get_downstream_synapses_df(root_id)
    if df.empty:
        return f"No outgoing synapses found for {root_id}."
    if 'size' in df.columns:
        df = df.sort_values('size', ascending=False)
    show_synapse_annotations(df.head(limit), layer_name)
    return (
        f"Found {len(df)} outgoing synapses from {root_id} "
        f"to {df['post_pt_root_id'].nunique()} unique partners. "
        f"Showing top {min(limit, len(df))} by size in '{layer_name}'."
    )


@mcp_server.tool()
def get_upstream_synapses(
    root_id: int = Field(..., description="64-bit neuron root ID"),
    limit: int = Field(200, description="Max synapses to render in viewer"),
    layer_name: str = Field('Input_Synapses', description="Layer name shown in the viewer"),
) -> str:
    """Show the incoming synapses of a neuron as point annotations in the viewer."""
    df = get_upstream_synapses_df(root_id)
    if df.empty:
        return f"No incoming synapses found for {root_id}."
    if 'size' in df.columns:
        df = df.sort_values('size', ascending=False)
    show_synapse_annotations(df.head(limit), layer_name)
    return (
        f"Found {len(df)} incoming synapses to {root_id} "
        f"from {df['pre_pt_root_id'].nunique()} unique partners. "
        f"Showing top {min(limit, len(df))} by size in '{layer_name}'."
    )


@mcp_server.tool()
def get_synapse_partners(
    root_id: int = Field(..., description="64-bit neuron root ID"),
    direction: Literal['pre', 'post'] = Field('pre', description="'pre' = downstream targets, 'post' = upstream inputs"),
    limit: int = Field(10, description="Number of top partners to return"),
) -> str:
    """Return the top synaptic partners of a neuron ranked by synapse count."""
    df = get_synapse_partners_df(root_id, direction, limit)
    if df.empty:
        return f"No synaptic partners found for {root_id}."
    label = "downstream targets" if direction == 'pre' else "upstream inputs"
    rows = "\n".join(f"  {r['pt_root_id']}: {r['synapse_count']} synapses" for _, r in df.iterrows())
    return f"Top {label} of {root_id}:\n{rows}"