from .activitystats import ActivityStats


async def setup(bot):
    """Load the ActivityStats cog."""
    await bot.add_cog(ActivityStats(bot))
