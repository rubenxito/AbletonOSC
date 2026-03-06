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
    """Queries the Swinsian SQLite DB for a filename (without extension)."""
    if not os.path.exists(NEW_DB_PATH):
        return None

    try:
        conn = sqlite3.connect(NEW_DB_PATH)
        cursor = conn.cursor()

        # We search the 'filename' column for the base name + any common extension
        # Swinsian usually stores the full filename (e.g., 'song.mp3') in the 'filename' column
        query = "SELECT path FROM TRACK WHERE filename LIKE ? LIMIT 1"

        # We use LIKE with a wildcard to catch 'filename.mp3', 'filename.wav', etc.
        cursor.execute(query, (f"{filename_no_ext}.%",))
        result = cursor.fetchone()
        conn.close()

        if result:
            # Swinsian paths often use a custom URI or absolute path;
            # ensure it's a standard system path.
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
                print_green(f"Found {cleaned_name}")
                return os.path.join(root, f)
    return None

# Set up the client
client = AbletonOSCClient("127.0.0.1", 11000)

# --- FILENAME & PATH UTILITIES ---

def sanitize_name(input_string, force_mp3=False):
    """
    Unified sanitizer for both clip names (no ext) and filenames (with ext).
    """
    timestamp_pattern = r'\s\[\d{4}-\d{2}-\d{2}\s\d{6}\]'
    suffixes = ['_denoisedRX', '_denoiseRX', '_denoised44', '_denoise44', '_denoised', '_denoise']

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
    raw_mp3_filename = clip_name + ".mp3"
    potential_raw_imported = os.path.join(imported_dir, raw_mp3_filename)
    if os.path.exists(potential_raw_imported):
        print_green(f"Found {potential_raw_imported} in {imported_dir}")
        return potential_raw_imported, clip_name, False

    # 2. Try Local Project (Processed/Crop)
    clean_full = sanitize_name(clip_name)
    clean_base = os.path.splitext(clean_full)[0]
    found_path = find_in_processed_subfolders(clean_base, processed_dir)
    if found_path:
        print_magenta(f"Found {found_path} in {processed_dir}")
        return found_path, clean_full, False

    # 3. Try Swinsian SQLite DB (The 250k Library)
    print_gray(f"...Searching Swinsian DB for: {clean_base}")
    db_path = find_in_swinsian_db(clean_base)
    if db_path and os.path.exists(db_path):
        print_yellow(f"Found {db_path} in Swinsian DB")
        return db_path, clean_full, False

    # 4. Last Chance: Fallback Small Folder
    print_magenta(f"...Checking Fallback folder for: {clean_base}")
    fallback_path = find_in_fallback_folder(clean_base)
    if fallback_path:
        print_yellow(f"Found {fallback_path} in Fallback folder")
        return fallback_path, clean_full, False

    # If all fail
    return "NOT_FOUND", clean_full, True


# --- CORE LOGIC ---
def get_arrangement_clips(n_tracks=None):
    results = {}

    # --- AUTO-DETECT TRACK COUNT ---
    if n_tracks is None:
        print_red("No track count provided. Querying Ableton for project size...")
        num_tracks_resp = client.query("/live/song/get/num_tracks")
        if num_tracks_resp:
            # AbletonOSC usually returns a list/tuple: [num_tracks]
            n_tracks = num_tracks_resp[0]
        else:
            print_red("Error: Could not retrieve track count. Defaulting to 0.")
            return {}

    print_orange(f"--- Initiating Scan for {n_tracks} Tracks ---")

    for i in range(n_tracks):
        # 1. Skip Group/Foldable tracks
        # AbletonOSC returns: [track_index, is_foldable_bool]
        is_group_resp = client.query("/live/track/get/is_foldable", [i])
        time.sleep(QUERY_DELAY)
        if is_group_resp and is_group_resp[1]:
            # print(f"Skipping Track {i} (Group/Folder)")
            continue

        # 2. Identify Track
        # Returns: [track_index, name_string]
        name_resp = client.query("/live/track/get/name", [i])
        time.sleep(QUERY_DELAY)
        if not name_resp: continue
        track_name = name_resp[1]

        # 3. Query properties
        # 3. Query properties
        names_raw = client.query("/live/track/get/arrangement_clips/name", [i])
        time.sleep(QUERY_DELAY)
        starts_raw = client.query("/live/track/get/arrangement_clips/start_time", [i])
        time.sleep(QUERY_DELAY)
        ends_raw = client.query("/live/track/get/arrangement_clips/end_time", [i])
        time.sleep(QUERY_DELAY)
        lengths_raw = client.query("/live/track/get/arrangement_clips/length", [i])
        time.sleep(QUERY_DELAY)

        # 2. Slice to remove the track_id [0]
        c_names = names_raw[1:] if names_raw else []
        c_starts = starts_raw[1:] if starts_raw else []
        c_ends = ends_raw[1:] if ends_raw else []
        c_lengths = lengths_raw[1:] if lengths_raw else []

        track_clips = []
        for n, s, e, l in zip(c_names, c_starts, c_ends, c_lengths):
            resolved_path, final_name, is_missing = resolve_path_from_name(n)

            # 3. Calculate the actual footprint on the timeline
            # This accounts for looped clips or resized (shortened) clips
            timeline_duration = e - s

            audio_metadata = get_id3tags(resolved_path)

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

        results[track_name] = track_clips
        print(f"Track {i} ({track_name}): Found {len(track_clips)} clips.")

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

    with open("arrangement_map2_test.json", "w") as f:
        json.dump(final_data, f, indent=4)

    print("\nFinal JSON generated with deep-searched paths.")