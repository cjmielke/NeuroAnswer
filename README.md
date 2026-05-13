# NeuroAnswer

An AI copilot for exploring the [MICrONs Minnie65](https://www.microns-explorer.org/) connectome dataset. NeuroAnswer lets researchers query 200,000+ neurons and 500 million synapses using natural language, with results rendered directly in [Neuroglancer](https://github.com/google/neuroglancer).

![NeuroAnswer Screenshot](img/screenshot.png)

## What it does

NeuroAnswer connects Claude to the [CAVE](https://caveclient.readthedocs.io/) connectomics database via an MCP (Model Context Protocol) server. Ask a question in plain English — "show me the closest soma" or "trace the downstream synapses of this L5 pyramidal cell" — and the system fetches the data, builds the 3D scene, and renders it in your Neuroglancer view.

**Current capabilities:**
- Spatial queries: find neurons by cell type within the current Neuroglancer viewport
- Synapse tracing: retrieve downstream synaptic targets for any neuron and render pre/post-synaptic markers

**Coming soon!:**
- Compartment targeting: identify synapses by postsynaptic compartment (soma, shaft, spine)
- Population search: look up excitatory and inhibitory neuron populations by morphological type

## Architecture

```
Chrome Extension (sidebar UI)
        ↕
FastAPI Gateway (relay server)
        ↕
MCP Server (FastMCP + CAVE client)
        ↕
CAVE / MICrONs Minnie65 cloud database
```

The MCP server exposes domain-specific tools — spatial search, synapse queries, scene construction — that Claude calls through the standard MCP protocol. A FastAPI gateway bridges the Chrome extension's HTTP requests to the MCP server. The extension injects a chat sidebar into the Neuroglancer interface and pushes returned scene state (layers, annotations, camera position) directly into the viewer.

Neuron metadata is cached locally as Parquet files to keep spatial queries fast. Synapse data is fetched live from CAVE on demand - a bit slower, but I'm working on it!

## In development

- **Code execution sandbox**: allowing Claude to run generated Python (pandas, numpy, matplotlib) workflows against the MICrONs dataset and render scientific figures in the browser
- **Richer annotation support**: line annotations connecting pre- and post-synaptic sites with size/weight labels

## Future directions

- **Dataset generalization**: extending support to FlyWire, H01 (human cortex), and other connectomics datasets with different database schemas
- **Simplified architecture**: moving the full agent loop into the Chrome extension to eliminate the FastAPI relay
- **Community-driven tool design**: the tool vocabulary should be shaped by what researchers actually need — feedback on useful queries and workflows is very welcome

## Built with

Python · FastMCP · CAVEclient · nglui · FastAPI · Chrome Extensions API

## Feedback

This project is under active development. If you work in connectomics or neuroscience and have thoughts on what queries or workflows would be most useful in a natural language interface for Neuroglancer, please open an issue or reach out. The goal is to build something the field actually wants to use.
