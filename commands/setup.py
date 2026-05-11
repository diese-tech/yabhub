import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from commands.owner_controls import (
    limit_temp_channel,
    lock_owned_temp_channel,
    rename_temp_channel,
    transfer_temp_channel,
    unlock_owned_temp_channel,
)
from commands.profiles import ProfileGroup
from config import JOIN_TO_CREATE_NAME
from services.permissions import require_manage_channels

if TYPE_CHECKING:
    from bot import YapHubBot

logger = logging.getLogger("yaphub")


class YapGroup(app_commands.Group):
    def __init__(self, bot: "YapHubBot") -> None:
        super().__init__(name="yap", description="YapHub temp VC controls")
        self.bot = bot
        self.add_command(ProfileGroup(bot))

    @app_commands.command(name="setup", description="Create the default Join to Yap profile")
    async def setup(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel | None = None,
    ) -> None:
        if not require_manage_channels(interaction):
            await interaction.response.send_message(
                "You need Manage Channels permission.",
                ephemeral=True,
            )
            return

        assert interaction.guild is not None
        profiles = self.bot.storage.list_profiles(interaction.guild.id)
        if profiles:
            await interaction.response.send_message(
                "A Yap setup already exists. Use `/yap profile create` to add another section.",
                ephemeral=True,
            )
            return

        lobby_channel = await interaction.guild.create_voice_channel(
            JOIN_TO_CREATE_NAME,
            category=category,
            reason="YapHub default setup",
        )

        profile = self.bot.storage.create_profile(
            guild_id=interaction.guild.id,
            name="Default",
            join_channel_id=lobby_channel.id,
            target_category_id=category.id if category else None,
            created_by_user_id=interaction.user.id,
        )
        self.bot.profile_cache[int(profile["join_channel_id"])] = profile

        await interaction.response.send_message(
            (
                f"Created default Join to Yap profile.\n"
                f"Lobby: {lobby_channel.mention}\n"
                f"Category: {category.name if category else 'Top level'}"
            ),
            ephemeral=True,
        )

    @app_commands.command(name="config", description="Show the current YapHub configuration")
    async def config(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        guild_config = self.bot.storage.get_or_create_guild_config(interaction.guild.id)
        profiles = self.bot.storage.list_profiles(interaction.guild.id)
        active_rooms = self.bot.storage.list_active_temp_channels(interaction.guild.id)

        lines = [
            f"Temp prefix: `{guild_config['temp_channel_prefix']}`",
            f"Duplicate-room cooldown: `{guild_config['notification_cooldown_seconds']}s`",
            f"Profiles: `{len(profiles)}`",
            f"Active temp rooms: `{len(active_rooms)}`",
        ]

        if profiles:
            lines.append("")
            lines.append("Configured profiles:")
            for profile in profiles:
                lobby_channel = interaction.guild.get_channel(int(profile["join_channel_id"]))
                category_name = "Top level"
                if profile["target_category_id"]:
                    category = interaction.guild.get_channel(int(profile["target_category_id"]))
                    if isinstance(category, discord.CategoryChannel):
                        category_name = category.name

                lines.append(
                    (
                        f"- {profile['name']}: "
                        f"{lobby_channel.mention if lobby_channel else profile['join_channel_id']} "
                        f"-> {category_name}"
                    )
                )

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="reset", description="Remove all Join to Yap profiles for this server")
    async def reset(self, interaction: discord.Interaction, confirm: bool = False) -> None:
        if not require_manage_channels(interaction):
            await interaction.response.send_message(
                "You need Manage Channels permission.",
                ephemeral=True,
            )
            return

        if not confirm:
            await interaction.response.send_message(
                "Run `/yap reset confirm:true` to clear all configured profiles.",
                ephemeral=True,
            )
            return

        assert interaction.guild is not None
        profiles = self.bot.storage.list_profiles(interaction.guild.id)

        deleted_channels = 0
        for profile in profiles:
            join_channel_id = int(profile["join_channel_id"])
            join_channel = interaction.guild.get_channel(join_channel_id)
            if isinstance(join_channel, discord.VoiceChannel):
                try:
                    await join_channel.delete(reason="YapHub reset")
                    deleted_channels += 1
                except (discord.Forbidden, discord.HTTPException):
                    logger.exception("Failed to delete lobby channel %s during reset", join_channel_id)
            self.bot.profile_cache.pop(join_channel_id, None)

        self.bot.storage.reset_guild_configuration(interaction.guild.id)

        await interaction.response.send_message(
            (
                f"Reset YapHub for this server.\n"
                f"Deleted lobby channels: `{deleted_channels}`\n"
                "Existing active temp rooms will continue to be tracked until they empty."
            ),
            ephemeral=True,
        )

    @app_commands.command(name="rename", description="Rename your active Yap room")
    async def rename(self, interaction: discord.Interaction, name: str) -> None:
        await rename_temp_channel(self.bot, interaction, name)

    @app_commands.command(name="limit", description="Set the user limit for your active Yap room")
    async def limit(
        self,
        interaction: discord.Interaction,
        count: app_commands.Range[int, 0, 99],
    ) -> None:
        await limit_temp_channel(self.bot, interaction, count)

    @app_commands.command(name="transfer", description="Transfer your active Yap room to another member")
    async def transfer(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await transfer_temp_channel(self.bot, interaction, user)

    @app_commands.command(name="lock", description="Lock your active Yap room")
    async def lock(self, interaction: discord.Interaction) -> None:
        await lock_owned_temp_channel(self.bot, interaction)

    @app_commands.command(name="unlock", description="Unlock your active Yap room")
    async def unlock(self, interaction: discord.Interaction) -> None:
        await unlock_owned_temp_channel(self.bot, interaction)
