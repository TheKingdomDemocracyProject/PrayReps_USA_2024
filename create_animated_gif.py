import os
import random
from PIL import Image

def create_animated_gif(image_dir, output_path):
    # Get list of image paths
    image_paths = [os.path.join(image_dir, img) for img in os.listdir(image_dir) if img.endswith('.png')]
    
    # Randomize the order of the images
    random.shuffle(image_paths)
    
    # Open images
    images = [Image.open(img_path) for img_path in image_paths]
    
    # Create and save animated GIF
    images[0].save(output_path, save_all=True, append_images=images[1:], duration=200, loop=0)
    print(f"Animated GIF saved to {output_path}")

if __name__ == "__main__":
    image_dir = 'output/outline'  # Directory where the generated images are stored
    gif_output_path = 'output/high_res/prayer_map.gif'  # Path to save the animated GIF

    create_animated_gif(image_dir, gif_output_path)
