from .speakup import SpeakUp


async def setup(bot):
    """Load the SpeakUp cog."""
    await bot.add_cog(SpeakUp(bot))
