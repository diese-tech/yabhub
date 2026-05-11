import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from config import JOIN_TO_CREATE_NAME
from services.permissions import require_manage_channels

if TYPE_CHECKING:
    from bot import YapHubBot

logger = logging.getLogger("yaphub")


def build_lobby_name(_: str) -> str:
    return JOIN_TO_CREATE_NAME


class ProfileGroup(app_commands.Group):
    def __init__(self, bot: "YapHubBot") -> None:
        super().__init__(name="profile", description="Manage Join to Yap profiles")
        self.bot = bot

    @app_commands.command(name="create", description="Create a new Join to Yap profile")
    async def create(
        self,
        interaction: discord.Interaction,
        name: str,
        category: discord.CategoryChannel | None = None,
        lobby_channel: discord.VoiceChannel | None = None,
    ) -> None:
        if not require_manage_channels(interaction):
            await interaction.response.send_message(
                "You need Manage Channels permission.",
                ephemeral=True,
            )
            return

        assert interaction.guild is not None
        guild = interaction.guild

        if self.bot.storage.get_profile_by_name(guild.id, name):
            await interaction.response.send_message(
                f"A profile named `{name}` already exists.",
                ephemeral=True,
            )
            return

        target_category = category
        if lobby_channel is not None and target_category is None:
            target_category = lobby_channel.category

        if lobby_channel is None:
            lobby_channel = await guild.create_voice_channel(
                build_lobby_name(name),
                category=target_category,
                reason=f"YapHub profile setup for {name}",
            )

        profile = self.bot.storage.create_profile(
            guild_id=guild.id,
            name=name,
            join_channel_id=lobby_channel.id,
            target_category_id=target_category.id if target_category else None,
            created_by_user_id=interaction.user.id,
        )
        self.bot.profile_cache[int(profile["join_channel_id"])] = profile

        await interaction.response.send_message(
            (
                f"Created profile `{name}`.\n"
                f"Lobby: {lobby_channel.mention}\n"
                f"Target category: {target_category.name if target_category else 'Top level'}"
            ),
            ephemeral=True,
        )

    @app_commands.command(name="list", description="List configured Join to Yap profiles")
    async def list_profiles(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        profiles = self.bot.storage.list_profiles(interaction.guild.id)

        if not profiles:
            await interaction.response.send_message(
                "No Join to Yap profiles are configured yet.",
                ephemeral=True,
            )
            return

        lines = []
        for profile in profiles:
            lobby_channel = interaction.guild.get_channel(int(profile["join_channel_id"]))
            category_name = "Top level"
            if profile["target_category_id"]:
                category = interaction.guild.get_channel(int(profile["target_category_id"]))
                if isinstance(category, discord.CategoryChannel):
                    category_name = category.name

            lines.append(
                (
                    f"`{profile['name']}`"
                    f" | lobby: {lobby_channel.mention if lobby_channel else profile['join_channel_id']}"
                    f" | category: {category_name}"
                )
            )

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="delete", description="Delete a Join to Yap profile")
    async def delete(self, interaction: discord.Interaction, name: str) -> None:
        if not require_manage_channels(interaction):
            await interaction.response.send_message(
                "You need Manage Channels permission.",
                ephemeral=True,
            )
            return

        assert interaction.guild is not None
        profile = self.bot.storage.get_profile_by_name(interaction.guild.id, name)
        if profile is None:
            await interaction.response.send_message(
                f"No profile named `{name}` was found.",
                ephemeral=True,
            )
            return

        join_channel_id = int(profile["join_channel_id"])
        join_channel = interaction.guild.get_channel(join_channel_id)
        if isinstance(join_channel, discord.VoiceChannel):
            try:
                await join_channel.delete(reason=f"YapHub profile delete for {name}")
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Failed to delete lobby channel %s", join_channel_id)

        self.bot.storage.delete_profile(profile["id"])
        self.bot.profile_cache.pop(join_channel_id, None)

        await interaction.response.send_message(
            f"Deleted profile `{name}`.",
            ephemeral=True,
        )
