import asyncio
import logging
import os
from collections import defaultdict
from collections.abc import Mapping

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from config import (
    DATABASE_PATH,
    DEFAULT_NOTIFICATION_COOLDOWN_SECONDS,
    DEFAULT_TEMP_CHANNEL_PREFIX,
    JOIN_TO_CREATE_NAME,
    NOTIFICATION_DELETE_AFTER_SECONDS,
    RECONCILE_INTERVAL_MINUTES,
)
from storage import Storage

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("yaphub")

TOKEN = os.getenv("DISCORD_TOKEN")


class YapHubBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.voice_states = True
        intents.guilds = True
        intents.members = True

        super().__init__(command_prefix="!", intents=intents)

        self.storage = Storage(DATABASE_PATH)
        self.profile_cache: dict[int, Mapping[str, object]] = {}
        self.active_temp_channel_ids: set[int] = set()
        self.notification_cooldowns: dict[tuple[int, int], float] = {}
        self.user_creation_locks: defaultdict[tuple[int, int], asyncio.Lock] = defaultdict(
            asyncio.Lock
        )
        self.started_once = False

    async def setup_hook(self) -> None:
        self.storage.initialize()
        self.tree.add_command(YapGroup(self))

    async def load_runtime_cache(self) -> None:
        self.profile_cache = {
            int(profile["join_channel_id"]): profile
            for profile in self.storage.list_all_profiles()
        }
        self.active_temp_channel_ids = {
            int(row["channel_id"]): row["channel_id"]
            for row in self.storage.list_active_temp_channels()
        }.keys()

    async def reconcile_active_temp_channels(self) -> None:
        tracked_ids: set[int] = set()

        for row in self.storage.list_active_temp_channels():
            guild = self.get_guild(int(row["guild_id"]))
            channel_id = int(row["channel_id"])

            if guild is None:
                logger.info(
                    "Removing stale temp channel record for missing guild %s",
                    row["guild_id"],
                )
                self.storage.delete_active_temp_channel(channel_id)
                continue

            channel = guild.get_channel(channel_id)
            if channel is None:
                try:
                    fetched = await self.fetch_channel(channel_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    fetched = None
                channel = fetched if isinstance(fetched, discord.VoiceChannel) else None

            if not isinstance(channel, discord.VoiceChannel):
                logger.info(
                    "Removing stale temp channel record for missing channel %s",
                    channel_id,
                )
                self.storage.delete_active_temp_channel(channel_id)
                continue

            if len(channel.members) == 0:
                try:
                    await channel.delete(reason="YapHub reconcile cleanup for empty temp VC")
                    self.storage.delete_active_temp_channel(channel_id)
                    logger.info("Deleted empty orphan temp channel %s", channel_id)
                except (discord.Forbidden, discord.HTTPException):
                    logger.exception("Failed to delete empty temp channel %s", channel_id)
                continue

            self.storage.touch_active_temp_channel(channel_id)
            tracked_ids.add(channel_id)

        self.active_temp_channel_ids = tracked_ids

    async def notify_duplicate_room(
        self,
        member: discord.Member,
        lobby_channel: discord.VoiceChannel,
        existing_channel: discord.VoiceChannel,
    ) -> None:
        cooldown_seconds = DEFAULT_NOTIFICATION_COOLDOWN_SECONDS
        guild_config = self.storage.get_guild_config(member.guild.id)
        if guild_config:
            cooldown_seconds = int(
                guild_config["notification_cooldown_seconds"]
                or DEFAULT_NOTIFICATION_COOLDOWN_SECONDS
            )

        cooldown_key = (member.guild.id, member.id)
        now = asyncio.get_running_loop().time()
        next_allowed_at = self.notification_cooldowns.get(cooldown_key, 0.0)
        if now < next_allowed_at:
            return

        self.notification_cooldowns[cooldown_key] = now + cooldown_seconds

        message = (
            f"You already have an active Yap room in **{member.guild.name}**: "
            f"{existing_channel.name}. Close that VC before creating a new one."
        )

        try:
            await member.send(message)
            return
        except (discord.Forbidden, discord.HTTPException):
            logger.info("DM failed for duplicate-room notice to user %s", member.id)

        fallback_message = (
            f"{member.mention} you already have an active Yap room: "
            f"{existing_channel.mention}. Close that VC before creating a new one."
        )

        for target in (lobby_channel, member.guild.system_channel):
            if target is None or not hasattr(target, "send"):
                continue

            try:
                await target.send(
                    fallback_message,
                    delete_after=NOTIFICATION_DELETE_AFTER_SECONDS,
                )
                return
            except (discord.Forbidden, discord.HTTPException):
                logger.info("Failed to send duplicate-room fallback notice in %s", target.id)

    async def resolve_existing_owned_channel(
        self, guild: discord.Guild, owner_user_id: int
    ) -> discord.VoiceChannel | None:
        existing_record = self.storage.get_active_temp_channel_by_owner(guild.id, owner_user_id)
        if existing_record is None:
            return None

        channel_id = int(existing_record["channel_id"])
        channel = guild.get_channel(channel_id)

        if channel is None:
            try:
                fetched = await self.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                fetched = None
            channel = fetched if isinstance(fetched, discord.VoiceChannel) else None

        if not isinstance(channel, discord.VoiceChannel):
            self.storage.delete_active_temp_channel(channel_id)
            self.active_temp_channel_ids.discard(channel_id)
            return None

        if len(channel.members) == 0:
            try:
                await channel.delete(reason="YapHub removing empty replaced temp VC")
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Failed to delete empty replaced temp VC %s", channel_id)
                return channel

            self.storage.delete_active_temp_channel(channel_id)
            self.active_temp_channel_ids.discard(channel_id)
            return None

        return channel

    async def create_temp_room(
        self,
        member: discord.Member,
        lobby_channel: discord.VoiceChannel,
        profile: Mapping[str, object],
    ) -> None:
        lock = self.user_creation_locks[(member.guild.id, member.id)]

        async with lock:
            existing_channel = await self.resolve_existing_owned_channel(member.guild, member.id)
            if existing_channel is not None:
                await self.notify_duplicate_room(member, lobby_channel, existing_channel)
                return

            category = None
            category_id = profile["target_category_id"]
            if category_id:
                category = member.guild.get_channel(int(category_id))
                if not isinstance(category, discord.CategoryChannel):
                    category = None

            if category is None:
                category = lobby_channel.category

            guild_config = self.storage.get_guild_config(member.guild.id)
            prefix = DEFAULT_TEMP_CHANNEL_PREFIX
            if guild_config and guild_config["temp_channel_prefix"] is not None:
                prefix = str(guild_config["temp_channel_prefix"]).strip()

            temp_channel_name = f"{member.display_name}'s Yap"
            if prefix:
                temp_channel_name = f"{prefix} {temp_channel_name}"

            temp_channel = await member.guild.create_voice_channel(
                name=temp_channel_name,
                category=category,
                reason=f"YapHub temp VC for user {member.id}",
            )

            self.storage.create_active_temp_channel(
                channel_id=temp_channel.id,
                guild_id=member.guild.id,
                profile_id=str(profile["id"]),
                owner_user_id=member.id,
            )
            self.active_temp_channel_ids.add(temp_channel.id)

            try:
                await member.move_to(temp_channel, reason="Moved to newly created Yap room")
            except (discord.Forbidden, discord.HTTPException):
                logger.exception(
                    "Failed to move user %s into temp channel %s", member.id, temp_channel.id
                )
                try:
                    await temp_channel.delete(reason="Cleanup after failed move")
                except (discord.Forbidden, discord.HTTPException):
                    logger.exception(
                        "Failed to cleanup temp channel %s after failed move", temp_channel.id
                    )
                self.storage.delete_active_temp_channel(temp_channel.id)
                self.active_temp_channel_ids.discard(temp_channel.id)

    async def cleanup_temp_channel(self, channel: discord.VoiceChannel) -> None:
        if channel.id not in self.active_temp_channel_ids:
            return

        if len(channel.members) != 0:
            self.storage.touch_active_temp_channel(channel.id)
            return

        try:
            await channel.delete(reason="YapHub deleting empty temp VC")
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Failed to delete empty temp VC %s", channel.id)
            return

        self.storage.delete_active_temp_channel(channel.id)
        self.active_temp_channel_ids.discard(channel.id)


def require_manage_channels(interaction: discord.Interaction) -> bool:
    return bool(
        interaction.guild
        and isinstance(interaction.user, discord.Member)
        and interaction.user.guild_permissions.manage_channels
    )


def build_lobby_name(_: str) -> str:
    return JOIN_TO_CREATE_NAME


class ProfileGroup(app_commands.Group):
    def __init__(self, bot: YapHubBot) -> None:
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


class YapGroup(app_commands.Group):
    def __init__(self, bot: YapHubBot) -> None:
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


bot = YapHubBot()


@bot.event
async def on_ready() -> None:
    if not bot.started_once:
        await bot.tree.sync()
        await bot.load_runtime_cache()
        await bot.reconcile_active_temp_channels()
        if not reconcile_loop.is_running():
            reconcile_loop.start()
        bot.started_once = True

    logger.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "unknown")


@tasks.loop(minutes=RECONCILE_INTERVAL_MINUTES)
async def reconcile_loop() -> None:
    await bot.wait_until_ready()
    await bot.reconcile_active_temp_channels()


@reconcile_loop.before_loop
async def before_reconcile_loop() -> None:
    await bot.wait_until_ready()


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    if member.bot:
        return

    if after.channel and after.channel.id in bot.profile_cache:
        profile = bot.profile_cache[after.channel.id]
        await bot.create_temp_room(member, after.channel, profile)

    if before.channel and before.channel.id in bot.active_temp_channel_ids:
        await bot.cleanup_temp_channel(before.channel)


if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set.")


bot.run(TOKEN)
