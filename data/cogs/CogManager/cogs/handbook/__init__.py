from .handbook import Handbook


async def setup(bot):
    """Load the Handbook cog."""
    await bot.add_cog(Handbook(bot))
