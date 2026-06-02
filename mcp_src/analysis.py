import base64
import io
import sys
from typing import List
from mcp.types import TextContent, ImageContent
from matplotlib import pyplot as plt
import seaborn as sns
plt.rcParams['svg.fonttype'] = 'none'

from mcp_src.core import mcp_server, cave_client, session
from mcp_src.synapses import (
    get_downstream_synapses_df,
    get_upstream_synapses_df,
    get_synapse_partners_df,
    get_targeted_compartments_df,
    show_synapse_annotations,
)
import pandas as pd
import numpy as np
from PIL import Image as PILImage

from loguru import logger
logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <white>{message}</white>")

SVG_SIZE_LIMIT = 500 * 1024  # 500 KB


def fig_to_image_content(fig) -> ImageContent:
    """Render a matplotlib figure as SVG if small enough, PNG otherwise."""
    svg_buf = io.BytesIO()
    fig.savefig(svg_buf, format='svg', bbox_inches='tight')
    svg_bytes = svg_buf.getvalue()
    size_kb = len(svg_bytes) / 1024
    logger.debug(f"Generated SVG size: {size_kb:.2f} KB")
    if len(svg_bytes) <= SVG_SIZE_LIMIT:
        logger.info("Size is under limit. Returning SVG.")
        plt.close(fig)
        return ImageContent(type="image", data=base64.b64encode(svg_bytes).decode(), mimeType="image/svg+xml")
    logger.warning(f"SVG size ({size_kb:.2f} KB) exceeded limit. Falling back to PNG.")
    png_buf = io.BytesIO()
    fig.savefig(png_buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    return ImageContent(type="image", data=base64.b64encode(png_buf.getvalue()).decode(), mimeType="image/png")


def fig_to_b64(fig) -> str:
    ic = fig_to_image_content(fig)
    return f'data:{ic.mimeType};base64,{ic.data}'


# Persistent sandbox — variables survive across execute_analysis calls.
# `display` is re-injected each call since it captures a per-call report list.
_sandbox = {
    'np': np,
    'pd': pd,
    'plt': plt,
    'sns': sns,
    'Image': PILImage,
    'cave_client': cave_client,
    # Synapse data functions
    'get_downstream_synapses_df': get_downstream_synapses_df,
    'get_upstream_synapses_df': get_upstream_synapses_df,
    'get_synapse_partners_df': get_synapse_partners_df,
    'get_targeted_compartments_df': get_targeted_compartments_df,
    # Viewer functions
    'show_synapse_annotations': show_synapse_annotations,
}


@mcp_server.tool()
def execute_analysis(code: str) -> List[TextContent | ImageContent]:
    """
    Execute generated Python code against connectome data.

    Available modules: np, pd, plt, Image (PIL)

    Available dataframes (injected into namespace):
        mtypes_df     — aibs_metamodel_mtypes_v661_v2: M-type predictions for all neurons in the dataset.
                        classification_system: 'excitatory_neuron' | 'inhibitory_neuron' (coarse)
                        cell_type: fine-grained M-type label (e.g. 'L5ET', 'L4a', 'MC', 'BC')
                        pt_root_id: segment ID  |  pt_position_x/y/z: soma position in nm
                        Errors, non-neurons, and soma mergers have been filtered out.

        celltypes_df  — aibs_metamodel_celltypes_v661: broader anatomical cell-type predictions.
                        Same schema as mtypes_df but cell_type also covers nonneuronal subclasses
                        (astrocyte, microglia, oligo, OPC, pericyte) and neuronal subclasses.
                        Less filtered — includes nonneuronal cells.

    Available data functions (return DataFrames, composable in code):
        get_downstream_synapses_df(root_id, limit=None)    → synapse rows where pre_pt_root_id == root_id
        get_upstream_synapses_df(root_id, limit=None)      → synapse rows where post_pt_root_id == root_id
        get_synapse_partners_df(root_id, direction, limit) → top partners by synapse count
        get_targeted_compartments_df(root_id, compartment) → compartment-filtered synapses

    Available viewer functions (mutate the neuroglancer viewer directly):
        show_synapse_annotations(df, layer_name)           → render synapse df as point annotations

    Available output function:
        display(content) — call multiple times to build the report
            str           → markdown text block
            plt.Figure    → SVG (preferred) or PNG fallback
            PIL.Image     → PNG

    Sandbox state persists across calls — variables defined in one call are
    available in the next, enabling multi-step workflows.
    """
    # Refresh per-session dataframe references in case they were reloaded
    _sandbox['mtypes_df'] = session.aibs_metamodel_mtypes_v661_v2
    _sandbox['celltypes_df'] = session.aibs_metamodel_celltypes_v661

    report_blocks = []

    def display(content):
        if isinstance(content, str):
            report_blocks.append(TextContent(type="text", text=content))
        elif hasattr(content, "savefig"):
            report_blocks.append(fig_to_image_content(content))
        elif isinstance(content, PILImage.Image):
            buf = io.BytesIO()
            content.save(buf, format="PNG")
            report_blocks.append(ImageContent(type="image", data=base64.b64encode(buf.getvalue()).decode(), mimeType="image/png"))

    _sandbox['display'] = display
    exec(code, _sandbox)
    return report_blocks