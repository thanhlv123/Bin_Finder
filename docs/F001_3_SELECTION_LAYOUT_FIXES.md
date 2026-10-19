# F001.3 — Ordered selection + stable review layout

This milestone applies the Windows GUI feedback after F001.2.

## Selection strip (panel 7)

- Exactly one current candidate is stored for each scene.
- Re-selecting a scene replaces that scene's previous candidate instead of appending a duplicate.
- Cards are always displayed in script order.
- Sparse selection is preserved naturally: selecting scene 1 and scene 3 shows `1, 3`; selecting scene 2 later inserts it between them.
- Panel 7 uses a horizontal scrollbar only.

## Review panel (panel 3)

- `Từ khóa`, `Đối tượng`, `Điều cần tránh`, and `Gợi ý nguồn` use compact tag chips.
- Preview, metadata, detail tabs, and analysis tabs use stable heights so candidate selection does not resize panels 3/8.

## Search results (panel 5)

- Exactly three candidate cards are shown per row.
- Horizontal scrolling is disabled; additional results continue vertically.

## Export panel (panel 8)

- Panel 8 has a stable compact height so panel 3 does not jump when a candidate is previewed.
