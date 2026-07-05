---
name: transaction-fetcher
description: |
  Normalizes the user's financial input — typed manual entry, MCP-fetched
  sample transactions, or one or more uploaded statement documents (bank,
  utility, mortgage, credit card) — into one compact JSON object
  (income, dependants, expenses, debts, notes). Use this skill whenever
  raw financial input needs to become the pipeline's normalized starting
  point. Do NOT use it to analyze, categorize with judgment beyond what a
  document states, or recommend anything — that's every later agent's job.
version: 1.0.0
license: MIT
metadata:
  author: financial-coach-agent
---
# Transaction Fetcher

## When to use
- First step of the pipeline, before security screening or clarification.
- Whenever the user provides financial data in any combination of: typed text, an MCP transaction fetch, or uploaded documents.

## When NOT to use
- Don't compute savings rates, category percentages, debt payoff plans, or any recommendation — restate only what's given or directly stated on a document.
- Don't invent a value that isn't derivable from the input — leave a field out rather than guess.

## Workflow
1. If the user asks to fetch/import transactions rather than typing or uploading, call `get_transactions` and restate its result as compact JSON — no other text.
2. If the user provided manual text, uploaded documents, or both, read everything provided (including every attached document) before producing any output.
3. **Identify each document's type** from its content — bank statement, utility bill, mortgage statement, or credit card statement — you won't be told which is which in advance.
4. **Income**: extract from the bank statement's deposit/credit lines (e.g. paycheck deposits). Sum all deposits into a single `income` figure unless the user's text says otherwise.
5. **Utility bills**: extract each bill's amount due into its own named expense category matching the utility type (e.g. `Electricity`, `Water`) — one category per bill, not a combined "Utilities" figure, unless only one utility bill is present.
6. **Mortgage statement**: extract the monthly payment amount into a `Mortgage` expense category.
7. **Credit card statements**: extract each statement's own transaction list into expense categories by type (e.g. `Eating Out`, `Subscriptions`) — combine same-type spending across multiple cards into one category total (e.g. one `Eating Out` figure covering both cards' dining transactions, not two separate per-card entries). Extract each card's `balance`, `min_payment` (or minimum payment due), and `interest_rate`/APR into a `debts` entry, one per card.
8. **Double-counting rule — the most important step**: the bank statement will show a debit line for the mortgage payment and for each credit card's payment. These are the *same* dollars you already captured in steps 6/7 from the mortgage/credit-card statements' own numbers — never add them again as a separate expense just because they also appear as a bank-statement debit. Before including any bank-statement debit line as its own expense category, check whether its amount and payee match a mortgage or credit-card payment you already extracted directly from that statement; if so, skip it (it's already counted). Only bank-statement debits that don't correspond to a mortgage/credit-card statement you have should become their own expense category.
   - Example: bank statement shows a $1,500.00 debit to "Homestead Mortgage Co." and the mortgage statement itself shows a $1,500.00 monthly payment — this is ONE expense (`Mortgage: 1500`), not two. Do not also add a `Mortgage Payment (bank)` category.
9. Anything the input mentions that doesn't fit `income`/`expenses`/`debts` (e.g. where a surplus goes, an existing emergency fund) goes verbatim into a `notes` field — never dropped, never folded into `expenses`.
10. Anything not derivable from any document or the typed text (e.g. dependants) is simply left out — do not guess. The pipeline's clarification step will ask about it if needed.
11. Return ONLY the resulting JSON — no commentary, no analysis, no formatting beyond the JSON itself.

## Examples
- Bank statement shows a $1,500 debit to "Homestead Mortgage Co." and a $150 debit to "Visa Card Payment"; a separate mortgage statement shows a $1,500 monthly payment; a separate Visa statement shows balance $2,000, minimum payment $150, APR 22%, with $300 of dining transactions and $80 of subscription transactions → `expenses` includes `{"Mortgage": 1500, "Eating Out": 300, "Subscriptions": 80}` (the bank statement's $1,500 and $150 debits are NOT added again), `debts` includes `{"name": "Visa", "amount": 2000, "interest_rate": 22, "min_payment": 150}`.
- Two utility bills (Electric $120, Water $65) with no other documents → `expenses: {"Electricity": 120, "Water": 65}`.

## Output format
Compact JSON: `income`, `dependants` (if known), `expenses` (object of category → amount), `debts` (list of `{name, amount, interest_rate, min_payment}`), `notes` (free text for anything else stated) — same shape whether the source was typed text, MCP data, or documents.

## Anti-patterns to avoid
- Don't double-count a mortgage or credit-card payment that appears both on the bank statement and on that debt's own statement — see the worked example above.
- Don't split one category across documents when it should be combined (e.g. two cards' dining spend into two separate "Eating Out" entries) — combine same-type spending into one category.
- Don't guess a value (e.g. dependants) that isn't stated anywhere in the input.
- Don't add commentary, analysis, or recommendations — that's every later agent's job, never this one's.
