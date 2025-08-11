# Python
import asyncio
import logging
import os
import tomllib
from dataclasses import dataclass
from typing import Optional, List

import discord

from discord_alias_responder_module import DiscordAliasResponder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("discord-daemon")

# Pick up LOG_LEVEL from environment if set; default to DEBUG
LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.DEBUG),
                    format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


@dataclass(frozen=True)
class DiscordConfig:
    token: str
    cards_csv: str
    reply_footer: str = ""
    max_cards_per_message: int = 8
    dry_run: bool = False

    # Monitoring scope:
    # - For single channel mode, set channel_id only.
    # - For guild-wide mode, set guild_id (and optionally channel_allowlist).
    guild_id: Optional[int] = None
    channel_id: Optional[int] = None
    channel_allowlist: Optional[List[int]] = None


def load_config(path: str = "config.toml") -> DiscordConfig:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    dcfg = data["discord"]

    # Optional fields for scope
    guild_id = dcfg.get("guild_id", None)
    guild_id = int(guild_id) if guild_id is not None else None

    channel_id = dcfg.get("channel_id", None)
    channel_id = int(channel_id) if channel_id is not None else None

    allowlist = dcfg.get("channel_allowlist", None)
    if allowlist is not None:
        # Coerce items to int safely
        allowlist = [int(x) for x in allowlist]

    return DiscordConfig(
        token=str(dcfg["token"]),
        cards_csv=str(dcfg["cards_csv"]),
        reply_footer=str(dcfg.get("reply_footer", "")),
        max_cards_per_message=int(dcfg.get("max_cards_per_message", 8)),
        dry_run=bool(dcfg.get("dry_run", False)),
        guild_id=guild_id,
        channel_id=channel_id,
        channel_allowlist=allowlist,
    )


class AliasBot(discord.Client):
    def __init__(self, conf: DiscordConfig, responder: DiscordAliasResponder):
        intents = discord.Intents.default()
        intents.message_content = True  # required to read message content for [[...]]
        super().__init__(intents=intents)
        self.conf = conf
        self.responder = responder
        self._allow = set(conf.channel_allowlist or [])

    async def on_ready(self):
        logger.info("Logged in as %s (id=%s)", self.user, getattr(self.user, "id", "?"))
        if self.conf.guild_id:
            logger.info("Monitoring all channels in guild_id=%s%s",
                        self.conf.guild_id,
                        f" (allowlist: {sorted(self._allow)})" if self._allow else "")
            logger.info("Logged in as %s (%s)", self.user, getattr(self.user, "id", "?"))
            guilds = [(g.name, g.id) for g in self.guilds]
            logger.info("Connected to guilds: %s", guilds)
        elif self.conf.channel_id:
            logger.info("Monitoring single channel_id=%s", self.conf.channel_id)
        else:
            logger.warning("No guild_id or channel_id configured; bot will ignore all messages.")

    async def on_message(self, message: discord.Message):
        try:
            if message.author.id == self.user.id:
                return
            if message.guild is None:
                return

            # Guild-wide mode
            if self.conf.guild_id is not None:
                if message.guild.id != self.conf.guild_id:
                    return
                if self._allow and message.channel.id not in self._allow:
                    return
            # Single-channel mode (backward compatible)
            elif self.conf.channel_id is not None:
                if message.channel.id != self.conf.channel_id:
                    return
            else:
                # Nothing configured to monitor
                return

            reply = self.responder.handle_message(message.content)
            if not reply:
                return

            # Optional safety cap
            blocks = [b for b in reply.split("\n\n") if b.strip()]
            if len(blocks) > self.conf.max_cards_per_message:
                reply = "\n\n".join(blocks[: self.conf.max_cards_per_message])

            if self.conf.dry_run:
                logger.info("[DRY RUN] Would reply in #%s (%s)\n%s", message.channel, message.id, reply)
                return

            await message.reply(reply, mention_author=False)

        except discord.HTTPException:
            logger.exception("Discord HTTPException while replying")
        except Exception:
            logger.exception("Unexpected error in on_message")

    async def start_with_reconnect(self, token: str):
        while True:
            try:
                await self.start(token)
            except (discord.ConnectionClosed, asyncio.TimeoutError):
                logger.warning("Connection lost; reconnecting in 5s...", exc_info=True)
                await asyncio.sleep(5)
            except Exception:
                logger.exception("Fatal error; reconnecting in 15s...")
                await asyncio.sleep(15)


def main(config_path: str = "config.toml"):
    conf = load_config(config_path)
    responder = DiscordAliasResponder.from_csv(conf.cards_csv, reply_footer=conf.reply_footer)
    bot = AliasBot(conf, responder)
    asyncio.run(bot.start_with_reconnect(conf.token))


if __name__ == "__main__":
    main()
