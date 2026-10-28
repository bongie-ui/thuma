Read this $kind_label (it may be handwritten or photographed at an angle) and extract it exactly as written.

- supplier: the business or school that issued it.
- items: every line with name, quantity and unit_price. If only a line total is shown, divide by the
  quantity. Set key to one of these item keys when the line is clearly that item, otherwise null: $item_keys
- total: the document total as written (null if none).
- currency: ISO code (e.g. USD).
- date: as written, or null.
- notes: anything unclear (illegible numbers, crossed-out prices) in plain words, or "".
Never guess a number you cannot read; use null and explain in notes.
