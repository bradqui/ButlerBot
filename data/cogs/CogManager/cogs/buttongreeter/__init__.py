from .buttongreeter import ButtonGreeter

async def setup(bot):
    await bot.add_cog(ButtonGreeter(bot))