import discord


def require_manage_channels(interaction: discord.Interaction) -> bool:
    return bool(
        interaction.guild
        and isinstance(interaction.user, discord.Member)
        and interaction.user.guild_permissions.manage_channels
    )


async def _clear_connect_overwrite(
    channel: discord.VoiceChannel,
    target: discord.Role | discord.Member,
    reason: str,
) -> None:
    overwrite = channel.overwrites_for(target)
    overwrite.connect = None

    if overwrite.is_empty():
        await channel.set_permissions(target, overwrite=None, reason=reason)
        return

    await channel.set_permissions(target, overwrite=overwrite, reason=reason)


async def lock_temp_channel(
    channel: discord.VoiceChannel,
    reason: str,
    owner: discord.Member | None = None,
) -> None:
    default_role = channel.guild.default_role
    default_overwrite = channel.overwrites_for(default_role)
    default_overwrite.connect = False
    await channel.set_permissions(default_role, overwrite=default_overwrite, reason=reason)

    allowed_members = list(channel.members)
    if owner is not None and all(member.id != owner.id for member in allowed_members):
        allowed_members.append(owner)

    for member in allowed_members:
        member_overwrite = channel.overwrites_for(member)
        member_overwrite.connect = True
        await channel.set_permissions(member, overwrite=member_overwrite, reason=reason)


async def unlock_temp_channel(channel: discord.VoiceChannel, reason: str) -> None:
    await _clear_connect_overwrite(channel, channel.guild.default_role, reason)

    for target, overwrite in list(channel.overwrites.items()):
        if isinstance(target, discord.Member) and overwrite.connect is True:
            await _clear_connect_overwrite(channel, target, reason)
