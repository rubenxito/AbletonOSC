import os
import re
import json
from client import AbletonOSCClient
from console_rub.print import *
import sqlite3
import shutil
import urllib.parse
import time
QUERY_DELAY = 0.03  # 30ms
from metadata.id3_read import get_id3tags
from pathlib import Path
from collections import defaultdict
from analyze_metadata import *

# --- METADATA UTILITIES ---
# LOAD the extra metadata for missing files
with open('jsons/missing_metadata.json', 'r', encoding='utf-8') as file:
    missing_metadata = json.load(file)

# --- SEARCH PATH UTILITIES ---

def sync_swinsian_db(source_path, dest_path):
    """
    Checks if the destination DB is older than the source DB.
    Copies source to destination if an update is needed.
    """
    try:
        # Check if source exists
        if not os.path.exists(source_path):
            print_red(f"Error: Swinsian source DB not found at {source_path}")
            return False

        # If destination doesn't exist, or source is newer than destination
        if not os.path.exists(dest_path) or os.path.getmtime(source_path) > os.path.getmtime(dest_path):
            print_gray("Swinsian DB out of date or missing. Syncing...")

            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            # Copy the file (preserving metadata like timestamps)
            shutil.copy2(source_path, dest_path)
            print_green(f"Successfully synced DB to: {dest_path}")
        else:
            print_gray("Swinsian DB is up to date. Proceeding...")

        return True
    except Exception as e:
        print_red(f"Failed to sync database: {e}")
        return False

def find_in_swinsian_db(filename_no_ext):
    """Queries the Swinsian SQLite DB for a filename specifically within the 'path' field."""
    if not os.path.exists(NEW_DB_PATH):
        return None

    try:
        # Use a context manager (with statement) to handle the connection automatically
        with sqlite3.connect(NEW_DB_PATH) as conn:
            cursor = conn.cursor()

            # Targeted query: only looks at the 'path' column
            query = "SELECT path FROM TRACK WHERE path LIKE ? LIMIT 1"

            # Use wildcards to find the filename anywhere within the path string
            search_term = f"%{filename_no_ext}%"

            cursor.execute(query, (search_term,))
            result = cursor.fetchone()

            if result:
                # result[0] is the path; we clean up the file URI prefix
                return result[0].replace("file://", "")

    except Exception as e:
        print_red(f"DB Error: {e}")

    return None

def find_in_fallback_folder(target_name_no_ext):
    """A standard shallow/deep search for a specific smaller folder."""
    extensions = ['.wav', '.aif', '.mp3']
    for root, _, files in os.walk(FALLBACK_SEARCH_PATH):
        for f in files:
            name, ext = os.path.splitext(f)
            cleaned_name = sanitize_filename(name)
            if target_name_no_ext in cleaned_name and ext.lower() in extensions:
                print_green(f"   Found {cleaned_name}")
                return os.path.join(root, f)
    return None

# Set up the client
client = AbletonOSCClient("127.0.0.1", 11000)

# --- FILENAME & PATH UTILITIES ---

def sanitize_name_old(input_string, force_mp3=False):
    """
    Unified sanitizer for both clip names (no ext) and filenames (with ext).
    """
    timestamp_pattern = r'\s\[\d{4}-\d{2}-\d{2}\s\d{6}\]'
    suffixes = ['_noise2', '_denoisedRX', '_denoiseRX', '_denoised44', '_denoise44', '_denoised', '_denoise']

    # 1. Separate extension if it exists
    base, ext = os.path.splitext(input_string)

    # 2. Strip Timestamp from the base
    base = re.sub(timestamp_pattern, '', base)

    # 3. Strip Suffixes
    # We check the end of the base string
    for s in suffixes:
        if base.endswith(s):
            base = base[: -len(s)]
            break  # Catch the longest/first match and exit loop

    # 4. Reconstruct
    if force_mp3:
        return base + ".mp3"

    # Return base + extension (ext will be empty if input was just a clip name)
    return base + ext

def sanitize_name(input_string, force_mp3=False):
    timestamp_pattern = r'\s\[\d{4}-\d{2}-\d{2}\s\d{6}\]'
    suffixes_pattern = r'(_noise2|_denoisedRX|_denoiseRX|_denoised44|_denoise44|_denoised|_denoise)$'

    # 1. Clean the string directly (since there is no extension to protect)
    base = re.sub(timestamp_pattern, '', input_string).strip()

    # 2. Strip Suffixes
    base = re.sub(suffixes_pattern, '', base)

    # 3. Add extension if forced, otherwise return as is
    return base + ".mp3" if force_mp3 else base

