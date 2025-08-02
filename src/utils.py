import os
import glob
import json
import datetime
import requests
import yt_dlp
import re
import lyricsgenius
from faster_whisper import WhisperModel
from pydantic import BaseModel
from dotenv import load_dotenv

class MusicInfo(BaseModel):
    artist: str
    title: str


load_dotenv()

# Client Setups
print("Loading transcription model...")
transcription_model = WhisperModel("medium", device="cpu", compute_type="int8")
print("Transcription model loaded.")

genius_token = os.environ.get("GENIUS_API_KEY")
if genius_token:
    genius = lyricsgenius.Genius(genius_token, verbose=False, remove_section_headers=True)
else:
    print("⚠️ GENIUS_API_KEY not found. Genius lookup will fail.")
    genius = None

# Helper Functions
def format_timestamp(seconds: float):
    """Converts seconds into SRT time format HH:MM:SS,ms"""
    td = datetime.timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = int(td.microseconds / 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"

def get_lyrics_from_genius(title, artist):
    """Searches for a song on Genius using a clean title and artist."""
    if not genius: return None
    try:
        print(f"Searching Genius for '{title}' by {artist}...")
        song = genius.search_song(title, artist)
        if song:
            print("✅ Found lyrics on Genius.")
            lyrics = re.sub(r'^.*Lyrics(\[.*?\])?\n', '', song.lyrics)
            return lyrics.strip()
        print("⚠️ Lyrics not found on Genius.")
        return None
    except Exception as e:
        print(f"⚠️ An error occurred with Genius API: {e}")
        return None


# cleaning function
def get_clean_title_and_artist_with_llm(video_title: str, client, model_name: str) -> tuple[str, str]:
    """Uses an LLM to extract a clean artist and title from a messy string."""
    print(f"Cleaning title with LLM: '{video_title}'")
    try:
        prompt = (
            "You're an expert music metadata extractor. Your task is to analyze the following noisy YouTube video title "
            "and return a clean, minimal JSON object with two keys: 'artist' and 'title'. Ignore or remove text like "
            "'official video', 'lyrics', 'HD', 'MV', timestamps, remix labels, YouTube tags, featured artists, and any "
            "extra formatting. Use the most well-known name for the artist (e.g. 'The Weeknd' not 'WeekndVEVO').\n\n"
            "Respond strictly in JSON format without explanations.\n\n"
            f"Title to analyze: \"{video_title}\""
        )


        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config={
                'response_mime_type': "application/json",
                'response_schema': MusicInfo,
            }
        )
        
        data = json.loads(response.text)
        clean_title = data['title']
        clean_artist = data['artist']
        
        print(f"✅ LLM cleaned title to: '{clean_title}' by '{clean_artist}'")
        return clean_title, clean_artist
    except Exception as e:
        print(f"⚠️ LLM title cleaning failed: {e}")
        # Fallback to the original title if the LLM fails
        return video_title, None

# Core Transcription & LLM Functions
def transcribe_and_save_srt(video_path: str, lang_code: str = None) -> str:
    """Generates an initial SRT file from a video using Whisper."""
    print(f"Transcribing '{os.path.basename(video_path)}'...")
    transcribe_options = {"temperature": 0.0, "condition_on_previous_text": False, "no_speech_threshold": 0.6}
    segments, info = transcription_model.transcribe(video_path, language=lang_code, beam_size=5, **transcribe_options)

    detected_lang_code = info.language
    print(f"Detected language: {detected_lang_code.upper()}")
    base_filename, _ = os.path.splitext(video_path)
    output_srt_path = f"{base_filename}.{detected_lang_code}.srt"

    with open(output_srt_path, "w", encoding="utf-8") as srt_file:
        for i, segment in enumerate(segments):
            start, end, text = segment.start, segment.end, segment.text.strip()
            srt_file.write(f"{i + 1}\n{format_timestamp(start)} --> {format_timestamp(end)}\n{text}\n\n")

    print(f"Initial transcription saved to '{output_srt_path}'")
    return output_srt_path

