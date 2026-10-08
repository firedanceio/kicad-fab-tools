# Copyright 2026 Firedance Multimedia LLC
# SPDX-License-Identifier: Apache-2.0
"""Live part data (stock, price tiers, basic/extended) from JLCPCB's parts search.

This uses the same JSON endpoint as JLCPCB's public parts page. It is not a documented API and
may change; every caller treats a failed lookup as "unknown", never as zero stock.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

SEARCH_URL = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"


@dataclass
class Part:
    code: str  # LCSC number, e.g. "C12345"
    model: str
    stock: int
    library: str  # "base" (JLCPCB basic) or "expand" (extended)
    prices: list[dict]  # [{"startNumber", "endNumber", "productPrice"}]

    @property
    def basic(self) -> bool:
        return self.library == "base"

    def unit_price(self, qty: int) -> float:
        """Unit price at `qty` pieces from the price tiers."""
        return tier_price(self.prices, qty)


def tier_price(prices: list[dict], qty: int) -> float:
    if not prices:
        raise ValueError("no price tiers")
    tiers = sorted(prices, key=lambda t: t["startNumber"])
    for t in tiers:
        end = t["endNumber"] if t["endNumber"] > 0 else float("inf")
        if t["startNumber"] <= qty <= end:
            return float(t["productPrice"])
    return float(tiers[0]["productPrice"] if qty < tiers[0]["startNumber"] else tiers[-1]["productPrice"])


def lookup(code: str, timeout: float = 30) -> Part | None:
    """The part with LCSC number `code`, or None if it isn't found."""
    req = urllib.request.Request(
        SEARCH_URL,
        data=json.dumps({"keyword": code, "currentPage": 1, "pageSize": 5}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "kicad-fab-tools"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        data = json.load(res)
    for c in ((data.get("data") or {}).get("componentPageInfo") or {}).get("list") or []:
        if c.get("componentCode") == code:
            return Part(code, c.get("componentModelEn", ""), int(c.get("stockCount") or 0),
                        c.get("componentLibraryType", ""), c.get("componentPrices") or [])
    return None
