import json
from console_rub.print import *
from collections import defaultdict

from collections import defaultdict


def analyze_tracks_data(tracks_data):
    """
    Analyze tracks data to count unique clips, find clips with null metadata,
    missing files, and missing URLs (including nested metadata URLs).
    """
    unique_clips_per_track = defaultdict(set)
    all_unique_clips = set()
    null_metadata_clips = []
    missing_file_clips = []
    missing_url_clips = []

    for track_name, clips in tracks_data.items():
        if not isinstance(clips, list):
            continue

        for clip in clips:
            if not isinstance(clip, dict):
                continue

            name = clip.get("name", "Unknown")
            metadata = clip.get("clip_metadata")
            is_missing = clip.get("missing_file", False)

            # 1. Check top-level URL
            primary_url = clip.get("url")

            # 2. Check nested URLs in metadata
            # We use .get() safely in case metadata is None or not a dict
            metadata_urls = []
            if isinstance(metadata, dict):
                lyrics_dict = metadata.get("lyrics_dict", {})
                if isinstance(lyrics_dict, dict):
                    metadata_urls = [
                        metadata.get("url"),
                        lyrics_dict.get('video_url'),
                        lyrics_dict.get('album_page_url'),
                        lyrics_dict.get('url'),
                        lyrics_dict.get('item_url')
                    ]

            # Combine all possible URL locations
            all_possible_urls = [primary_url] + metadata_urls

            # A clip has a "valid URL" if at least one of these is non-empty
            has_valid_url = any(url and str(url).strip() for url in all_possible_urls)

            all_unique_clips.add(name)
            unique_clips_per_track[track_name].add(name)

            if metadata is None:
                null_metadata_clips.append(clip)

            if is_missing:
                missing_file_clips.append(clip)

            if not has_valid_url:
                missing_url_clips.append(clip)

    unique_counts_per_track = {track: len(clips) for track, clips in unique_clips_per_track.items()}

    return (
        unique_counts_per_track,
        len(all_unique_clips),
        null_metadata_clips,
        missing_file_clips,
        missing_url_clips
    )

def print_analysis_report(tracks_data):
    """
    Print a comprehensive report of the tracks analysis.
    """
    # Unpack the updated 5-item tuple
    unique_counts, total_count, null_clips, missing_clips, missing_urls = analyze_tracks_data(tracks_data)

    # Calculate total clips (raw count)
    total_clips = sum(len(clips) for clips in tracks_data.values() if isinstance(clips, list))

    # Helper function to deduplicate clips for the printed report
    def get_unique_list(clip_list):
        unique_list = []
        seen_keys = set()
        for clip in clip_list:
            key = (clip.get('name', ''), clip.get('path', ''))
            if key not in seen_keys:
                seen_keys.add(key)
                unique_list.append(clip)
        return unique_list

    # Deduplicate for reporting
    report_null_clips = get_unique_list(null_clips)
    report_missing_files = get_unique_list(missing_clips)
    report_missing_urls = get_unique_list(missing_urls)

    print_gray("TRACKS ANALYSIS REPORT")
    print_gray("=" * 60)

    print_orange(f"\nTOTAL CLIPS ACROSS ALL TRACKS: {total_clips}")
    print_yellow(f"\nTOTAL UNIQUE CLIPS ACROSS ALL TRACKS: {total_count}")

    print_gray("\nSUM OF UNIQUE CLIPS BY TRACK:")
    print_gray("-" * 30)
    for track, count in unique_counts.items():
        print_yellow(f"{track}: {count}")

    # --- MISSING FILES SECTION ---
    print_gray(f"\n CLIPS WITH MISSING FILES ({len(report_missing_files)} unique):")
    print_gray("-" * 40)
    if report_missing_files:
        for i, clip in enumerate(report_missing_files, 1):
            print_red(f"{i}. {clip.get('name')} ")
            print_gray(f"   Path: {clip.get('path', 'N/A')}")
    else:
        print_green("All file paths are valid.")

    # --- MISSING URL SECTION ---
    print_gray(f"\n CLIPS WITH MISSING URLS ({len(report_missing_urls)} unique):")
    print_gray("-" * 40)
    if report_missing_urls:
        for i, clip in enumerate(report_missing_urls, 1):
            print_red(f"{i}. {clip.get('name')} ")
            print_gray(f"   Path: {clip.get('path', 'N/A')}")
    else:
        print_green("All clips have valid URL values.")

    # --- NULL METADATA SECTION ---
    print_gray(f"\n CLIPS WITH NULL METADATA ({len(report_null_clips)} unique):")
    print_gray("-" * 40)
    if report_null_clips:
        for i, clip in enumerate(report_null_clips, 1):
            print_red(f"{i}. Name: {clip.get('name')}")
            print_gray(f"   Path: {clip.get('path', 'N/A')}")
    else:
        print_green("No clips found with null metadata.")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    # Run the analysis
    json_file = 'arrangement_map.json'
    merged_path = '/Users/antropoloops/PycharmProjects/spectrogram_metadata_viewer/data/arrangement_map_merged.json'
    # Load data from JSON file
    with open(json_file, 'r') as f:
        tracks_data = json.load(f)

    print_analysis_report(tracks_data)
