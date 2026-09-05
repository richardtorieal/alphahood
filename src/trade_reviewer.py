"""
AlphaHood — LLM-Assisted Trade Reviewer
Uses Gemini dynamic Flash model chain (same pattern as genai-runner)
to analyze open positions and provide Hold/Trim/Exit recommendations.
Runs 2x daily at 10:30 AM and 3:30 PM CT.
"""
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .risk.portfolio import PortfolioState, Position
from .data.market_data import MarketDataProvider
from .utils.discord_notify import send_review_summary

log = logging.getLogger("alphahood.trade_reviewer")

# ── Constants ──────────────────────────────────────────────────────────────────
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
# Exclude non-text models from the flash chain
EXCLUDED_MODEL_SUFFIXES = ("tts", "audio", "image", "live")


@dataclass
class ReviewResult:
    """Result of an LLM trade review for a single position."""
    symbol: str
    recommendation: str  # "HOLD", "TRIM", "EXIT"
    confidence: float  # 0.0 - 1.0
    reasoning: str
    updated_stop: Optional[float] = None
    suggested_trim_pct: Optional[float] = None  # e.g. 0.5 = trim 50%
    risk_flags: list[str] = field(default_factory=list)


@dataclass
class PortfolioReview:
    """Full portfolio review with rebalance suggestions."""
    timestamp: str
    model_used: str
    position_reviews: list[ReviewResult]
    portfolio_recommendation: str
    rebalance_suggestions: list[str]
    overall_health: str  # "STRONG", "NEUTRAL", "WEAK", "CRITICAL"


def discover_flash_models(client) -> list[str]:
    """
    Dynamically queries available models from Gemini API and returns
    all Flash models ordered by version descending (newest first).
    Same pattern as genai-runner's dynamic model resolver.
    """
    try:
        raw_models = [m.name.replace("models/", "") for m in client.models.list()]
        flash_models = []
        for m in raw_models:
            if "flash" in m and not any(sub in m for sub in EXCLUDED_MODEL_SUFFIXES):
                flash_models.append(m)

        def parse_version(name: str) -> float:
            match = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
            return float(match.group(1)) if match else 0.0

        flash_models.sort(
            key=lambda m: (parse_version(m), "lite" not in m), reverse=True
        )
        if flash_models:
            log.info(f"🔍 Flash chain: {', '.join(flash_models[:5])}")
            return flash_models
    except Exception as err:
        log.warning(f"Dynamic model discovery failed: {err}")

    # Fallback chain
    return [
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite-preview",
    ]


def call_gemini(client, prompt: str, system: str = "") -> tuple[str, str]:
    """
    Call Gemini with dynamic model fallback chain.
    Returns (response_text, model_used).
    """
    from google.genai import types

    cfg = types.GenerateContentConfig(
        temperature=0.3,
        system_instruction=system or None,
    )
    flash_chain = discover_flash_models(client)

    for model_name in flash_chain:
        try:
            log.info(f"🤖 Attempting review with [{model_name}]...")
            resp = client.models.generate_content(
                model=model_name, contents=prompt, config=cfg
            )
            if resp.text:
                log.info(f"✓ Review succeeded using [{model_name}]")
                return resp.text.strip(), model_name
        except Exception as err:
            log.warning(f"Model [{model_name}] failed: {err}")

    log.error("All Flash models in chain failed for trade review.")
    return "", "none"


