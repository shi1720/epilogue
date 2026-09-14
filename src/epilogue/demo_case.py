"""The demonstration case: the estate of James Mitchell.

Everything here is fictional. The documents are the kind of shoebox a family
actually brings to this problem: a bank statement, a card statement, and a
stack of mail — each one quietly revealing another account, another renewal,
another institution that doesn't know yet.
"""

SEED_NARRATIVE = """My dad, James Mitchell, passed away on August 30th. He was 78. I'm Sarah
Mitchell, his daughter, and the court has named me executor. I live two states away and I'm
back at work already — I just can't spend every lunch break on hold with another bank.

Dad lived alone at 44 Maple Crest Drive in Columbus, Ohio. The house will be sold, probably in
the spring, so someone needs to keep the lights on until then. I have his mail, his last bank
and credit card statements, and a folder of papers. I ordered certified death certificates —
five copies.

What I'm most afraid of: missing something important, his identity being stolen (my friend
went through that with her mom), and losing his photos — he kept everything in some cloud
account. Please don't delete anything that can't be undone without asking me. And the life
insurance — the funeral cost more than we expected."""

SEED_DOCUMENTS = """=== FIRST HARBOR BANK — STATEMENT (excerpt), August 2026 ===
Account holder: JAMES R MITCHELL — Checking ...4417 / Savings ...9052
Aug 01  DIRECT DEP — FED BENEFIT PAYMENT           +$1,847.00
Aug 03  ACH — OHIO LIGHT & POWER (autopay)            -$96.40
Aug 05  CARD — STREAMFLIX.COM                          -$15.99
Aug 07  ACH — CLEARLINE WIRELESS                       -$38.00
Aug 11  CARD — IRONWORKS FITNESS COLUMBUS              -$42.00
Aug 14  CHECK #2201 — THE DAILY LEDGER (annual)       -$149.00
Aug 21  CARD — PIXELVAULT 2TB PLAN (monthly notice: renews annually Sep 12)
Ending balance (checking): $4,218.55 / (savings): $27,840.12

=== MERIDIAN CARD SERVICES — VISA ...7734, August 2026 (excerpt) ===
Aug 04  STREAMFLIX.COM                                  $15.99
Aug 09  SKYWAY AIRLINES — SEAT UPGRADE                  $49.00
Aug 11  IRONWORKS FITNESS                               $42.00
Aug 26  AMAZON MKTPLACE                                  $23.47
Statement balance: $312.09. Minimum due Sep 20.

=== MAIL FOUND AT THE HOUSE ===
1. Beacon Mutual Life — premium receipt, term life policy BML-88213, insured JAMES R MITCHELL.
   "Your beneficiary designation on file: SARAH MITCHELL, daughter."
2. Skyway Airlines SkyMiles statement — balance 84,210 miles. "Miles expire after 18 months of
   inactivity."
3. Ohio Light & Power — service at 44 MAPLE CREST DR, autopay from First Harbor checking.
4. PixelVault — "Your 2TB plan renews Sep 12 for $119.88. 22,384 photos · 511 videos safely
   stored."
5. Handwritten note on the fridge: "gym — cancel!! they make it impossible"

=== SARAH'S NOTES ===
- Dad was retired (2013, Ohio Bell / pension already paying out). Widowed 2019. No veteran.
- Funeral was Sept 4, paid by me ($9,400) — hoping insurance reimburses.
- I have: 5 certified death certificates, letters testamentary (3 copies), my ID.
"""
