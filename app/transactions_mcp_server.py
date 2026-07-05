"""Stub MCP server exposing sample transaction data for financial-coach-agent.

Local dev/demo only — returns canned transactions, no real bank integration or auth.
Run standalone for manual testing: `uv run python app/transactions_mcp_server.py`
Wired into the agent via StdioServerParameters in app/agent.py.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("transactions")

_SAMPLE_TRANSACTIONS = {
    "default_user": [
        {"date": "2026-06-01", "category": "Housing", "amount": 1500.00},
        {"date": "2026-06-02", "category": "Food", "amount": 320.50},
        {"date": "2026-06-03", "category": "Transportation", "amount": 180.00},
        {"date": "2026-06-05", "category": "Utilities", "amount": 210.00},
        {"date": "2026-06-08", "category": "Entertainment", "amount": 95.00},
        {"date": "2026-06-12", "category": "Healthcare", "amount": 60.00},
        {"date": "2026-06-15", "category": "Food", "amount": 275.25},
        {"date": "2026-06-20", "category": "Personal", "amount": 140.00},
        {"date": "2026-06-25", "category": "Other", "amount": 75.00},
    ]
}


@mcp.tool()
def get_transactions(user_id: str) -> list[dict]:
    """Return sample transactions for a user.

    Args:
        user_id: Identifier for the user whose transactions to fetch.

    Returns:
        A list of {date, category, amount} records. Returns an empty list for
        unknown user_ids rather than fabricating data.
    """
    return _SAMPLE_TRANSACTIONS.get(user_id, [])


if __name__ == "__main__":
    mcp.run(transport="stdio")
