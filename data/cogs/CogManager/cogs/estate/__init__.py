from .estate import Estate


async def setup(bot):
    """Load the Estate cog."""
    await bot.add_cog(Estate(bot))
