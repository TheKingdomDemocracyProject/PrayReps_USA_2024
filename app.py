from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, get_flashed_messages
import pandas as pd
import requests
import threading
import time
import queue as Queue
import logging
from datetime import datetime
import json
import sys
from io import StringIO
import numpy as np
import os

from hex_map import load_hex_map, load_post_label_mapping, plot_hex_map_with_hearts
from utils import format_pretty_timestamp

app = Flask(__name__)

# Secret key for flashing messages - IMPORTANT: Change for production!
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev_secret_key') # Use environment variable or a default

# Configuration
app.config['HEX_MAP_PATH'] = 'data/20241105_usa_esri_v2.shp'
app.config['POST_LABEL_MAPPING_PATH'] = 'data/post_label to 3CODE.csv'
app.config['HEART_IMG_PATH'] = 'static/heart_icons/heart_red.png'
app.config['CSV_DATA_PATH'] = 'data/20241105_usa_488.csv'
app.config['PRAYED_FOR_LOG'] = 'prayed_for.json'

# Simplified party_info with only relevant parties
party_info = {
    'Democrat': {'short_name': 'Dem', 'color': '#0015BC'},
    'Republican': {'short_name': 'Rep', 'color': '#E81B23'},
    'Independent': {'short_name': 'Ind', 'color': '#808080'},
    'Other': {'short_name': 'Other', 'color': '#CCCCCC'}
}

data_queue = Queue.Queue()
processed_items = []
prayed_for = []  # This will store the processed items for statistics
queued_entries = set()  # To track the unique entries in the queue

# Load hex map and mappings
hex_map = load_hex_map(app.config['HEX_MAP_PATH'])
post_label_mapping = load_post_label_mapping(app.config['POST_LABEL_MAPPING_PATH'])

# Threading lock for update_queue
update_thread_lock = threading.Lock()

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler("app.log"),
    logging.StreamHandler()
])

# Function to load CSV data from config
def load_csv_data_from_config(csv_path):
    logging.info(f"Loading CSV data from {csv_path}")
    try:
        # Use standard file I/O with open()
        with open(csv_path, 'r', encoding='utf-8') as f:
            df = pd.read_csv(f)
        df = df.replace({np.nan: None})  # Replace NaN with None
        logging.debug(f"Loaded data: {df.head()}")
        return df
    except FileNotFoundError:
        logging.error(f"CSV file not found at {csv_path}")
        return pd.DataFrame()
    except Exception as e:
        logging.error(f"Error reading CSV file at {csv_path}: {e}")
        return pd.DataFrame()

# Process each entry to determine if an image is available
def process_deputies(csv_data):
    deputies_with_images = []
    deputies_without_images = []

    for index, row in csv_data.iterrows():
        image_url = row.get('image_url')

        if not image_url:
            logging.debug(f"No image URL for {row.get('person_name')} at index {index}")
            deputies_without_images.append(row)
            continue

        row['Image'] = image_url
        deputies_with_images.append(row)
        logging.debug(f"Image URL assigned for {row.get('person_name')}: {image_url}")

    return deputies_with_images, deputies_without_images

# Load the CSV data
csv_data = load_csv_data_from_config(app.config['CSV_DATA_PATH'])
deputies_with_images, deputies_without_images = process_deputies(csv_data)

# Log the names without images
if deputies_without_images:
    logging.info(f"No images found for the following names: {', '.join([dep['person_name'] for dep in deputies_without_images if dep['person_name']])}")

# Function to periodically update the queue
def update_queue():
    if not update_thread_lock.acquire(blocking=False):
        logging.info("Update_queue: Could not acquire lock, another instance is running or about to run.")
        return

    try:
        logging.info("Update_queue: Lock acquired, proceeding with update.")
        with app.app_context():  # Ensure this block runs within an application context
            while True: # This loop will be managed by the thread's lifecycle now, consider if it should run once or loop
                df = load_csv_data_from_config(app.config['CSV_DATA_PATH'])
                if df.empty:
                    logging.warning("Update_queue: CSV data is empty, skipping update cycle.")
                    time.sleep(90) # Wait before retrying if data is empty
                    continue

                prayed_for_ids = {(item['person_name'], item['post_label']) for item in prayed_for}

            # Shuffle the DataFrame rows for randomization
            df = df.sample(frac=1).reset_index(drop=True)

            for index, row in df.iterrows():
                if all(row.get(field) for field in ['place', 'post_label', 'person_name', 'party']):
                    item = row.to_dict()
                    entry_id = (item['person_name'], item['post_label'])
                    if entry_id not in prayed_for_ids and entry_id not in queued_entries:
                        image_url = item.get('image_url', app.config['HEART_IMG_PATH'])
                        if not image_url:
                            image_url = app.config['HEART_IMG_PATH']
                        item['thumbnail'] = image_url
                        data_queue.put(item)
                        queued_entries.add(entry_id)
                        logging.info(f"Added to queue: {item}")
                else:
                    logging.debug(f"Skipped incomplete entry at index {index}: {row.to_dict()}")
            
            logging.debug(f"Queue size: {data_queue.qsize()}")
            # The time.sleep here will cause the lock to be held for 90s.
            # This means start_update_thread_if_not_running will not be able to start a new thread
            # if this one is sleeping. The while True means this thread will run "forever" once started.
            # The lock prevents multiple *concurrent* executions of the core logic,
            # but the thread itself will re-run this loop.
            time.sleep(90)
    finally:
        update_thread_lock.release()
        logging.info("Update_queue: Lock released.")

