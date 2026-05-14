import base64
import io
from typing import List, Dict
from mcp.server.fastmcp import Image as MCPImage
from matplotlib import pyplot as plt


from mcp_src.core import mcp_server, cave_client, session
import pandas as pd
import numpy as np
from PIL import Image as PILImage


def fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight')
    plt.close(fig)
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()

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
def execute_analysis(code: str) -> List:
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

        display(content): Use this to add content to your final report.
            - If you pass a string, it adds a markdown text block.
            - If you pass a PIL Image or a Matplotlib Figure, it adds an image block.
            - Call this multiple times to interleave text and charts (e.g., text, fig1, text, fig2).

    Results :
        Place all results from your analysis in the following variables:
        summary: str, a textual summary of the analysis results. Preferrably in markdown format
        images: List[Image]     a list of PIL Image objects. This is were results from matplotlib can be placed
    """

    report_blocks = []
    def display(content):
        """Internal helper injected into the sandbox."""
        if isinstance(content, str):
            report_blocks.append(content)
        elif hasattr(content, "savefig"):  # Handle Matplotlib Figures
            buf = io.BytesIO()
            content.savefig(buf, format="png", bbox_inches='tight')
            plt.close(content)
            report_blocks.append(MCPImage(data=buf.getvalue(), format="png"))
        elif isinstance(content, PILImage.Image):  # Handle PIL Images
            buf = io.BytesIO()
            content.save(buf, format="PNG")
            report_blocks.append(MCPImage(data=buf.getvalue(), format="png"))

    namespace = {
        'neurons_df': session.excitatory_cache,
        'np': np, 'pd': pd, 'plt': plt, 'Image': PILImage,
        'display': display, 'downstream_synapes': downstream_synapes
    }
    exec(code, namespace)

    return report_blocks


