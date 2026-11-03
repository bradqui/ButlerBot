from .gamemanager import GameManager


async def setup(bot):
    """Load the GameManager cog."""
    await bot.add_cog(GameManager(bot))
