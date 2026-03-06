"""
Metadata field definitions shared between Ableton_arrangement_scanner.py
and the spectrogram_metadata_viewer pipeline.

METADATA_FIELDS: list of (output_key, [dotted.search.paths]) tuples.
  - Paths are resolved in order; first non-empty value wins.
  - Dotted paths traverse nested dicts (e.g. "clip_metadata.song_title").
  - Bare keys (no dot) are looked up directly on the clip dict.
"""

METADATA_FIELDS = [
    ("title",   ["clip_metadata.song_title", "clip_metadata.album_title", "name", "clip_metadata.title"]),
    ("album",   ["clip_metadata.album_title", "clip_metadata.album"]),
    ("artist",  ["clip_metadata.song_artist", "clip_metadata.artist"]),
    ("country", ["clip_metadata.country"]),
    ("date",    ["clip_metadata.song_date", "clip_metadata.lyrics_dict.date", "clip_metadata.date"]),
    ("url",     ["clip_metadata.url", "clip_metadata.lyrics_dict.item_url", "clip_metadata.lyrics_dict.album_page_url", "clip_metadata.lyrics_dict.url", "clip_metadata.lyrics_dict.album_url", "clip_metadata.lyrics_dict.video_url"]),
]

# Keys in arrangement_map that are not track names
SPECIAL_KEYS = ["master", "cue_points", "song_tempo_values"]