class TradeReviewer:
    """
    LLM-assisted trade reviewer that analyzes each open position
    using Gemini Flash models and provides actionable recommendations.
    """

    def __init__(self):
        api_key = os.environ.get(GEMINI_API_KEY_ENV, "")
        if not api_key:
            log.warning(f"No {GEMINI_API_KEY_ENV} set; LLM reviews will be skipped.")
            self.client = None
        else:
            from google import genai
            self.client = genai.Client(api_key=api_key)

    def review_position(
        self,
        position: Position,
        market_data: MarketDataProvider,
    ) -> ReviewResult:
        """
        Analyze a single position using Gemini and return a recommendation.
        """
        if not self.client:
            return ReviewResult(
                symbol=position.symbol,
                recommendation="HOLD",
                confidence=0.0,
                reasoning="LLM review unavailable (no API key).",
            )

        # Gather context for the LLM
        pnl_pct = (
            (position.current_price - position.entry_price) / position.entry_price
            if position.entry_price > 0
            else 0.0
        )
        hold_days = (datetime.now() - position.entry_time).days if position.entry_time else 0

        prompt = f"""You are a Senior Swing Trade Analyst reviewing an open position.

POSITION DETAILS:
- Symbol: {position.symbol}
- Strategy: {position.strategy_name}
- Asset Type: {position.asset_type}
- Entry Price: ${position.entry_price:.2f}
- Current Price: ${position.current_price:.2f}
- Unrealized P&L: {pnl_pct:.1%}
- Hold Duration: {hold_days} days
- Stop Loss: {position.stop_loss_pct:.1%}
- Trailing Stop: ${position.trailing_stop_price:.2f if position.trailing_stop_price else 'N/A'}
- Quantity: {position.quantity}

TASK: Provide a concise swing trade review. Respond in EXACTLY this format:
RECOMMENDATION: [HOLD/TRIM/EXIT]
CONFIDENCE: [0.0-1.0]
REASONING: [2-3 sentences on technical posture, momentum, and any catalyst risk]
UPDATED_STOP: [new stop price or UNCHANGED]
RISK_FLAGS: [comma-separated flags or NONE]
"""

        system = (
            "You are a quantitative swing trade analyst. Be decisive and concise. "
            "Favor cutting losers quickly and letting winners run. "
            "Flag any earnings, macro events, or technical breakdowns."
        )

        response_text, model_used = call_gemini(self.client, prompt, system)

        # Parse structured response
        return self._parse_review_response(position.symbol, response_text)

    def review_portfolio(
        self,
        portfolio: PortfolioState,
        market_data: MarketDataProvider,
    ) -> PortfolioReview:
        """
        Run a full portfolio review — analyze each position and provide
        portfolio-level rebalancing suggestions.
        """
        position_reviews: list[ReviewResult] = []

        for symbol, position in portfolio.positions.items():
            review = self.review_position(position, market_data)
            position_reviews.append(review)

        # Portfolio-level analysis
        exits = sum(1 for r in position_reviews if r.recommendation == "EXIT")
        trims = sum(1 for r in position_reviews if r.recommendation == "TRIM")
        holds = sum(1 for r in position_reviews if r.recommendation == "HOLD")

        if exits > len(position_reviews) * 0.5:
            overall_health = "CRITICAL"
            portfolio_rec = "Majority of positions flagged for exit. Consider risk-off."
        elif exits + trims > len(position_reviews) * 0.3:
            overall_health = "WEAK"
            portfolio_rec = "Several positions need attention. Trim exposure."
        elif holds == len(position_reviews):
            overall_health = "STRONG"
            portfolio_rec = "All positions holding well. Maintain current allocation."
        else:
            overall_health = "NEUTRAL"
            portfolio_rec = "Mixed signals. Monitor closely."

        # Build rebalance suggestions
        rebalance: list[str] = []
        options_pct = portfolio.get_options_allocation()
        if options_pct > 0.80:
            rebalance.append(f"Options allocation at {options_pct:.0%} — at limit, avoid new options entries.")
        if portfolio.cash < portfolio.total_equity * 0.10:
            rebalance.append(f"Cash reserve low (${portfolio.cash:.0f}). Consider trimming to free capital.")

        model_used = "dynamic-flash-chain"
        review = PortfolioReview(
            timestamp=datetime.now().isoformat(),
            model_used=model_used,
            position_reviews=position_reviews,
            portfolio_recommendation=portfolio_rec,
            rebalance_suggestions=rebalance,
            overall_health=overall_health,
        )

        # Format and send to Discord
        self._send_discord_review(review)
        return review

    def _parse_review_response(self, symbol: str, text: str) -> ReviewResult:
        """Parse the structured LLM response into a ReviewResult."""
        recommendation = "HOLD"
        confidence = 0.5
        reasoning = text
        updated_stop = None
        risk_flags: list[str] = []

        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("RECOMMENDATION:"):
                rec = line.split(":", 1)[1].strip().upper()
                if rec in ("HOLD", "TRIM", "EXIT"):
                    recommendation = rec
            elif line.startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif line.startswith("REASONING:"):
                reasoning = line.split(":", 1)[1].strip()
            elif line.startswith("UPDATED_STOP:"):
                stop_str = line.split(":", 1)[1].strip()
                if stop_str != "UNCHANGED":
                    try:
                        updated_stop = float(stop_str.replace("$", ""))
                    except ValueError:
                        pass
            elif line.startswith("RISK_FLAGS:"):
                flags_str = line.split(":", 1)[1].strip()
                if flags_str != "NONE":
                    risk_flags = [f.strip() for f in flags_str.split(",")]

        return ReviewResult(
            symbol=symbol,
            recommendation=recommendation,
            confidence=confidence,
            reasoning=reasoning,
            updated_stop=updated_stop,
            risk_flags=risk_flags,
        )

    def _send_discord_review(self, review: PortfolioReview) -> None:
        """Format portfolio review as Discord message."""
        lines = [
            f"📊 **AlphaHood Trade Review** — {review.timestamp[:16]}",
            f"Overall Health: **{review.overall_health}**",
            f"Model: `{review.model_used}`",
            "",
        ]

        for pr in review.position_reviews:
            emoji = {"HOLD": "🟢", "TRIM": "🟡", "EXIT": "🔴"}.get(pr.recommendation, "⚪")
            lines.append(
                f"{emoji} **{pr.symbol}**: {pr.recommendation} "
                f"(conf: {pr.confidence:.0%}) — {pr.reasoning[:100]}"
            )
            if pr.risk_flags:
                lines.append(f"   ⚠️ Flags: {', '.join(pr.risk_flags)}")

        lines.append("")
        lines.append(f"**Portfolio**: {review.portfolio_recommendation}")
        if review.rebalance_suggestions:
            lines.append("**Rebalance**: " + " | ".join(review.rebalance_suggestions))

        send_review_summary("\n".join(lines))
