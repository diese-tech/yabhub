import discord

from services.ownership import resolve_owned_temp_channel
from services.permissions import lock_temp_channel, unlock_temp_channel


async def rename_temp_channel(bot, interaction: discord.Interaction, name: str) -> None:
    channel = await resolve_owned_temp_channel(interaction, bot.storage)
    if channel is None:
        return

    await channel.edit(name=name, reason=f"YapHub rename by user {interaction.user.id}")
    await interaction.response.send_message(
        f"Renamed your Yap room to `{name}`.",
        ephemeral=True,
    )


async def limit_temp_channel(bot, interaction: discord.Interaction, count: int) -> None:
    channel = await resolve_owned_temp_channel(interaction, bot.storage)
    if channel is None:
        return

    await channel.edit(user_limit=count, reason=f"YapHub limit by user {interaction.user.id}")
    label = "unlimited" if count == 0 else str(count)
    await interaction.response.send_message(
        f"Set your Yap room limit to `{label}`.",
        ephemeral=True,
    )


async def transfer_temp_channel(
    bot,
    interaction: discord.Interaction,
    user: discord.Member,
) -> None:
    channel = await resolve_owned_temp_channel(interaction, bot.storage)
    if channel is None:
        return

    if user.bot:
        await interaction.response.send_message(
            "Yap rooms can only be transferred to server members.",
            ephemeral=True,
        )
        return

    if user not in channel.members:
        await interaction.response.send_message(
            "Transfer target must be in your Yap room.",
            ephemeral=True,
        )
        return

    bot.storage.transfer_active_temp_channel_owner(channel.id, user.id)
    await interaction.response.send_message(
        f"Transferred ownership of {channel.mention} to {user.mention}.",
        ephemeral=True,
    )


async def lock_owned_temp_channel(bot, interaction: discord.Interaction) -> None:
    channel = await resolve_owned_temp_channel(interaction, bot.storage)
    if channel is None:
        return

    owner = None
    record = bot.storage.get_active_temp_channel(channel.id)
    if interaction.guild is not None and record is not None:
        owner = interaction.guild.get_member(int(record["owner_user_id"]))

    await lock_temp_channel(
        channel,
        reason=f"YapHub lock by user {interaction.user.id}",
        owner=owner,
    )
    await interaction.response.send_message(
        "Locked your Yap room.",
        ephemeral=True,
    )


async def unlock_owned_temp_channel(bot, interaction: discord.Interaction) -> None:
    channel = await resolve_owned_temp_channel(interaction, bot.storage)
    if channel is None:
        return

    await unlock_temp_channel(channel, reason=f"YapHub unlock by user {interaction.user.id}")
    await interaction.response.send_message(
        "Unlocked your Yap room.",
        ephemeral=True,
    )
