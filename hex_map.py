import geopandas as gpd
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Use Agg backend for Matplotlib
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from PIL import Image, ImageFile

# Ensure PIL doesn't use tkinter
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Load hex map
def load_hex_map(hex_map_path):
    hex_map = gpd.read_file(hex_map_path)
    return hex_map

# Load post_label to 3CODE mapping
def load_post_label_mapping(post_label_mapping_path):
    post_label_mapping = pd.read_csv(post_label_mapping_path)
    return post_label_mapping

# Load heart image
def load_heart_image(heart_img_path):
    heart_img = Image.open(heart_img_path)
    heart_img.thumbnail((50, 50))  # Resize the image for better fit
    return heart_img

# Plot hex map with white fill color and light grey boundaries
def plot_hex_map_with_hearts(hex_map, post_label_mapping, prayed_for, queue, heart_img_path):
    heart_img = load_heart_image(heart_img_path)
    fig, ax = plt.subplots(1, 1, figsize=(25, 25))
    hex_map.plot(ax=ax, color='white', edgecolor='lightgrey')  # Use light grey for edges
    ax.set_axis_off()  # Hide the axis

    # Get the data bounds directly from the hex map
    bounds = hex_map.geometry.total_bounds  # Returns (minx, miny, maxx, maxy)
    ax.set_xlim(bounds[0], bounds[2])
    ax.set_ylim(bounds[1], bounds[3])
    ax.set_aspect('equal')  # Set aspect ratio to be equal

    # Debugging: Check if there are any locations in prayed_for
    print(f"Total prayed_for locations: {len(prayed_for)}")
    
    # Plot hearts for prayed_for locations
    for location in prayed_for:
        print(f"Processing location: {location}")
        location_code = post_label_mapping.loc[post_label_mapping['post_label'] == location, 'name']
        if not location_code.empty:
            location_code = location_code.iloc[0]
            print(f"Found location code: {location_code}")
            location_geom = hex_map[hex_map['name'] == location_code]
            if not location_geom.empty:
                centroid = location_geom.geometry.centroid.iloc[0]
                print(f"Centroid for {location_code}: ({centroid.x}, {centroid.y})")
                imagebox = OffsetImage(heart_img, zoom=0.8)  # Adjust the zoom level for heart size
                ab = AnnotationBbox(imagebox, (centroid.x, centroid.y), frameon=False)
                ax.add_artist(ab)
                print(f"Heart plotted for location {location_code}")
            else:
                print(f"No geometry found for location code {location_code}")
        else:
            print(f"No mapping found for post_label {location}")

    # Highlight the top of the queue (optional)
    if queue:
        top_queue_location = queue[0]
        location_code = post_label_mapping.loc[post_label_mapping['post_label'] == top_queue_location, 'name']
        if not location_code.empty:
            location_code = location_code.iloc[0]
            location_geom = hex_map[hex_map['name'] == location_code]
            if not location_geom.empty:
                centroid = location_geom.geometry.centroid.iloc[0]
                hex_patch = Polygon(location_geom.geometry.iloc[0].exterior.coords, closed=True, edgecolor='yellow', facecolor='yellow', alpha=0.5)
                ax.add_patch(hex_patch)

    # Save the plot as an image in the static directory
    plt.savefig('static/hex_map.png', bbox_inches='tight', pad_inches=0.5)
    plt.close(fig)  # Close the plot to free memory

# Example usage for Case 2
if __name__ == "__main__":
    hex_map_path = 'data/20241105_usa_esri_v2.shp'
    post_label_mapping_path = 'data/post_label to 3CODE.csv'
    heart_img_path = 'data/heart.png'
    prayed_for = []  # Empty list for Case 2
    queue = ['Croydon West']  # Example list with one item in the queue

    hex_map = load_hex_map(hex_map_path)
    post_label_mapping = load_post_label_mapping(post_label_mapping_path)
    plot_hex_map_with_hearts(hex_map, post_label_mapping, prayed_for, queue, heart_img_path)