def sanitize_filename(filename):
    # 1. Decode URL characters (%28 -> (, %29 -> ))
    clean_name = urllib.parse.unquote(filename)

    # 2. Remove the known "junk" patterns and extra extensions
    # This regex looks for .240p, .vp9, and any .mp3 that isn't at the very end
    # It also handles .480p, .720p, etc.
    clean_name = re.sub(r'\.\d{3,4}p|\.vp\d|\.mp3(?!\.\w+$)', '', clean_name)

    # 3. Optional: Replace underscores with spaces if you prefer "The Singing Fool"
    # clean_name = clean_name.replace('_', ' ')

    return clean_name

def find_in_processed_subfolders(target_name_no_ext, processed_root):
    """Recursively walks through all subfolders in Processed to find a matching file."""
    extensions = ['.wav', '.aif', '.mp3']

    for root, dirs, files in os.walk(processed_root):
        for filename in files:
            # print_gray(filename)
            name, ext = os.path.splitext(filename)
            # Check if name matches (ignoring extension) and is a valid audio type
            if name == target_name_no_ext and ext.lower() in extensions:
                return os.path.join(root, filename)
    return None

def resolve_path_from_name(clip_name):
    imported_dir = os.path.join(SAMPLES_BASE_PATH, "Imported")
    processed_dir = os.path.join(SAMPLES_BASE_PATH, "Processed")



    # 1. Try Local Project (Imported)
    clean_full = sanitize_name(clip_name, force_mp3=True)
    potential_raw_imported = os.path.join(imported_dir, clean_full)
    if os.path.exists(potential_raw_imported):
        print_green(f"   Found {potential_raw_imported}")
        return potential_raw_imported, clean_full, False
    else:
        print_red(f"   Could not find {potential_raw_imported} in imported folder")

    # 2. Try Local Project (Processed/Crop)
    clean_full = sanitize_name(clip_name)
    clean_base = os.path.splitext(clean_full)[0]
    found_path = find_in_processed_subfolders(clean_base, processed_dir)
    if found_path:
        print_green(f"   Found {found_path} in {processed_dir}")
        return found_path, clean_full, False
    else:
        print_red(f"   Could not find {found_path} in processed folder")

    # 3. Try Swinsian SQLite DB (The 250k Library)
    print_gray(f"   ...Searching Swinsian DB for: {clean_base}")
    db_path = find_in_swinsian_db(clean_base)
    if db_path and os.path.exists(db_path):
        print_green(f"   Found {db_path} in Swinsian DB")
        return db_path, clean_full, False
    else:
        print_red(f"   Could not find {clean_base} path in Swinsian")


    # 4. Last Chance: Fallback Small Folder
    print_magenta(f"   ...Checking Fallback folder for: {clean_base}")
    fallback_path = find_in_fallback_folder(clean_base)
    if fallback_path:
        print_green(f"   Found {fallback_path} in Fallback folder")
        return fallback_path, clean_full, False
    else:
        print_red(f"   Could not find {clean_base} in Fallback folder")

    # If all fail
    print_red(f"   ...file not found")
    return "NOT_FOUND", clean_full, True

def last_metadata_check(audio_path):
    '''
    if metadata is null after audio_metadata = get_id3tags(resolved_path)
    perform a second sanitize process and search in swinsian again
    sometimes, a unsanitized name is in LIVE folders with no metadata
    '''
    filename_no_ext = Path(audio_path).stem
    filename = os.path.basename(audio_path)
    clean_filename = sanitize_name(filename)

    # 3. Try Swinsian SQLite DB (The 250k Library)
    print_gray(f"   ...Searching Swinsian DB for: {clean_filename}")
    db_path = find_in_swinsian_db(clean_filename)
    if db_path and os.path.exists(db_path):
        print_green(f"   Found {db_path} in Swinsian DB")
        return db_path

    # 4. Last Chance: Fallback Small Folder
    print_gray(f"   ...Checking Fallback folder for: {clean_filename}")
    fallback_path = find_in_fallback_folder(clean_filename)
    if fallback_path:
        print_green(f"   Found {fallback_path} in Fallback folder")
        return fallback_path

    # If all fail
    return None

# --- CORE LOGIC ---

