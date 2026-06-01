import base64
import io
import sys
from typing import List
from mcp.types import TextContent, ImageContent
from matplotlib import pyplot as plt
plt.rcParams['svg.fonttype'] = 'none'       # dont allow fonts to be exported as SVG paths

from mcp_src.core import mcp_server, cave_client, session
import pandas as pd
import numpy as np
from PIL import Image as PILImage

from loguru import logger
logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <white>{message}</white>")

SVG_SIZE_LIMIT = 500 * 1024  # 500 KB — above this, scatter-heavy plots are cheaper as PNG


def fig_to_image_content(fig) -> ImageContent:
    """Render a matplotlib figure as SVG if small enough, PNG otherwise."""
    svg_buf = io.BytesIO()
    fig.savefig(svg_buf, format='svg', bbox_inches='tight')
    svg_bytes = svg_buf.getvalue()

    # --- LOG THE ACTUAL SIZE ---
    size_kb = len(svg_bytes) / 1024
    logger.debug(f"Generated SVG size: {size_kb:.2f} KB")

    if len(svg_bytes) <= SVG_SIZE_LIMIT:
        logger.info("Size is under limit. Returning SVG.")
        plt.close(fig)
        return ImageContent(type="image", data=base64.b64encode(svg_bytes).decode(), mimeType="image/svg+xml")

    logger.warning(f"SVG size ({size_kb:.2f} KB) exceeded {SVG_SIZE_LIMIT / 1024} KB limit! Falling back to PNG.")
    png_buf = io.BytesIO()
    fig.savefig(png_buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    return ImageContent(type="image", data=base64.b64encode(png_buf.getvalue()).decode(), mimeType="image/png")


def fig_to_b64(fig) -> str:
    ic = fig_to_image_content(fig)
    return f'data:{ic.mimeType};base64,{ic.data}'

# TODO -
def downstream_synapes(neuron_root_id: int, limit=None):
    df_synapses = cave_client.materialize.query_table(
        'synapses_pni_2',
        filter_equal_dict={'pre_pt_root_id': neuron_root_id},
        desired_resolution=[1, 1, 1]
    )
    if limit:
        df_synapses = df_synapses.head(limit)
    return df_synapses

# class AnalysisResult(BaseModel):
#     """The strongly-typed output of a neuron population search."""
#     text: str = Field(description="Results in text form. Preferrably markdown. Could consist of tabular data, summaries, formatted answers based on numerical results.")
#     images: List[Image] = Field(description="A list of images in PIL Image format. Could be the result of plt figures, for example")




@mcp_server.tool()
def execute_analysis(code: str) -> List[TextContent | ImageContent]:
    """
    This tool allows more complex on the connectome data by using generated python code

    Available python modules: np, pd, plt

    Available dataframes:
        neurons_df: the primary neuron table. Contains the following columns
            - id: int the neuron id
            - classification_system: Literal["inhibitory_neuron", "excitatory_neuron"]
            - cell_type: str

    Available functions :
        downstream_synapes(neuron_root_id: int, limit=None):
            Use this to fetch (from the cloud, slow!) a pandas dataframe with the following columns:
                - ctr_pt_position: List[int, int, int] center synapse postiion
                - size: float size of the synapse
                - pre_pt_root_id:  id of source neuron
                - post_pt_root_id: id of destination neuron

        display(content): Use this to add content to your final report. Call this multiple times to interleave text and charts (e.g., text, fig1, text, fig2).
            - If you pass a string, it adds a markdown text block.
            - If you pass a Matplotlib Figure, the browser UI will receive an SVG (preferred for most plot types)
            - When creating plots with more than 1,000 points, use rasterized=True in your plot call (e.g., plt.scatter(x, y, rasterized=True)). This prevents SVG bloat.
            - If you pass a PIL Image, the browser UI will render a PNG

    """

    report_blocks = []
    def display(content):
        """Internal helper injected into the sandbox."""
        if isinstance(content, str):
            report_blocks.append(TextContent(type="text", text=content))
        elif hasattr(content, "savefig"):  # Handle Matplotlib Figures
            report_blocks.append(fig_to_image_content(content))
        elif isinstance(content, PILImage.Image):  # Handle PIL Images
            buf = io.BytesIO()
            content.save(buf, format="PNG")
            report_blocks.append(ImageContent(type="image", data=base64.b64encode(buf.getvalue()).decode(), mimeType="image/png"))

    namespace = {
        'neurons_df': session.aibs_metamodel_mtypes_v661_v2,
        'np': np, 'pd': pd, 'plt': plt, 'Image': PILImage,
        'display': display, 'downstream_synapes': downstream_synapes
    }
    exec(code, namespace)

    return report_blocks


