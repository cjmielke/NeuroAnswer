import os
import warnings
from dotenv import load_dotenv
load_dotenv()

# import debugpy
# debugpy.listen(5678)
# debugpy.wait_for_client()

import signal

# make restarts during development a little faster
# signal.signal(signal.SIGINT, lambda sig, frame: os._exit(0))

# Suppress cloud-volume warnings
os.environ['GCE_METADATA_TIMEOUT'] = '0.1'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = '/dev/null'
warnings.filterwarnings("ignore", module="cloudvolume")
warnings.filterwarnings("ignore", category=UserWarning)

import logging
from mcp_src.core import mcp_server
from mcp_src.ng import viewer
from mcp_src import neurons, synapses, scene, analysis
logging.info(viewer.get_viewer_url())


if __name__ == "__main__":
    # stdio transport
    #mcp.run()

    # Binds the MCP server to a local TCP port using Server-Sent Events
    mcp_server.run(transport='sse')


