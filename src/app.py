import os
import glob
import json
from flask import Flask, render_template, request, url_for, redirect
from . import utils
import sqlite3
from deep_translator import GoogleTranslator
from google import genai
from dotenv import load_dotenv

load_dotenv()

client = genai.Client()

app = Flask(__name__)

gemini_model = 'gemini-1.5-flash'


@app.route('/')
def index():
    search_query = request.args.get('search', '').lower()
    library_path = 'library.json'
    try:
        with open(library_path, 'r', encoding='utf-8') as f:
            library_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        library_data = {}

    video_folder = os.path.join(app.static_folder, 'videos')
    thumbnail_folder = os.path.join(app.static_folder, 'thumbnails')
    videos_data = []
    
    try:
        video_files = [f for f in os.listdir(video_folder) if f.endswith('.mp4')]
    except FileNotFoundError:
        video_files = []

    for filename in video_files:
        youtube_id = os.path.splitext(filename)[0]
        title = library_data.get(youtube_id, youtube_id)

        if search_query and search_query not in title.lower():
            continue

        thumbnail_filename = youtube_id + ".jpg"
        thumbnail_path = os.path.join(thumbnail_folder, thumbnail_filename)
        
        if os.path.exists(thumbnail_path):
            thumbnail_url = url_for('static', filename=f'thumbnails/{thumbnail_filename}')
        else:
            thumbnail_url = f"https://i.ytimg.com/vi/{youtube_id}/hqdefault.jpg"

        video_info = {
            'youtube_id': youtube_id,
            'player_url': url_for('player', youtube_id=youtube_id),
            'thumbnail_url': thumbnail_url,
            'title': title
        }
        videos_data.append(video_info)

    return render_template('index.html', videos=videos_data, search_query=search_query)


@app.route('/add', methods=['GET', 'POST'])
def add_video():
    if request.method == 'POST':
        video_url = request.form.get('url')
        if not video_url:
            return "URL is missing.", 400
        
        clean_url = video_url.split('&')[0]
        
        try:
            video_info = utils.get_subtitle_options(clean_url)
            return render_template('confirm.html', video=video_info, video_url=clean_url)
        except Exception as e:
            print(f"Error fetching subtitle options: {e}")
            return "Could not fetch video data...", 500

    return render_template('add.html')


@app.route('/download', methods=['POST'])
def download_video():
    # Get all the data from the form on the confirmation page
    video_url = request.form.get('video_url')
    generate_with_whisper = request.form.get('generate_with_whisper')
    video_save_path = os.path.join(app.static_folder, 'videos')

    try:
        if generate_with_whisper:
            # If generating, get the extra Whisper-related options
            whisper_lang = request.form.get('whisper_lang_code')
            target_lang = request.form.get('translate_to_lang', 'en')
            use_genius = request.form.get('use_genius') == 'true'
            lang_code_or_none = whisper_lang if whisper_lang else None
            
            # Call the full-featured transcription function
            video_title = utils.download_and_transcribe(
                video_url, video_save_path, use_genius, client, gemini_model,
                lang_code=lang_code_or_none, target_lang=target_lang
            )
        else:
            # Otherwise, just download the official subtitles
            lang_codes = request.form.getlist('lang_codes')
            if not lang_codes:
                return "You must select at least one subtitle language.", 400
            video_title = utils.download_video_and_subs(video_url, lang_codes, video_save_path)
        
        return render_template('downloading.html', video_title=video_title)
        
    except Exception as e:
        print(f"An error occurred during download: {e}")
        return "An error occurred during the download process.", 500


