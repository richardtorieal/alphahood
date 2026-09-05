import os
import requests

def send_alert(message: str):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return
    requests.post(webhook_url, json={"content": message})

def send_trade_alert(trade_details):
    send_alert(f"New Trade: {trade_details}")

def send_exit_alert(exit_details):
    send_alert(f"Trade Closed: {exit_details}")

def send_review_summary(review):
    send_alert(f"Review Summary: {review}")

def send_daily_summary(portfolio_stats):
    send_alert(f"Daily Summary: {portfolio_stats}")
