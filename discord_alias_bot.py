# Python
import asyncio
import logging
import tomllib
from dataclasses import dataclass
from typing import Optional

import discord  # pip install -U "discord.py>=2.3"

from discord_alias_responder_module import DiscordAliasResponder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("discord-daemon")


@dataclass(frozen=True)
class DiscordConfig:
    token: str
    channel_id: int
    cards_csv: str
    reply_footer: str = ""
    max_cards_per_message: int = 8  # safety guard
    # If true, don't actually send; log output only
    dry_run: bool = False


def load_config(path: str = "config.toml") -> DiscordConfig:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    dcfg = data["discord"]
    return DiscordConfig(
        token=str(dcfg["token"]),
        channel_id=int(dcfg["channel_id"]),
        cards_csv=str(dcfg["cards_csv"]),
        reply_footer=str(dcfg.get("reply_footer", "")),
        max_cards_per_message=int(dcfg.get("max_cards_per_message", 8)),
        dry_run=bool(dcfg.get("dry_run", False)),
    )


class AliasBot(discord.Client):
    def __init__(self, conf: DiscordConfig, responder: DiscordAliasResponder):
        intents = discord.Intents.default()
        intents.message_content = True  # required to read message content
        super().__init__(intents=intents)
        self.conf = conf
        self.responder = responder

    async def on_ready(self):
        logger.info("Logged in as %s (id=%s)", self.user, getattr(self.user, "id", "?"))
        # Optional sanity check for channel
        ch = self.get_channel(self.conf.channel_id)
        if ch is None:
            logger.warning("Target channel_id=%s not found in cache; bot will still handle events when they arrive.",
                           self.conf.channel_id)

    async def on_message(self, message: discord.Message):
        try:
            # Ignore our own messages and DMs
            if message.author.id == self.user.id:
                return
            if message.guild is None:
                return
            if message.channel.id != self.conf.channel_id:
                return

            reply = self.responder.handle_message(message.content)
            if not reply:
                return

            # Optional cap on number of cards per message: split by two blank lines
            blocks = [b for b in reply.split("\n\n") if b.strip()]
            if len(blocks) > self.conf.max_cards_per_message:
                blocks = blocks[: self.conf.max_cards_per_message]
                reply = "\n\n".join(blocks)

            if self.conf.dry_run:
                logger.info("[DRY RUN] Would reply to #%s (%s):\n%s",
                            message.channel, message.id, reply)
                return

            await message.reply(reply, mention_author=False)

        except discord.HTTPException as e:
            logger.exception("Discord HTTPException while replying: %s", e)
        except Exception:
            logger.exception("Unexpected error in on_message")

    async def start_with_reconnect(self, token: str):
        # Robust auto-reconnect loop
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
