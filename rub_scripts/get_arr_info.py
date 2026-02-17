import os
import re
import json
import threading
from pythonosc import udp_client, dispatcher, osc_server
from console_rub.print import *

IP, SEND_PORT, RECV_PORT = "127.0.0.1", 11000, 11001


class SyncAbleton:
    def __init__(self):
        self.client = udp_client.SimpleUDPClient(IP, SEND_PORT)
        self.data_ready = threading.Event()
        self.last_response = None
        self.dispatcher = dispatcher.Dispatcher()
        self.dispatcher.map("/live/*", self._handle_response)
        self.server = osc_server.ThreadingOSCUDPServer((IP, RECV_PORT), self.dispatcher)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _handle_response(self, addr, *args):
        self.last_response = args[-1] if args else None
        self.data_ready.set()

    def query(self, address, params=None):
        self.data_ready.clear()
        self.client.send_message(address, params if params else [])
        if self.data_ready.wait(timeout=1.0):
            return self.last_response
        return None


def clean_filename(filename, force_mp3=False):
    """Only strips if timestamp or specific denoise suffix is found."""
    # 1. Regex to check for the Ableton timestamp
    timestamp_pattern = r'\s\[\d{4}-\d{2}-\d{2}\s\d{6}\]'
    has_timestamp = re.search(timestamp_pattern, filename)

    # 2. Check for denoise suffixes specifically
    suffixes = ['_denoisedRX', '_denoiseRX', '_denoised44', '_denoise44', '_denoised', '_denoise']
    base, ext = os.path.splitext(filename)

    found_suffix = None
    for s in suffixes:
        if base.endswith(s):
            found_suffix = s
            break

    # If neither exists, and we aren't forcing MP3, return original
    if not has_timestamp and not found_suffix and not force_mp3:
        return filename

    # Perform stripping
    new_base = re.sub(timestamp_pattern, '', base)
    if found_suffix:
        new_base = new_base[: -len(found_suffix)]

    final_ext = ".mp3" if force_mp3 else ext
    return new_base + final_ext


def process_file_path(raw_path):
    if not raw_path or not os.path.exists(raw_path):
        return "Internal/MIDI", False

    folder, filename = os.path.split(raw_path)

    # Precise folder detection
    is_processed = "/Samples/Processed" in raw_path
    is_imported = "/Samples/Imported" in raw_path

    # --- CASE 1: PROCESSED (Force MP3 check in Imported) ---
    if is_processed:
        # Search for the MP3 version in the Imported sibling folder
        cleaned_name_mp3 = clean_filename(filename, force_mp3=True)
        samples_root = raw_path.split("/Samples/Processed")[0] + "/Samples"
        imported_dir = os.path.join(samples_root, "Imported")
        imported_path = os.path.join(imported_dir, cleaned_name_mp3)

        if os.path.exists(imported_path):
            return imported_path, False
        else:
            # If not in Imported, clean the current processed path but keep original extension
            cleaned_processed_name = clean_filename(filename, force_mp3=False)
            processed_clean_path = os.path.join(folder, cleaned_processed_name)
            # Only alert if the file actually had a timestamp/denoise to strip
            if cleaned_processed_name != filename:
                print_red(f"    Source MP3 missing in Imported: {cleaned_name_mp3}")
            return processed_clean_path, True

    # --- CASE 2: IMPORTED OR EXTERNAL ---
    cleaned_name = clean_filename(filename)
    has_change = (cleaned_name != filename)

    final_path = os.path.join(folder, cleaned_name)
    exists = os.path.exists(final_path)

    # If we stripped something and it doesn't exist, it's missing
    is_missing = has_change and not exists
    if is_missing:
        print_red(f"    Original file missing after stripping: {cleaned_name}")

    return final_path if exists else raw_path, is_missing


def scan_project(n_tracks=10):
    api = SyncAbleton()
    results = {}

    print_gray(f"Scanning {n_tracks} tracks with strict path verification...")

    total_tracks = api.query("/live/song/get/num_tracks")
    num_scenes = api.query("/live/song/get/num_scenes")

    for i in range(min(total_tracks, n_tracks)):
        if api.query("/live/track/get/is_foldable", [i]): continue

        track_name = api.query("/live/track/get/name", [i])
        print_orange(f"Track {i}: {track_name}")
        results[track_name] = {}

        for s in range(num_scenes):
            if api.query("/live/clip_slot/get/has_clip", [i, s]):
                clip_name = api.query("/live/clip/get/name", [i, s])
                raw_path = api.query("/live/clip/get/file_path", [i, s])

                final_path, is_missing = process_file_path(raw_path)

                results[track_name][clip_name] = {
                    "path": final_path,
                    "original_missing": is_missing
                }

                print_yellow(f"  Clip: {clip_name}")
                print_gray(f"    Raw: {raw_path}")
                print(f"    Stripped: {final_path}")

    with open("session_analysis.json", "w", encoding='utf-8') as f:
        json.dump(results, f, indent=4)


if __name__ == "__main__":
    scan_project(n_tracks=2)