def correct_and_translate_srt_with_llm(srt_path, video_title, original_lang, target_lang, client, model_name, genius_lyrics=None):
    """Uses two separate LLM calls to first correct an SRT file and then translate it."""
    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            srt_content = f.read()

        # --- First Pass: Correction ---
        print("Starting LLM Pass 1: Correcting original lyrics...")
        correction_instruction = (
            f"The official lyrics for '{video_title}' are provided below. You must align these official lyrics with the timestamps from the original SRT file. "
            f"Preserve the original numbering and timestamps perfectly, but replace the text with the accurate lyrics. in the language '{original_lang}'. "
            f"Only output the raw, corrected SRT content and nothing else."
            f"\n\n--- OFFICIAL LYRICS ---\n{genius_lyrics}"
        ) if genius_lyrics else (
            f"Search the web for the official lyrics of '{video_title}' in its native language ({original_lang}). "
            "Then, use those official lyrics to correct any transcription errors in the provided SRT content. Only output the raw, corrected SRT content."
        )
        
        correction_prompt = (
            f"You are an expert SRT file processor. Your task is to correct the text of the provided SRT file using the official lyrics. "
            f"{correction_instruction}\n\n"
            f"\n\n--- ORIGINAL SRT CONTENT WITH TIMESTAMPS ---\n{srt_content}"        )

        correction_response = client.models.generate_content(model=model_name, contents=correction_prompt)
        corrected_original_srt = correction_response.text.strip()

        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write(corrected_original_srt)
        print("✅ Correction complete.")

        # --- Second Pass: Translation ---
        print("Starting LLM Pass 2: Translating corrected lyrics...")
        translation_prompt = (
            f"You are an expert SRT file translator. Your task is to translate the text portion of the provided SRT file into the language with the code '{target_lang}'. "
            f"You MUST preserve the original timestamps and numbering perfectly. Only output the raw, translated SRT content."
            f"\n\n--- CORRECTED SRT CONTENT TO TRANSLATE ---\n{corrected_original_srt}"
        )

        translation_response = client.models.generate_content(model=model_name, contents=translation_prompt)
        translated_srt = translation_response.text.strip()
        
        base_filename, _ = os.path.splitext(srt_path)
        translated_srt_path = f"{base_filename.rsplit('.', 1)[0]}.{target_lang}.srt"
        with open(translated_srt_path, 'w', encoding='utf-8') as f:
            f.write(translated_srt)
            
        print(f"✅ Translation complete. New file saved: {translated_srt_path}")
    except Exception as e:
        print(f"⚠️ LLM processing failed: {e}")

# Main Workflow Functions
def get_subtitle_options(video_url):
    """Fetches a list of OFFICIAL subtitles for a video, ignoring auto-captions."""
    ydl_opts = {'listsubtitles': True, 'quiet': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
    
    subtitles_list = []
    if 'subtitles' in info and info.get('subtitles'):
        for code, subs in info['subtitles'].items():
            if any(sub.get('ext') == 'srt' for sub in subs):
                subtitles_list.append({'code': code, 'name': subs[0].get('name', code)})
    
    return {'youtube_id': info.get('id'), 'title': info.get('title'), 'subtitles': subtitles_list, 'has_subs': len(subtitles_list) > 0}

def download_and_transcribe(video_url, video_save_path, use_genius, client, model_name, lang_code=None, target_lang='en'):
    """Orchestrates the full Whisper -> Genius -> LLM workflow."""
    ydl_opts = {'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4/best', 'outtmpl': os.path.join(video_save_path, '%(id)s.%(ext)s'), 'quiet': True}
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
        title, youtube_id = info.get('title'), info.get('id')
    
    genius_lyrics = None
    if use_genius:
        clean_title, clean_artist = get_clean_title_and_artist_with_llm(title, client, model_name)
        
        if clean_title and clean_artist:
            genius_lyrics = get_lyrics_from_genius(clean_title, clean_artist)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        video_filename = ydl.prepare_filename(info)

    initial_srt_path = transcribe_and_save_srt(video_filename, lang_code=lang_code)

    if initial_srt_path:
        original_lang = os.path.basename(initial_srt_path).split('.')[-2]
        correct_and_translate_srt_with_llm(initial_srt_path, title, original_lang, target_lang, client, model_name, genius_lyrics)
    
    # Update library.json
    library_path = 'library.json'
    try:
        with open(library_path, 'r', encoding='utf-8') as f: library_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): library_data = {}
    library_data[youtube_id] = title
    with open(library_path, 'w', encoding='utf-8') as f: json.dump(library_data, f, indent=4, ensure_ascii=False)
    
    return title
