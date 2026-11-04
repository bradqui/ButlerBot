from .butlerfun import ButlerFun


async def setup(bot):
    """Load the ButlerFun cog."""
    await bot.add_cog(ButlerFun(bot))