@app.route('/player/<youtube_id>')
def player(youtube_id):
    library_path = 'library.json'
    try:
        with open(library_path, 'r', encoding='utf-8') as f:
            library_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        library_data = {}
    video_title = library_data.get(youtube_id, youtube_id)

    video_folder = os.path.join(app.static_folder, 'videos')
    video_url = url_for('static', filename=f'videos/{youtube_id}.mp4')
    subtitle_pattern = os.path.join(video_folder, f'{youtube_id}.*.srt')
    subtitle_files = glob.glob(subtitle_pattern)
    
    subtitle_data = []
    for srt_path in subtitle_files:
        filename = os.path.basename(srt_path)
        lang_code = filename.split('.')[-2]
        subtitle_data.append({
            'lang_code': lang_code.upper(),
            'url': url_for('static', filename=f'videos/{filename}')
        })

    preselect_lang1_url = None
    preselect_lang2_url = None
    
    # Find the English subtitle URL, if it exists
    en_sub = next((sub for sub in subtitle_data if sub['lang_code'] == 'EN'), None)
    if en_sub:
        preselect_lang2_url = en_sub['url']

    # If there are only two languages and one is English, pre-select the other one
    if len(subtitle_data) == 2 and en_sub:
        other_sub = next((sub for sub in subtitle_data if sub['lang_code'] != 'EN'), None)
        if other_sub:
            preselect_lang1_url = other_sub['url']

    return render_template(
        'player.html',
        video_title=video_title,
        video_url=video_url,
        subtitles=subtitle_data,
        # Pass the pre-selection URLs to the template
        preselect_lang1=preselect_lang1_url,
        preselect_lang2=preselect_lang2_url
    )

@app.route('/delete', methods=['POST'])
def delete_video():
    youtube_id = request.form.get('youtube_id')
    if youtube_id:
        video_save_path = os.path.join(app.static_folder, 'videos')
        utils.delete_video_files(youtube_id, video_save_path)
    return redirect(url_for('index'))

@app.route('/save_word', methods=['POST'])
def save_word():
    data = request.get_json()
    word = data.get('word')
    definition = data.get('definition')
    context = data.get('context')

    if not all([word, definition, context]):
        return {"status": "error", "message": "Missing data"}, 400

    try:
        conn = sqlite3.connect('library.db')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO vocabulary (word, definition, context) VALUES (?, ?, ?)",
            (word, definition, context)
        )
        conn.commit()
        conn.close()
        return {"status": "success", "message": "Word saved!"}
    except Exception as e:
        print(f"Database error: {e}")
        return {"status": "error", "message": "Could not save word"}, 500


@app.route('/vocabulary')
def vocabulary():
    words = []
    try:
        conn = sqlite3.connect('library.db')
        cursor = conn.cursor()
        cursor.execute("SELECT word, definition, context FROM vocabulary ORDER BY word ASC")
        
        for row in cursor.fetchall():
            words.append({'word': row[0], 'definition': row[1], 'context': row[2]})
        
        conn.close()
    except Exception as e:
        print(f"Database error when fetching vocabulary: {e}")

    return render_template('vocabulary.html', words=words)

@app.route('/delete_word', methods=['POST'])
def delete_word():
    word_to_delete = request.form.get('word')
    if word_to_delete:
        try:
            conn = sqlite3.connect('library.db')
            cursor = conn.cursor()
            cursor.execute("DELETE FROM vocabulary WHERE word = ?", (word_to_delete,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Database error while deleting word: {e}")
            
    # Redirect back to the vocabulary page to see the updated list
    return redirect(url_for('vocabulary'))



@app.route('/get_definition', methods=['POST'])
def get_definition():
    data = request.get_json()
    clicked_word = data.get('word')
    full_sentence = data.get('sentence')
    lang_code = data.get('lang_code', 'en').lower().strip()

    if not clicked_word or not full_sentence:
        return {"error": "Missing data"}, 400
    
    if lang_code == 'en':
        return {
            "sentence_translation": full_sentence.replace(clicked_word, f"<mark>{clicked_word}</mark>"),
            "word_translation": clicked_word
        }

    try:
        prompt = (
            f"Translate the following sentence from the language with code '{lang_code}' to English. "
            f"In the translated English sentence, find the word or short phrase that most closely corresponds to the word '{clicked_word}' "
            "and wrap it in <mark> tags. Only return the final, translated sentence and nothing else."
            f"\n\nSentence: \"{full_sentence}\""
        )
        
        response = client.models.generate_content(
            model=gemini_model,
            contents=prompt,
            config={
                "temperature": 0.0
            }
        )
        highlighted_sentence = response.text


        
        word_translation = GoogleTranslator(source=lang_code, target='en').translate(clicked_word)
        
        return {
            "sentence_translation": highlighted_sentence,
            "word_translation": word_translation
        }
    except Exception as e:
        print(f"LLM or Translation Error: {e}")
        return {"error": "Could not process translation"}, 500