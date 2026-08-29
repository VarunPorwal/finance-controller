Transcribe every transaction row from this bank statement PDF, in the order
they appear on the page, top to bottom, across all pages.

For each row return:

- `txn_date` — the transaction date exactly as printed, `dd/mm/yyyy`
- `value_date` — the value date if the statement has that column, else null
- `narration` — the narration/particulars text **verbatim**
- `chq_ref_no` — the cheque or reference number column, or null
- `withdrawal` — the withdrawal/debit amount **as printed**, or null if blank
- `deposit` — the deposit/credit amount **as printed**, or null if blank
- `closing_balance` — the running balance **as printed**

## What "as printed" means, and why it matters

Copy the amount characters exactly: `1,24,500.00` stays `1,24,500.00`. Do not
strip the commas, do not convert to a plain number, do not multiply by
anything, do not compute paise. A separate piece of code converts these to
integer paise, and it is tested. Your job is transcription; arithmetic is not
yours to do here.

The same applies to the narration. If it is cut off mid-reference — Indian bank
statements truncate narrations at around a hundred characters and frequently
sever a UTR — transcribe the truncated text as it stands. **Do not complete it,
do not guess the missing characters, do not tidy it.** A truncated reference is
information the system uses; a plausibly-completed one is a fabrication that
looks identical.

Exactly one of `withdrawal` and `deposit` carries a value on a normal row. If
both columns look blank, still return the row with both null rather than
dropping it.

## What not to include

Opening-balance lines, closing-balance summary lines, carried-forward markers,
page headers and footers, column headings, subtotals, and any marketing text
are not transaction rows. Skip them.

## If you cannot read something

Transcribe what is legible and leave genuinely unreadable fields null. Do not
fill a gap with a value that would make the running balance work out — the
running balance is checked independently, and a row invented to make the
arithmetic close is the single worst thing you could return. A rejected
extraction is a fine outcome; a plausible wrong one is not.

Return JSON: `{"rows": [ ... ]}`.