def get_master_data():
    master_data = {}

    master_data['arr_loop_start'] = client.query("/live/song/get/loop_start")[0]
    master_data['arr_loop_length'] = client.query("/live/song/get/loop_length")[0]
    master_data['song_length'] = client.query("/live/song/get/song_length")[0]
    master_data['song_tempo'] = client.query("/live/song/get/tempo")[0]

    return master_data

def get_cue_points():
    cue_lists_raw = client.query("/live/song/get/cue_points")
    # Convert raw tuple to dictionary with keys ordered by values (ascending)
    cue_dict = dict(sorted({cue_lists_raw[i]: cue_lists_raw[i + 1] for i in range(0, len(cue_lists_raw), 2)}.items(), key=lambda item: item[1]))
    print(cue_dict)
    return cue_dict

def get_arrangement_clips(n_tracks=None):
    results = {}

    # --- AUTO-DETECT TRACK COUNT ---
    if n_tracks is None:
        print_red("No track count provided. Querying Ableton for project size...")
        num_tracks_resp = client.query("/live/song/get/num_tracks")
        if num_tracks_resp:
            n_tracks = num_tracks_resp[0]
        else:
            print_red("Error: Could not retrieve track count. Defaulting to 0.")
            return {}

    print(f"--- Initiating Scan for {n_tracks} Tracks ---\n")

    # Step 1: Process tracks in order to detect groups and their children
    current_group = None
    group_stack = []  # Keep track of nested groups if needed

    for i in range(n_tracks):
        # Get track properties
        is_foldable_resp = client.query("/live/track/get/is_foldable", [i])
        time.sleep(QUERY_DELAY)

        name_resp = client.query("/live/track/get/name", [i])
        time.sleep(QUERY_DELAY)

        if not name_resp:
            continue

        track_name = name_resp[1]

        # Check if this is a group track
        is_foldable = is_foldable_resp and is_foldable_resp[1] if is_foldable_resp else False

        if is_foldable:
            # This is a group track - set it as current group
            current_group = {
                "index": i,
                "name": track_name
            }
            print_orange(f"Found Group: {track_name}")
            print_orange(20 * '_ ')
        else:
            # This is a regular track - check if it's grouped
            is_grouped_resp = client.query("/live/track/get/is_grouped", [i])
            time.sleep(QUERY_DELAY)

            is_grouped = is_grouped_resp and is_grouped_resp[1] if is_grouped_resp else False

            # Determine full track name with group prefix
            if is_grouped and current_group:
                # This track belongs to the current group
                full_track_name = f"{current_group['name']} - {track_name}"
                print_orange(f"Track {i}: {full_track_name} (belongs to group)")
                print_orange(20 * '_ ')
            elif not is_grouped:
                # This track is not grouped
                full_track_name = track_name
                print_yellow(f"Track {i}: {full_track_name} (ungrouped)")
                print_yellow(20*'_ ')
                # Reset current group when we hit an ungrouped track (if needed)
                # But keep the last group in case there are multiple ungrouped tracks
            else:
                # This track is grouped but no current group - use fallback
                full_track_name = track_name
                print_magenta(f"Track {i}: {full_track_name} (grouped but no parent detected)")
                print_magenta(20 * '_ ')

            # Query arrangement clips for this track
            names_raw = client.query("/live/track/get/arrangement_clips/name", [i])
            time.sleep(QUERY_DELAY)
            starts_raw = client.query("/live/track/get/arrangement_clips/start_time", [i])
            time.sleep(QUERY_DELAY)
            ends_raw = client.query("/live/track/get/arrangement_clips/end_time", [i])
            time.sleep(QUERY_DELAY)
            lengths_raw = client.query("/live/track/get/arrangement_clips/length", [i])
            time.sleep(QUERY_DELAY)

            # Slice off track index from response
            c_names = names_raw[1:] if names_raw else []
            c_starts = starts_raw[1:] if starts_raw else []
            c_ends = ends_raw[1:] if ends_raw else []
            c_lengths = lengths_raw[1:] if lengths_raw else []

            track_clips = []
            for n, s, e, l in zip(c_names, c_starts, c_ends, c_lengths):
                print_yellow(f"\n   {n}: {s} {e} {l}")
                print_yellow(f"   {20 * '. '}")

                resolved_path, final_name, is_missing = resolve_path_from_name(n)

                timeline_duration = e - s

                # read ID3, return None if there is not
                # 1. Primary Attempt
                audio_metadata = get_id3tags(resolved_path)

                # 2. Secondary Attempt (Last Check Path)
                if not audio_metadata:
                    print_red(f"   ...no metadata in {resolved_path}, checking last_check_path...")
                    last_check_path = last_metadata_check(resolved_path)
                    if last_check_path:
                        audio_metadata = get_id3tags(last_check_path)

                # 3. Final Attempt (Cache/Dictionary Lookup)
                if not audio_metadata:
                    audio_metadata = missing_metadata.get(final_name)
                    if audio_metadata:
                        print_green(f"   Found metadata for {final_name} in external json")

                # Proceed only if we finally have metadata
                if not audio_metadata:
                    print_red(f"   CRITICAL: No metadata found for {n} after all attempts.")
                    continue

                track_clips.append({
                    "name": final_name,
                    "start": s,
                    "end": e,
                    "actual_duration": timeline_duration,
                    "loop_length": l,  # Keeping this for reference
                    "path": resolved_path,
                    "missing_file": is_missing,
                    "clip_metadata": audio_metadata,
                })

            results[full_track_name] = track_clips
            print_gray(20 * '_ ')
            print_gray(f"Track {i} ({full_track_name}): Found {len(track_clips)} clips.\n\n")

    # get master data
    results['master'] = get_master_data()

    # get cue points
    results['cue_points'] = get_cue_points()

    return results


