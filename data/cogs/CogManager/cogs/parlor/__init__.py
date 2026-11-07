from .parlor import Parlor


async def setup(bot):
    """Load the Parlor cog."""
    await bot.add_cog(Parlor(bot))
