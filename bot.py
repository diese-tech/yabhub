import os

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

from config import TEMP_CHANNEL_PREFIX, JOIN_TO_CREATE_NAME

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

join_to_create_channels = {}
temp_channels = {}


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")


class YapGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="yap", description="YapHub voice controls")

    @app_commands.command(name="setup", description="Create a Join to Yap voice channel")
    async def setup(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message(
                "You need Manage Channels permission.",
                ephemeral=True,
            )
            return

        guild = interaction.guild

        channel = await guild.create_voice_channel(JOIN_TO_CREATE_NAME)

        join_to_create_channels[guild.id] = channel.id

        await interaction.response.send_message(
            f"Created {channel.mention}",
            ephemeral=True,
        )


bot.tree.add_command(YapGroup())


@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild

    join_channel_id = join_to_create_channels.get(guild.id)

    if after.channel and after.channel.id == join_channel_id:
        category = after.channel.category

        temp_channel = await guild.create_voice_channel(
            name=f"{TEMP_CHANNEL_PREFIX} {member.display_name}'s Yap",
            category=category,
        )

        temp_channels[temp_channel.id] = member.id

        await member.move_to(temp_channel)

    if before.channel and before.channel.id in temp_channels:
        if len(before.channel.members) == 0:
            temp_channels.pop(before.channel.id, None)
            await before.channel.delete()


bot.run(TOKEN)
