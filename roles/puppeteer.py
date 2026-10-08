"""Puppeteer: spends a token at night to chat as someone else the next day."""

from roles.base import RoleLogic, register


@register("Puppeteer")
class Puppeteer(RoleLogic):
    night_note = "A Puppeteer's puppet: use the puppet op (code swaps who chats tomorrow)."
