# Bin Finder — F001.5 Fixed Workspace

F001.5 finalizes the Windows-local GUI shell before live providers are connected.
No live downloader or provider is enabled yet.

## Workflow numbering

The panels are renumbered by workflow rather than by screen position:

1. Dự án & Kịch bản
2. Danh sách cảnh trong kịch bản
3. Tùy chọn tìm kiếm & nguồn
4. Kết quả tìm kiếm
5. Xem, phân tích & đánh giá cảnh
6. Danh sách cảnh đã chọn
7. Xuất footage

## F001.5 layout changes

- Removed user-draggable splitters from the main workspace.
- The project/scene column is fixed at 330 px.
- The review column is fixed at 650 px so the preview remains wide and stable.
- The source/filter panel has a fixed 250 px height; search results use the remaining center space.
- Search results remain exactly three candidate cards per row.
- The preview now preserves the complete image aspect ratio and never crops the frame.
- Panel 7 export controls are compact: the destination field is shorter and export options use shorter visible labels with full tooltips.
- Selecting a candidate cannot resize the review/export workspace.
- Top navigation renders literal ampersands correctly.

## Existing F001 workflow

- Clicking a script scene refreshes scene-specific candidate results.
- Clicking a candidate previews it in panel 5.
- Choosing the candidate marks its scene selected and updates panel 6.
- Panel 6 keeps exactly one current candidate per scene, sorted by script order, with horizontal scrolling.
- Reselecting a scene replaces its current footage instead of appending a duplicate.

## Sources reserved for F002

YouTube, Storyblocks, Pexels, Pixabay, News/electronic newspapers, and Local library.

## Stable rules

- `scene_id` stays stable when footage is replaced.
- `clip_id` identifies one concrete selected clip.
- Adjacent scenes may not reuse the same source video.
- The same source may return after at least one different source.
- Overlapping ranges from the same source are invalid.
- Final output remains one clean selected-footage folder plus manifest/index files.

## Windows update

Extract this package directly over the existing project directory and keep the existing `.venv`.
No new runtime dependency was added.

Run: `start_bin_finder.cmd`

## Next milestone

F002: provider architecture and real discovery integration.
