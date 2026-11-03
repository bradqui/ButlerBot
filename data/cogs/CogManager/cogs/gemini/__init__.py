import sys
import importlib
from pathlib import Path

# 1. Add our local 'lib' folder to the top of the system path
lib_path = Path(__file__).parent / "lib"
sys.path.insert(0, str(lib_path))

# 2. FORCE RELOAD typing_extensions
# This is the critical fix. We check if the loaded version is the old one (missing Sentinel).
# If it is, we remove it from memory so Python is forced to load our local version.

try:
    import typing_extensions
    
    # Check if the 'Sentinel' class exists (the specific thing pydantic is crashing on)
    if not hasattr(typing_extensions, "Sentinel"):
        # It's the old version! Purge it.
        if "typing_extensions" in sys.modules:
            del sys.modules["typing_extensions"]
            
        # Import it again - this time it will grab from our 'lib' folder because of step 1
        import typing_extensions
except ImportError:
    pass

# 3. Now it is safe to load the cog
from .gemini import GeminiChat

async def setup(bot):
    await bot.add_cog(GeminiChat(bot))