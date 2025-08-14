# Python
import asyncio
import logging
import tomllib
from dataclasses import dataclass
from typing import Optional, List, Tuple

import discord  # pip install -U "discord.py>=2.3"

from discord_alias_responder_module import DiscordAliasResponder
from custom_alias_store import CustomAliasStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("discord-daemon")


@dataclass(frozen=True)
class DiscordConfig:
    token: str
    channel_id: int
    cards_csv: str
    reply_footer: str = ""
    max_cards_per_message: int = 8  # safety guard
    dry_run: bool = False
    # New, optional file for learned aliases
    custom_aliases_csv: Optional[str] = None


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
        custom_aliases_csv=str(dcfg.get("custom_aliases_csv", "")) or None,
    )


def _default_custom_aliases_path(cards_csv: str) -> str:
    # Save next to the main CSV by default
    from pathlib import Path
    p = Path(cards_csv)
    return str(p.with_name("custom_aliases.csv"))


def _extract_alias_specs(msg_text: str) -> List[Tuple[Optional[str], str]]:
    """
    Parses alias lines from the user message.

    Accepted formats (case-insensitive 'Alias:'):
      - Alias: New Alias
      - Alias: Card Name | New Alias
      - Alias: "Card Name" | "New Alias"
    Supports multiple lines; returns a list of (maybe_card_name, alias).
    """
    out: List[Tuple[Optional[str], str]] = []
    for raw_line in msg_text.splitlines():
        line = raw_line.strip()
        if not line.lower().startswith("alias:"):
            continue
        body = line[len("alias:"):].strip()
        # Try explicit "Card | Alias" first
        if "|" in body:
            left, right = body.split("|", 1)
            name = left.strip().strip('"').strip("'")
            alias = right.strip().strip('"').strip("'")
            if alias:
                out.append((name or None, alias))
        else:
            # Only alias provided; card name must be inferred from the replied-to message
            alias = body.strip().strip('"').strip("'")
            if alias:
                out.append((None, alias))
    return out


def _guess_single_card_name_from_text(text: str) -> Optional[str]:
    """
    Tries to extract a single card name from the bot's message text.
    This should work if the bot replied with exactly one card block.
    Heuristics:
      - CSV-style first line: "#123,Name," or "Number,Name,..." -> take the token after first comma
      - A line starting with "Name:" -> take the remainder
      - A bold header like "**Name**:" -> take text inside (best effort)
    """
    import re

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None

    # Heuristic 1: CSV-ish first data line like "#001,Colonizer Training Camp,..."
    first = lines[0]
    if "," in first:
        parts = [p.strip() for p in first.split(",")]
        if len(parts) >= 2:
            # If the first part looks like a card number tag, take the second as name
            if re.fullmatch(r"#?\d{1,4}", parts[0]):
                maybe_name = parts[1]
                return maybe_name or None

    # Heuristic 2: look for "Name: X"
    for ln in lines[:5]:
        m = re.match(r"(?i)name\s*:\s*(.+)$", ln)
        if m:
            return m.group(1).strip()

    # Heuristic 3: bold header "**X**:" at top
    m = re.match(r"^\*{2}(.+?)\*{2}\s*:\s*", first)
    if m:
        return m.group(1).strip()

    return None


