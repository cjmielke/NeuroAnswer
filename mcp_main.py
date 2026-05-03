import os
import warnings


# Suppress cloud-volume warnings
os.environ['GCE_METADATA_TIMEOUT'] = '0.1'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = '/dev/null'
warnings.filterwarnings("ignore", module="cloudvolume")
warnings.filterwarnings("ignore", category=UserWarning)


from mcp_src.core import mcp_server
from mcp_src import neurons, synapses, scene


if __name__ == "__main__":
    # stdio transport
    #mcp.run()

    # Binds the MCP server to a local TCP port using Server-Sent Events
    mcp_server.run(transport='sse')


