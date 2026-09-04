"""Settlement-side review artifacts: what happened after the bet was frozen.

WHY THIS IS NOT `src/report/`
-------------------------------
`src/report/` and `src/analysis/` are CUSTOMER surfaces, and
`tests/test_customer_language.py` scans every string literal in them for
product copy that would overclaim -- including the phrase "win probability",
because this project's own model is uncalibrated and no win-probability
number exists in the product.

The post-mortem is not product copy. It is internal settlement evidence, and
the number it reports is MLB's OWN published win-probability series for a
game that has already finished -- a measured fact about a past game, not a
forecast this project is making about a future one. Putting it under
`src/report/` would force it to either trip that guard or paraphrase the one
term that names its data correctly. Neither is right, so it lives here
instead and the customer-language tripwire keeps its full force over the
surfaces it was written for.
"""
