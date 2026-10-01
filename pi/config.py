PRICES = {3: 150, 5: 200}  # Store prices as integer cents to avoid floating-point money errors.
PRODUCTS = {(3,): 1, (5,): 2, (3, 3): 3, (3, 5): 4, (5, 5): 5}  # Map whole baskets to proposed MDB product IDs.
ML = {3: 11356, 5: 18927}  # Rounded millilitres for three and five US gallons.
PAYMENT_SECONDS = 90  # Nayax's currently configured vend-result deadline.
STOP_MARGIN_SECONDS = 10  # Stop before the deadline to allow valve settling and payment reporting.
THANK_YOU_SECONDS = 10  # Hold the completed-order state before returning to idle.
