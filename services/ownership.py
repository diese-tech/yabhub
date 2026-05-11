from collections.abc import Sequence
from typing import Protocol

import discord


class TempChannelStorage(Protocol):
    def get_active_temp_channel(self, channel_id: int): ...


def has_manage_channels(interaction: discord.Interaction) -> bool:
    return bool(
        interaction.guild
        and isinstance(interaction.user, discord.Member)
        and interaction.user.guild_permissions.manage_channels
    )


def user_is_recorded_owner(record, user_id: int) -> bool:
    return record is not None and int(record["owner_user_id"]) == user_id


async def resolve_owned_temp_channel(
    interaction: discord.Interaction,
    storage: TempChannelStorage,
) -> discord.VoiceChannel | None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(
            "This command can only be used in a server.",
            ephemeral=True,
        )
        return None

    voice = interaction.user.voice
    channel = voice.channel if voice else None
    if not isinstance(channel, discord.VoiceChannel):
        await interaction.response.send_message(
            "Join your Yap room before using this command.",
            ephemeral=True,
        )
        return None

    record = storage.get_active_temp_channel(channel.id)
    if record is None or int(record["guild_id"]) != interaction.guild.id:
        await interaction.response.send_message(
            "That voice channel is not a tracked YapHub temp room.",
            ephemeral=True,
        )
        return None

    if not user_is_recorded_owner(record, interaction.user.id) and not has_manage_channels(
        interaction
    ):
        await interaction.response.send_message(
            "Only the room owner or a Manage Channels admin can do that.",
            ephemeral=True,
        )
        return None

    return channel


def active_channel_ids(rows: Sequence) -> set[int]:
    return {int(row["channel_id"]) for row in rows}