if __name__ == "__main__":
    # --- DATABASE & FALLBACK CONFIG ---
    # Ableton Project's Sample folder
    project_folder = '/Users/antropoloops/Desktop/antropoloops/Box Sync/0 songs/70 Epica/noise_test_120_44_1 Project'
    SAMPLES_BASE_PATH = f"{project_folder}/samples/"
    # Swinsian DB copy paths
    SWINSIAN_DB_PATH = '/Users/antropoloops/Library/Application Support/Swinsian/Library.sqlite'
    NEW_DB_PATH = '/Users/antropoloops/Desktop/swinsian_db_copy/Library_ml.sqlite'

    ### UPDATE DB if has changed
    sync_swinsian_db(SWINSIAN_DB_PATH, NEW_DB_PATH)

    # folder to search other audio files
    FALLBACK_SEARCH_PATH = '/Volumes/ssd4tb/varios/4_libraries'

    # OPTIONS:
    # 1. get_arrangement_clips()      <- Scans everything
    # 2. get_arrangement_clips(2)     <- Scans first 2 tracks

    final_data = get_arrangement_clips()
    ####################################



    # saves json with raw clip metadata
    with open("arrangement_map_raw_metadata.json", "w") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=4)

    print("\nFinal JSON generated with deep-searched paths.")

    ### BUILD lean arrangement_map.json + clip_metadata_ref.json
    from metadata_fields import METADATA_FIELDS, SPECIAL_KEYS

    def _extract_nested(obj, dotted_path):
        parts = dotted_path.split(".")
        cur = obj
        for p in parts:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return None
        return cur if cur not in (None, "", []) else None

    clip_metadata_ref = {}
    lean_data = {}
    for key, value in final_data.items():
        if key in SPECIAL_KEYS or not isinstance(value, list):
            lean_data[key] = value
            continue
        lean_clips = []
        for clip in value:
            name = clip.get("name", "")
            if name and name not in clip_metadata_ref:
                meta = {}
                for field_name, paths in METADATA_FIELDS:
                    meta[field_name] = ""
                    for path in paths:
                        val = _extract_nested(clip, path) if "." in path else clip.get(path)
                        if val:
                            meta[field_name] = str(val)
                            break
                # url fallback from missing_metadata
                if not meta.get("url"):
                    fallback_url = missing_metadata.get(name, {}).get("url")
                    if fallback_url:
                        meta["url"] = str(fallback_url)
                clip_metadata_ref[name] = meta
            lean_clips.append({k: v for k, v in clip.items() if k != "clip_metadata"})
        lean_data[key] = lean_clips

    # saves only clip time positions
    with open("arrangement_map.json", "w", encoding="utf-8") as f:
        json.dump(lean_data, f, ensure_ascii=False, indent=4)

    # saves unique clip metadata selected for VIZ in metadata_fields.py
    with open("clip_metadata_ref.json", "w", encoding="utf-8") as f:
        json.dump(clip_metadata_ref, f, ensure_ascii=False, indent=4)

    print(f"Lean map  → arrangement_map.json  ({sum(len(v) for v in lean_data.values() if isinstance(v, list))} clips)")
    print(f"Meta ref  → clip_metadata_ref.json ({len(clip_metadata_ref)} unique clips)")

    ### ANALYZE DATA
    print_analysis_report(final_data)
