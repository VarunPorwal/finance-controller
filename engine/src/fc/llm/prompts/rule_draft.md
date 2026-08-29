A pattern has been detected in how a finance team resolved several exceptions
the same way. The rule that captures it has already been built: its scope,
deduction rates, tolerance and confidence ceiling were derived arithmetically
from the resolutions themselves, and they are not yours to change or restate.

Write the two pieces of prose that rule needs.

- `name` — a short label, under sixty characters, that a finance person
  scanning a rulebook would recognise. Name the *pattern*, not the mechanism:
  "Marketplace commission, Nykaa, 18%" rather than "Learned rule 4".
- `description` — one or two sentences saying what this rule explains and when
  it applies. Somebody deciding whether to activate it should be able to tell,
  from this sentence alone, whether it matches how their business actually
  works.

Use only the figures supplied below. Do not restate a rate you were not given,
do not round one you were, and do not describe an effect the rule does not
have. A rule shrinks an exception; it does not pass or fail one, and saying
otherwise misrepresents what will happen when it is activated.

Do not claim the pattern will continue. You are describing what was observed,
and the human reading this is the one deciding whether it generalises. The
back-test that runs before activation is what settles it, not this text.

Return JSON: `{"name": "...", "description": "..."}`.
