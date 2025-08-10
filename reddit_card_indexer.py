from card_index_manager import CardIndex
from card_loader_from_csv import load_cards_from_csv
from reddit_bot_config_loader import load_config
from reddit_comment_reply_streamer import make_reddit, run_stream


def main():
    cfg = load_config()
    cards = load_cards_from_csv(cfg.bot.cards_csv)
    index = CardIndex.build(cards)

    reddit = make_reddit(cfg)

    def lookup_fn(token: str):
        return index.lookup(token)

    run_stream(reddit, cfg, lookup_fn)


if __name__ == "__main__":
    main()