def start_update_thread_if_not_running():
    is_thread_running = False
    for thread in threading.enumerate():
        if thread.name == 'QueueUpdateThread' and thread.is_alive():
            is_thread_running = True
            break

    if not is_thread_running:
        logging.info("Starting QueueUpdateThread as it is not currently running.")
        thread = threading.Thread(target=update_queue, daemon=True, name='QueueUpdateThread')
        thread.start()
    else:
        logging.info("QueueUpdateThread is already running.")

def read_log():
    global prayed_for
    try:
        with open(app.config['PRAYED_FOR_LOG'], 'r') as f:
            prayed_for = json.load(f)
    except FileNotFoundError:
        logging.info(f"Log file {app.config['PRAYED_FOR_LOG']} not found. Initializing with an empty list.")
        prayed_for = []
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from {app.config['PRAYED_FOR_LOG']}. Initializing with an empty list.")
        prayed_for = []
    except Exception as e:
        logging.error(f"An unexpected error occurred while reading {app.config['PRAYED_FOR_LOG']}: {e}")
        prayed_for = []

def write_log():
    try:
        with open(app.config['PRAYED_FOR_LOG'], 'w') as f:
            json.dump(prayed_for, f)
    except Exception as e:
        logging.error(f"An error occurred while writing to {app.config['PRAYED_FOR_LOG']}: {e}")

@app.route('/')
def home():
    read_log()  # Ensure prayed_for is up to date
    remaining = 488 - len(prayed_for)
    current = None if data_queue.empty() else data_queue.queue[0]
    queue_list = list(data_queue.queue)
    plot_hex_map_with_hearts(hex_map, post_label_mapping, [item['post_label'] for item in prayed_for], [item['post_label'] for item in queue_list])  # Update hex map

    # Create URLs for images
    # Ensure heart_img_path is available for templates if needed, or passed via context
    processed_deputies_with_images = []
    for deputy in deputies_with_images:
        # Assuming 'Image' is the key for the image URL in the deputy dict
        # If not, this logic might need adjustment based on how images are handled
        if not deputy.get('Image'): # Check if 'Image' key exists and is not empty
             deputy['Image'] = app.config['HEART_IMG_PATH'] # Fallback to default heart image
        processed_deputies_with_images.append(deputy)
        logging.debug(f"Deputy: {deputy['person_name']}, Image URL: {deputy['Image']}")


    return render_template('index.html', remaining=remaining, current=current, queue=queue_list, deputies_with_images=processed_deputies_with_images, deputies_without_images=deputies_without_images, heart_img_path=app.config['HEART_IMG_PATH'])

@app.route('/queue')
def queue_page():
    items = list(data_queue.queue)
    logging.info(f"Queue items: {items}")
    return render_template('queue.html', queue=items)

@app.route('/queue/json')
def get_queue_json():
    items = list(data_queue.queue)
    logging.info(f"Queue items: {items}")
    return jsonify(items)

