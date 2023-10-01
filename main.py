from flask import Flask, request, jsonify, session, redirect, url_for, render_template
from werkzeug.utils import secure_filename
from faster_whisper import WhisperModel
import os
import re
import sqlite3
import time
import random
import string
from moviepy.editor import AudioFileClip

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with your own secret key

# SQLite database setup
conn = sqlite3.connect('user_data.db')
conn.execute('''CREATE TABLE IF NOT EXISTS users
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
             username TEXT NOT NULL,
             password TEXT NOT NULL,
             hourly_usage REAL DEFAULT 0.0,
             amount_paid REAL DEFAULT 0.0)''')

conn.execute('''CREATE TABLE IF NOT EXISTS api_keys
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
             user_id INTEGER,
             api_key TEXT UNIQUE NOT NULL,
             api_key_name TEXT NOT NULL)''')

conn.commit()
conn.close()

def get_audio_duration(audio_path):
    audio = AudioFileClip(audio_path)
    audio.close()
    return audio.duration / 3600

def generate_unique_api_key():
    # Define the characters to choose from for the API key
    characters = string.ascii_letters + string.digits
    key_length = 20

    while True:
        # Generate a random API key
        api_key = 'tc-' + ''.join(random.choice(characters) for _ in range(key_length))

        # Check if the API key is in the database
        conn = sqlite3.connect('user_data.db')
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM api_keys WHERE api_key=?", (api_key,))
        count = cursor.fetchone()[0]
        conn.close()

        if count == 0:
            return api_key

def format_time(total_seconds):
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    milliseconds = int((total_seconds % 1) * 1000)

    formatted_time = f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

    return formatted_time

def segments_to_captions(input_text):
    # Split the input text into lines
    lines = input_text.split('\n')

    output_text = ""
    counter = 1

    for line in lines:
        # Extract the time intervals and text
        match = re.search(r'\[(\d+\.\d+s) -> (\d+\.\d+s)\]\s+(.*)', line)
        if match:
            start_time = match.group(1)
            end_time = match.group(2)
            text = match.group(3)

            # Convert the times to the desired format with commas for milliseconds
            start_seconds = int(float(start_time[:-1]) * 100) / 100
            end_seconds = int(float(end_time[:-1]) * 100) / 100

            formatted_start_seconds = format_time(start_seconds)
            formatted_end_seconds = format_time(end_seconds)

            # Format the output line
            output_line = f"{counter}\n"
            output_line += f"{formatted_start_seconds} --> {formatted_end_seconds}\n"
            output_line += text

            output_text += output_line + '\n\n'
            counter += 1

    return output_text

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    else: 
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # Check if the username and password match a user in the database
        conn = sqlite3.connect('user_data.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            # Store the user's ID in the session
            session['user_id'] = user[0]
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='Invalid username or password')

    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))
        
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # Check if the username already exists in the database
        conn = sqlite3.connect('user_data.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            conn.close()
            return render_template('signup.html', error='Username already exists')
        
        # If the username is unique, create a new user in the database
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()

        default_api_key_name = 'API key'
        
        # Generate a new API key for the user
        api_key = generate_unique_api_key()
        cursor.execute("INSERT INTO api_keys (user_id, api_key, api_key_name) VALUES (?, ?)", (cursor.lastrowid, api_key, default_api_key_name))
        conn.commit()
        
        conn.close()
        
        # Store the user's ID in the session
        session['user_id'] = cursor.lastrowid
        return redirect(url_for('dashboard'))
    
    return render_template('signup.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    # Get the user's API keys from the database
    conn = sqlite3.connect('user_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE id=?', (user_id,))
    user = cursor.fetchone()

    cursor.execute("SELECT api_key, api_key_name, id FROM api_keys WHERE user_id=?", (user_id,))
    api_keys = cursor.fetchall()

    conn.close()

    if api_keys is None:
        api_keys = []
    
    return render_template('dashboard.html', api_keys=api_keys, user=user)

@app.route('/create_api_key', methods=['POST', 'GET'])
def create_api_key():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if request.method == 'POST':
        print(request.form['api_key_name'])
        api_key_name = request.form['api_key_name'] if request.form['api_key_name'] else 'API Key'
        
        # Generate a new API key for the user
        api_key = generate_unique_api_key()
        
        # Insert the new API key and its name into the database
        conn = sqlite3.connect('user_data.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO api_keys (user_id, api_key, api_key_name) VALUES (?, ?, ?)", (user_id, api_key, api_key_name))
        conn.commit()
        conn.close()

    return redirect(url_for('dashboard'))

@app.route('/remove_api_key/<int:key_id>', methods=['POST'])
def remove_api_key(key_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    # Check if the API key belongs to the user
    conn = sqlite3.connect('user_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM api_keys WHERE id=?", (key_id,))
    owner_id = cursor.fetchone()
    conn.close()

    if not owner_id or owner_id[0] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    # Delete the API key
    conn = sqlite3.connect('user_data.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM api_keys WHERE id=?", (key_id,))
    conn.commit()
    conn.close()

    return redirect(url_for('dashboard'))

@app.route('/transcribe', methods=['POST'])
@app.route('/transcribe/<model>', methods=['POST'])
def upload(model:str='tiny'):
    api_key = request.headers.get('API-Key')
    
    # Check if the API key exists in the database
    conn = sqlite3.connect('user_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM api_keys WHERE api_key=?", (api_key,))
    user_id = cursor.fetchone()
    conn.close()
    
    if not user_id:
        return jsonify({'error': 'Invalid API key'}), 401
    
    user_id = user_id[0]
    
    # Check if the user has exceeded the hourly usage limit
    conn = sqlite3.connect('user_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT hourly_usage, amount_paid FROM users WHERE id=?", (user_id,))
    user_data = cursor.fetchone()
    conn.close()
    
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
    
    hourly_limit = user_data[1] * 0.5  # Hourly limit based on amount pai

    if user_data[0] >= hourly_limit:
        return jsonify({'error': 'Hourly usage limit exceeded'}), 429

    model = WhisperModel(model)

    audio_file = request.files['file']  

    audio_filename = secure_filename(audio_file.filename)
    audio_file.save(audio_filename)

    audio_duration = get_audio_duration(audio_filename)

    start_time = time.time()

    segments, _ = model.transcribe(audio_filename, word_timestamps=True)
    segments = list(segments)

    end_time = time.time()

    process_time = end_time - start_time + 's'

    try:
        os.remove(audio_filename)
    except Exception as e:
        print(str(e))
  
    words_to_text = ""
    for segment in segments:
        for word in segment.words:
            word = "[%.2fs -> %.2fs] %s" % (word.start, word.end, word.word)
            words_to_text += word + "\n"

    captions = segments_to_captions(words_to_text)
    
    # Update the user's hourly usage
    conn = sqlite3.connect('user_data.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET hourly_usage = hourly_usage + ? WHERE id=?", (audio_duration, user_id,))
    conn.commit()
    conn.close()

    return jsonify({'captions': captions, 'process_time': process_time, 'success': True})

if __name__ == '__main__':
    app.run(port=81)
