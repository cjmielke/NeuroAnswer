import os
import uuid
from mcp.server import FastMCP
import time
from pathlib import Path
from typing import Dict
import caveclient
import pandas as pd


mcp_server = FastMCP("NeuroAnswer", host=os.environ.get("MCP_HOST", "127.0.0.1"), port=8000)

cave_client = caveclient.CAVEclient('minnie65_public')

class ConnectomeSession:
    """Manages the in-memory state so Claude doesn't crash on massive datasets."""

    # Cache configuration
    CACHE_DIR = Path("./data")
    CACHE_TIMEOUT_SECONDS = 7 * 24 * 60 * 60  # 1 week in seconds

    def __init__(self):
        self.dataframes: Dict[str, pd.DataFrame] = {}

        # Ensure the ./data directory exists
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

        print("Booting NeuroAnswer... Loading Structural Metadata.")

        # Load the flagship Excitatory and Inhibitory tables
        self.excitatory_cache = self._load_or_fetch_table('aibs_metamodel_mtypes_v661_v2')
        self.inhibitory_cache = self._load_or_fetch_table('aibs_metamodel_celltypes_v661')

        print("Boot complete. Ready for Claude.")

    def _load_or_fetch_table(self, table_name: str) -> pd.DataFrame:
        """
        Attempts to load a dataframe from local Parquet storage.
        If it doesn't exist or is older than 1 week, it fetches a fresh copy from CAVE.
        """
        file_path = self.CACHE_DIR / f"{table_name}.parquet"

        # 1. Check if the file exists and is fresh
        if file_path.exists():
            file_age_seconds = time.time() - file_path.stat().st_mtime

            if file_age_seconds < self.CACHE_TIMEOUT_SECONDS:
                age_hours = file_age_seconds / 3600
                print(f"  -> Loaded {table_name} from local cache (Age: {age_hours:.1f} hours)")
                return pd.read_parquet(file_path)
            else:
                print(f"  -> Cache expired for {table_name} (Older than 1 week). Re-downloading...")
        else:
            print(f"  -> No local cache found for {table_name}. Downloading from CAVE...")

        # 2. If we reach here, we need to download it (assumes 'client' is in global scope)
        df = cave_client.materialize.query_table(
            table_name,
            desired_resolution=[1, 1, 1],   # Forces download in true nanometers
            split_positions=True            # Automatically unpacks into _x, _y, _z columns
        )

        if 'pt_position_x' not in df.columns and 'pt_position' in df.columns:
            print("Unpacking spatial coordinates for optimized distance querying...")

            # This is the fastest method to expand a column of lists into separate columns
            df[['pt_position_x', 'pt_position_y', 'pt_position_z']] = pd.DataFrame(
                df['pt_position'].tolist(),
                index=df.index
            )

        # 3. Save it to disk for next time
        df.to_parquet(file_path, engine='pyarrow', index=False)
        print(f"  -> Saved {table_name} to local Parquet cache.")

        return df

    def store_df(self, df: pd.DataFrame) -> str:
        # Simple garbage collection: keep only the last 5 queries in RAM
        if len(self.dataframes) >= 5:
            del self.dataframes[list(self.dataframes.keys())[0]]

        ref_id = f"mem_ref_{uuid.uuid4().hex[:8]}"
        self.dataframes[ref_id] = df
        return ref_id



# Instantiate the state manager
session = ConnectomeSession()