class AliasBot(discord.Client):
    def __init__(self, conf: DiscordConfig, responder: DiscordAliasResponder, alias_store: CustomAliasStore):
        intents = discord.Intents.default()
        intents.message_content = True  # required to read message content
        super().__init__(intents=intents)
        self.conf = conf
        self.responder = responder
        self.alias_store = alias_store

        # Apply all known custom aliases to the responder if it supports it
        self._push_all_custom_aliases_to_responder()

    def _push_all_custom_aliases_to_responder(self):
        if hasattr(self.responder, "register_custom_alias"):
            for name, aliases in self.alias_store.all_aliases().items():
                for alias in aliases:
                    try:
                        self.responder.register_custom_alias(name, alias)  # type: ignore[attr-defined]
                    except Exception:
                        logger.exception("Failed applying custom alias %r -> %r to responder", name, alias)

    async def on_ready(self):
        logger.info("Logged in as %s (id=%s)", self.user, getattr(self.user, "id", "?"))
        ch = self.get_channel(self.conf.channel_id)
        if ch is None:
            logger.warning("Target channel_id=%s not found in cache; bot will still handle events when they arrive.",
                           self.conf.channel_id)

    async def on_message(self, message: discord.Message):
        try:
            if message.author.id == self.user.id:
                return
            if message.guild is None:
                return
            if message.channel.id != self.conf.channel_id:
                return

            # 1) Handle "Alias:" teaching replies
            if message.reference and "alias:" in message.content.lower():
                await self._handle_alias_reply(message)
                return

            # 2) Normal flow: use the responder to answer queries
            reply = self.responder.handle_message(message.content)
            if not reply:
                return

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

    async def _handle_alias_reply(self, message: discord.Message):
        # Ensure the reply references one of our bot messages
        ref = message.reference
        if not ref:
            return
        # Discord may or may not pre-resolve the message
        target_msg = ref.resolved if isinstance(ref.resolved, discord.Message) else None
        if target_msg is None:
            try:
                target_msg = await message.channel.fetch_message(ref.message_id)  # type: ignore[arg-type]
            except Exception:
                logger.warning("Could not fetch referenced message for alias processing.")
                return

        if not target_msg.author or target_msg.author.id != self.user.id:
            # Only accept alias replies to our own messages
            return

        alias_specs = _extract_alias_specs(message.content)
        if not alias_specs:
            return

        # If any spec lacks a card name, try to infer from the referenced message (single-card replies)
        inferred_name = None
        if any(n is None for n, _a in alias_specs):
            inferred_name = _guess_single_card_name_from_text(target_msg.content)

        added_count = 0
        errors: List[str] = []

        for maybe_name, alias in alias_specs:
            name = maybe_name or inferred_name
            if not name:
                errors.append(f'Could not determine card name for alias "{alias}". '
                              f'Use: Alias: Card Name | {alias}')
                continue

            # Persist to CSV
            try:
                is_new = self.alias_store.add_alias(name, alias)
                # Push to responder if supported for immediate effect
                if hasattr(self.responder, "register_custom_alias"):
                    try:
                        self.responder.register_custom_alias(name, alias)  # type: ignore[attr-defined]
                    except Exception:
                        logger.exception("Responder rejected alias %r -> %r", name, alias)
                if is_new:
                    added_count += 1
            except Exception:
                logger.exception("Failed to add alias %r -> %r", name, alias)
                errors.append(f'Failed to save alias "{alias}" for "{name}".')

        # Acknowledge to the user
        if self.conf.dry_run:
            logger.info("[DRY RUN] Would add %s aliases; errors: %s", added_count, errors)
            return

        feedback = []
        if added_count:
            feedback.append(f"Added {added_count} alias(es).")
        if errors:
            feedback.append("\n".join(errors))
        if not feedback:
            feedback.append("No new aliases added (duplicates ignored).")

        try:
            await message.add_reaction("👍")
        except Exception:
            pass

        try:
            await message.reply("\n".join(feedback), mention_author=False)
        except Exception:
            logger.debug("Could not send feedback message for alias addition.")

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
    # Pick a default path if not provided
    custom_path = conf.custom_aliases_csv or _default_custom_aliases_path(conf.cards_csv)

    responder = DiscordAliasResponder.from_csv(conf.cards_csv, reply_footer=conf.reply_footer)
    alias_store = CustomAliasStore(custom_path)

    bot = AliasBot(conf, responder, alias_store)
    asyncio.run(bot.start_with_reconnect(conf.token))


if __name__ == "__main__":
    main()
