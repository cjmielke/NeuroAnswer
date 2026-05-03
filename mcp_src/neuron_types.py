from typing import Literal
from pydantic import BaseModel, Field

# ONE place to maintain codes AND descriptions
EXCITATORY_TYPES = {
    "L2a": "Layer 2 superficial",
    "L5ET": "Thick-tufted / Brainstem-projecting",
    "ITC": "Cortico-cortical (inter-telencephalic)",
    "PTC": "Motor output (perisomatic targeting)",
    "STC": "Sparsely targeting"
}

# Programmatically generate the LLM prompt from the dictionary
mtype_docs = "The excitatory cell type. Definitions:\n" + "\n".join(
    f"- {code}: {desc}" for code, desc in EXCITATORY_TYPES.items()
)

# Use Literal for strict IDE typing, and inject the generated docs
class PopulationSearchInput(BaseModel):
    mtype: Literal["L2a", "L5ET", "ITC", "PTC", "STC"] = Field(
        ...,
        description=mtype_docs
    )
    limit: int = Field(5, description="Max cells to return.")

# Claude-generated assumptions .... need to find an authoritative table

"""
  ┌──────────────────────────────┬──────────────────────────────────────────────┐
  │             Code             │                 Description                  │
  ├──────────────────────────────┼──────────────────────────────────────────────┤
  │ L2a, L2b, L2c                │ Layer 2 subtypes                             │
  ├──────────────────────────────┼──────────────────────────────────────────────┤
  │ L3a, L3b                     │ Layer 3 subtypes                             │
  ├──────────────────────────────┼──────────────────────────────────────────────┤
  │ L4a, L4b, L4c                │ Layer 4 subtypes                             │
  ├──────────────────────────────┼──────────────────────────────────────────────┤
  │ L5a, L5b                     │ Layer 5 subtypes                             │
  ├──────────────────────────────┼──────────────────────────────────────────────┤
  │ L5ET                         │ Thick-tufted / Brainstem-projecting          │
  ├──────────────────────────────┼──────────────────────────────────────────────┤
  │ L5NP                         │ Layer 5 near-projecting                      │
  ├──────────────────────────────┼──────────────────────────────────────────────┤
  │ L6tall-a, L6tall-b, L6tall-c │ Layer 6 tall subtypes                        │
  ├──────────────────────────────┼──────────────────────────────────────────────┤
  │ L6short-a, L6short-b         │ Layer 6 short subtypes                       │
  ├──────────────────────────────┼──────────────────────────────────────────────┤
  │ PTC                          │ Motor output (perisomatic targeting cells)   │
  ├──────────────────────────────┼──────────────────────────────────────────────┤
  │ DTC                          │ Distal targeting cells                       │
  ├──────────────────────────────┼──────────────────────────────────────────────┤
  │ ITC                          │ Cortico-cortical (inter-telencephalic cells) │
  ├──────────────────────────────┼──────────────────────────────────────────────┤
  │ STC                          │ Sparsely targeting cells                     │
  └──────────────────────────────┴──────────────────────────────────────────────┘


"""
