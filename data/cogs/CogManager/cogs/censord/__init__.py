from .censord import Censord

async def setup(bot):
    await bot.add_cog(Censord(bot))