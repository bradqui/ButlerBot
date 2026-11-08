from .setupwizard import SetupWizard


async def setup(bot):
    await bot.add_cog(SetupWizard(bot))