def download_video_and_subs(video_url, lang_codes, video_save_path):
    """
    Downloads video/subs, saves the title to library.json, and downloads a thumbnail.
    """
    with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
        info = ydl.extract_info(video_url, download=False)
        title = info.get('title', 'video')
        youtube_id = info.get('id')

    library_path = 'library.json'
    try:
        with open(library_path, 'r', encoding='utf-8') as f:
            library_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        library_data = {}
    library_data[youtube_id] = title
    with open(library_path, 'w', encoding='utf-8') as f:
        json.dump(library_data, f, indent=4, ensure_ascii=False)
    
    thumbnail_folder = os.path.join(video_save_path, "thumbnails")
    os.makedirs(thumbnail_folder, exist_ok=True)
    thumbnail_path = os.path.join(thumbnail_folder, f"{youtube_id}.jpg")
    
    if not os.path.exists(thumbnail_path):
        print(f"Downloading thumbnail for {youtube_id}...")
        for quality in ["maxresdefault", "sddefault", "hqdefault", "default"]:
            thumbnail_url = f"https://i.ytimg.com/vi/{youtube_id}/{quality}.jpg"
            try:
                response = requests.get(thumbnail_url)
                if response.status_code == 200:
                    with open(thumbnail_path, "wb") as f:
                        f.write(response.content)
                    print(f"✅ Thumbnail saved in '{quality}' quality.")
                    break
            except requests.exceptions.RequestException as e:
                print(f"Could not download thumbnail: {e}")
                break
        else:
            print("⚠️ Thumbnail not found in any resolution.")

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4/best',
        'outtmpl': os.path.join(video_save_path, '%(id)s.%(ext)s'),
        'writesubtitles': True,
        'subtitleslangs': lang_codes,
        'subtitlesformat': 'srt',
        'quiet': True,
    }

    print(f"Downloading '{title}'...")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])
    print("Download complete.")
    return title


def delete_video_files(youtube_id, video_save_path):
    """Deletes a video, its thumbnail, all subtitles, and its library entry."""
    print(f"Attempting to delete files for {youtube_id}...")
    video_files_pattern = os.path.join(video_save_path, f'{youtube_id}.*')
    files_to_delete = glob.glob(video_files_pattern)
    thumbnail_path = os.path.join(video_save_path, "thumbnails", f"{youtube_id}.jpg")
    if os.path.exists(thumbnail_path):
        files_to_delete.append(thumbnail_path)

    for f in files_to_delete:
        try:
            os.remove(f)
            print(f"Deleted file: {f}")
        except OSError as e:
            print(f"Error deleting file {f}: {e}")

    library_path = 'library.json'
    try:
        with open(library_path, 'r', encoding='utf-8') as f:
            library_data = json.load(f)
        if youtube_id in library_data:
            del library_data[youtube_id]
            print(f"Removed {youtube_id} from library.json")
        with open(library_path, 'w', encoding='utf-8') as f:
            json.dump(library_data, f, indent=4, ensure_ascii=False)
    except (FileNotFoundError, json.JSONDecodeError):
        print("library.json not found or is empty.")