@app.route('/process_item', methods=['POST'])
def process_item():
    if not data_queue.empty():
        item = data_queue.get()
        item['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Add timestamp
        processed_items.append(item)
        prayed_for.append(item)  # Add to prayed_for list
        queued_entries.remove((item['person_name'], item['post_label']))  # Remove from queued entries
        write_log()  # Save to log file
        logging.info(f"Processed item: {item}")
        queue_list = list(data_queue.queue)
        plot_hex_map_with_hearts(hex_map, post_label_mapping, [item['post_label'] for item in prayed_for], [item['post_label'] for item in queue_list])  # Update hex map
    return '', 204

@app.route('/statistics')
def statistics():
    read_log()
    party_counts = {}
    for item in prayed_for:
        party = item.get('party', 'Other')
        short_name = party_info.get(party, party_info['Other'])['short_name']
        party_counts[short_name] = party_counts.get(short_name, 0) + 1

    sorted_party_counts = sorted(party_counts.items(), key=lambda x: x[1], reverse=True)
    return render_template('statistics.html', sorted_party_counts=sorted_party_counts, party_info=party_info)

@app.route('/statistics/data')
def statistics_data():
    read_log()
    party_counts = {}
    for item in prayed_for:
        party = item.get('party', 'Other')
        short_name = party_info.get(party, party_info['Other'])['short_name']
        party_counts[short_name] = party_counts.get(short_name, 0) + 1
    return jsonify(party_counts)

@app.route('/statistics/timedata')
def statistics_timedata():
    read_log()
    timestamps = []
    values = []
    for item in prayed_for:
        timestamps.append(item.get('timestamp'))
        values.append({
            'place': item.get('post_label'),
            'person': item.get('person_name'),
            'party': item.get('party')  # Use full party name for matching colors
        })
    return jsonify({'timestamps': timestamps, 'values': values})

@app.route('/prayed')
def prayed_list():
    read_log()
    for item in prayed_for:
        item['formatted_timestamp'] = format_pretty_timestamp(item.get('timestamp'))
        party = item.get('party', 'Other')
        party_info_item = party_info.get(party, party_info['Other'])
        item['party_class'] = party_info_item['short_name'].lower().replace(' ', '-').replace('&', 'and')
        item['party_color'] = party_info_item['color']

    return render_template('prayed.html', prayed_for=prayed_for, party_info=party_info)

@app.route('/purge')
def purge_queue():
    global data_queue, prayed_for, queued_entries
    with data_queue.mutex:
        data_queue.queue.clear()
    prayed_for = []
    queued_entries.clear()
    write_log()
    plot_hex_map_with_hearts(hex_map, post_label_mapping, [], [])  # Update hex map
    return redirect(url_for('home'))

@app.route('/refresh')
def refresh_data():
    start_update_thread_if_not_running()
    # write_log() call removed as per instructions
    return redirect(url_for('home'))

@app.route('/put_back', methods=['POST'])
def put_back_in_queue():
    global prayed_for
    read_log()
    person_name = request.form.get('person_name')
    post_label = request.form.get('post_label')
    # Use 'item' as variable name for consistency if it's used in flash message
    item_found = next((item for item in prayed_for if item['post_label'] == post_label and item['person_name'] == person_name), None)

    if item_found:
        data_queue.put(item_found) # Use item_found here
        prayed_for = [p for p in prayed_for if p['post_label'] != post_label or p['person_name'] != person_name]
        queued_entries.add((person_name, post_label))
        write_log()
        queue_list = list(data_queue.queue)
        plot_hex_map_with_hearts(hex_map, post_label_mapping, [item['post_label'] for item in prayed_for], [item['post_label'] for item in queue_list])  # Update hex map
        flash(f"'{item_found['person_name']}' has been returned to the prayer queue.", 'success')
    else:
        flash('Selected person not found in prayed list.', 'error')

    return redirect(url_for('prayed_list'))

@app.route('/filter_by_state', methods=['GET', 'POST'])
def filter_by_state():
    filtered_reps = []
    state_query = ""
    global csv_data # Ensure we are using the global csv_data

    if request.method == 'POST':
        state_query = request.form.get('state_name', '').strip()
        if state_query:
            normalized_state = state_query.lower().replace(' ', '_')

            # Ensure csv_data is loaded and is a DataFrame
            if csv_data is None or csv_data.empty:
                logging.error("CSV data is not loaded or is empty. Cannot filter by state.")
                # Optionally, flash a message to the user
                flash("Data is currently unavailable, please try again later.", "error")
            else:
                # Filter Senators
                senator_pattern = f"senate-{normalized_state}"
                # Ensure 'post_label' column exists and handle potential errors if it doesn't
                if 'post_label' in csv_data.columns:
                    senators = csv_data[csv_data['post_label'].str.lower() == senator_pattern]
                else:
                    senators = pd.DataFrame() # Empty DataFrame if column missing
                    logging.error("Column 'post_label' not found in csv_data.")

                # Filter House Members
                house_pattern = f"^{normalized_state}-"
                if 'post_label' in csv_data.columns:
                    house_reps = csv_data[csv_data['post_label'].str.lower().str.startswith(house_pattern, na=False)]
                else:
                    house_reps = pd.DataFrame()
                    logging.error("Column 'post_label' not found in csv_data.")

                # Filter Governor
                governor_pattern = f"governor_of_{normalized_state}"
                if 'post_label' in csv_data.columns:
                    governors = csv_data[csv_data['post_label'].str.lower() == governor_pattern]
                else:
                    governors = pd.DataFrame()
                    logging.error("Column 'post_label' not found in csv_data.")

                # Combine results
                combined_reps_df = pd.concat([senators, house_reps, governors], ignore_index=True)

                if not combined_reps_df.empty:
                    combined_reps_list = combined_reps_df.to_dict('records')

                    # Deduplicate
                    seen_reps = set()
                    final_filtered_list = []
                    for rep in combined_reps_list:
                        rep_tuple = (rep.get('person_name'), rep.get('post_label'))
                        if rep_tuple not in seen_reps:
                            final_filtered_list.append(rep)
                            seen_reps.add(rep_tuple)
                    filtered_reps = final_filtered_list
                else:
                    logging.info(f"No representatives found for state query: {state_query}")
        else:
            flash("Please enter a state name to search.", "info")
            # Return early if state_query is empty to avoid rendering results for an empty query
            return render_template('filtered_results.html', representatives=[], location_query='')


    return render_template('filtered_results.html', representatives=filtered_reps, location_query=state_query.title())

if __name__ == '__main__':
    # Read initial log
    read_log()

    # Start the queue updating thread if not already running
    start_update_thread_if_not_running()

    try:
        # Run the Flask app with debug mode enabled
        app.run(debug=True)
    except KeyboardInterrupt:
        print('You pressed Ctrl+C! Exiting gracefully...')
        sys.exit(0)
