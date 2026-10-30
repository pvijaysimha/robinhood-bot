"""Which symbols the bot may trade. With a "universe" block in config.json
the list comes from universe.json, which only `bot.cli screen` writes;
otherwise it is config.json's fixed "symbols" list."""
import datetime


def allowed_symbols(config, universe, today):
    """(symbols, buys_blocked). buys_blocked is None or the reason no new
    buys may be made. A stale universe still lists its symbols, so held
    funds keep being managed and are not mistaken for rotated-out ones."""
    if "universe" not in config:
        return list(config["symbols"]), None
    if universe is None:
        return [], "no universe.json yet: run the screen"
    age = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(universe["date"])).days
    max_age = config["universe"]["max_age_days"]
    if age > max_age:
        return list(universe["symbols"]), (f"universe.json is {age} days old (max {max_age}): "
                                           "run the screen")
    return list(universe["symbols"]), None


def bought_symbols(order_log_entries):
    """Symbols the bot has bought before, per logs/orders.jsonl."""
    return {e["symbol"] for e in order_log_entries if e["side"] == "buy"}


def exits(held_symbols, symbols, bought):
    """Held symbols the bot bought that have rotated out of the universe.
    Holdings the bot never bought are left alone."""
    return sorted(s for s in held_symbols if s in bought and s not in symbols)
