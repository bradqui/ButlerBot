import importlib.util
import sys

from redbot.core.data_manager import cog_data_path


def _ensure_typing_extensions():
    """
    The anthropic SDK imports pydantic, which needs `typing_extensions.Sentinel`.
    Red's venv ships an older typing_extensions, and Red puts the Downloader lib
    folder (which has a newer copy) at the END of sys.path, so the old one wins.
    Swap in the Downloader copy before anything imports pydantic.
    """
    current = sys.modules.get("typing_extensions")
    if current is not None and hasattr(current, "Sentinel"):
        return  # Already a new enough version (e.g. the Gemini cog fixed it first).

    lib_file = cog_data_path(raw_name="Downloader") / "lib" / "typing_extensions.py"
    if not lib_file.exists():
        raise RuntimeError(
            "The Claude cog needs a newer typing_extensions. Run `[p]pipinstall -U typing_extensions` and reload."
        )

    spec = importlib.util.spec_from_file_location("typing_extensions", lib_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules["typing_extensions"] = module
    spec.loader.exec_module(module)


_ensure_typing_extensions()

from .claude import ClaudeChat  # noqa: E402  (must import after the fix above)


async def setup(bot):
    await bot.add_cog(ClaudeChat(bot))
