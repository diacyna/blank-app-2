import streamlit as st
import pandas as pd
import os
import glob
import folium
from PIL import Image
import numpy as np
import base64
from pyproj import Transformer
import matplotlib.pyplot as plt
import seaborn as sns
from streamlit_folium import st_folium
import io

# Optional rasterio -- may fail if libgdal is missing in the environment.
try:
    import rasterio
    from rasterio import transform as rio_transform
    has_rasterio = True
except Exception:
    rasterio = None
    rio_transform = None
    has_rasterio = False

def dm_to_dd(degrees, minutes):
    """Converts degrees and minutes to decimal degrees."""
    return degrees + minutes / 60

st.set_page_config(layout="wide")
st.title('Georeferencing and Geological Data Viewer')

st.write("Upload your image (e.g., screenshot) and Excel file with geological coordinates.")

uploads_dir = os.path.join(os.getcwd(), 'uploads')
os.makedirs(uploads_dir, exist_ok=True)

# Always use the on-site uploader: der Benutzer lädt beide Dateien hoch.
image_file = st.file_uploader("Upload Image (PNG/JPG)", type=['png', 'jpg', 'jpeg'])
excel_file = st.file_uploader("Upload Excel File (.xlsx)", type=['xlsx'])

if image_file and excel_file:
    st.success("Files provided — starte Verarbeitung...")

    # Save uploaded files into uploads/ for record and later reuse
    try:
        img_bytes = image_file.getvalue() if hasattr(image_file, 'getvalue') else image_file.read()
        img_name = getattr(image_file, 'name', 'uploaded_image.png')
        with open(os.path.join(uploads_dir, img_name), 'wb') as f:
            f.write(img_bytes)
    except Exception:
        pass
    try:
        excel_bytes = excel_file.getvalue() if hasattr(excel_file, 'getvalue') else excel_file.read()
        excel_name = getattr(excel_file, 'name', 'uploaded_coords.xlsx')
        with open(os.path.join(uploads_dir, excel_name), 'wb') as f:
            f.write(excel_bytes)
    except Exception:
        pass

    # Temporary paths for processing
    input_image_path = io.BytesIO(image_file.getvalue())
    output_geotiff_path = "/tmp/georeferenced_screenshot.tif" # Use a temporary file
    output_png_path = "/tmp/georeferenced_screenshot.png"

    ### 1. Georeference the Image
    st.subheader("1. Georeferencing Image")

    # Define bounds (these need to be input by the user or dynamically determined for a real app)
    st.info("For this demo, predefined coordinates (West: 11° 20', South: 50° 06', East: 11° 30', North: 50° 12') are used. In a real application, you might add input fields for these.")
    west = dm_to_dd(11, 20)
    south = dm_to_dd(50, 6)
    east = dm_to_dd(11, 30)
    north = dm_to_dd(50, 12)

    st.write(f"Defined bounds: West={west}°, South={south}°, East={east}°, North={north}°")

    # Load the image using Pillow
    img = Image.open(input_image_path)
    img_array = np.array(img)

    # Get image dimensions (handle grayscale or RGB/RGBA)
    if img_array.ndim == 2:
        height, width = img_array.shape
        bands = 1
    else:
        height, width, bands = img_array.shape

    # If rasterio (and GDAL) is available, create a GeoTIFF; otherwise fall back to the original image
    if has_rasterio:
        transform = rasterio.transform.from_bounds(west, south, east, north, width, height)

        # Define the Coordinate Reference System (CRS) - WGS84 for lat/lon
        crs = 'EPSG:4326'

        # Write the image as a GeoTIFF
        with rasterio.open(
            output_geotiff_path,
            'w',
            driver='GTiff',
            height=height,
            width=width,
            count=bands,
            dtype=img_array.dtype,
            crs=crs,
            transform=transform,
        ) as dst:
            if bands == 1:
                dst.write(img_array, 1)
            else:
                for i in range(bands):
                    dst.write(img_array[:, :, i], i + 1)
        st.success(f"Image successfully georeferenced to {output_geotiff_path}")

        # Convert GeoTIFF to PNG for Folium overlay (if original was not PNG already)
        with rasterio.open(output_geotiff_path) as src:
            geotiff_data = src.read()
            if src.count == 4:
                pil_image_array = np.transpose(geotiff_data, (1, 2, 0)).astype(np.uint8)
                pil_img = Image.fromarray(pil_image_array, 'RGBA')
            elif src.count == 3:
                pil_image_array = np.transpose(geotiff_data, (1, 2, 0)).astype(np.uint8)
                pil_img = Image.fromarray(pil_image_array, 'RGB')
            else:
                pil_image_array = geotiff_data[0, :, :].astype(np.uint8)
                pil_img = Image.fromarray(pil_image_array, 'L')

            pil_img.save(output_png_path)
        st.success(f"GeoTIFF converted to PNG for display: {output_png_path}")
    else:
        # Fallback: save the uploaded image directly for overlay (no GeoTIFF)
        try:
            pil_img = img.convert('RGBA') if img.mode in ('RGBA', 'RGB') else img.convert('RGB')
            pil_img.save(output_png_path)
            st.warning("rasterio/GDAL nicht verfügbar — Bild wird ohne GeoTIFF-Generierung angezeigt.")
        except Exception as e:
            st.error(f"Fehler beim Verarbeiten des Bildes ohne rasterio: {e}")
            st.stop()


    ### 2. Convert Coordinates
    st.subheader("2. Converting UTM to Latitude/Longitude")
    coordinates_df = pd.read_excel(excel_file)

    if 'UTM Zone' in coordinates_df.columns and 'Easting' in coordinates_df.columns and 'Northing' in coordinates_df.columns:
        try:
            utm_zone_str = coordinates_df['UTM Zone'].iloc[0]
            zone_number = int(utm_zone_str[:-1])
            hemisphere = 'north' if utm_zone_str[-1].upper() >= 'N' else 'south'

            if hemisphere == 'north':
                utm_epsg_code = 32600 + zone_number
            else:
                utm_epsg_code = 32700 + zone_number

            transformer = Transformer.from_crs(f"epsg:{utm_epsg_code}", "epsg:4326", always_xy=True)

            latitudes = []
            longitudes = []
            for idx, row in coordinates_df.iterrows():
                easting = row['Easting']
                northing = row['Northing']
                lon, lat = transformer.transform(easting, northing)
                longitudes.append(lon)
                latitudes.append(lat)

            coordinates_df['Latitude'] = latitudes
            coordinates_df['Longitude'] = longitudes
            st.success("UTM coordinates successfully converted to Latitude and Longitude.")
            st.dataframe(coordinates_df.head())
        except Exception as e:
            st.error(f"Error converting UTM coordinates: {e}")
            st.stop()
    else:
        st.warning("UTM Zone, Easting, or Northing columns not found in Excel file. Skipping coordinate conversion.")
        st.stop()


    ### 3. Display on an Interactive Map
    st.subheader("3. Interactive Map with Data Overlay")

    center_lat = (north + south) / 2
    center_lon = (east + west) / 2

    m = folium.Map(location=[center_lat, center_lon], zoom_start=12)

    with open(output_png_path, 'rb') as image_file_read:
        encoded_image = base64.b64encode(image_file_read.read()).decode('utf-8')

    image_bounds = [[south, west], [north, east]]
    folium.raster_layers.ImageOverlay(
        image=f"data:image/png;base64,{encoded_image}",
        bounds=image_bounds,
        opacity=0.5,
        name='Georeferenced Screenshot'
    ).add_to(m)

    points_layer = folium.FeatureGroup(name='Points from Excel').add_to(m)

    if 'Latitude' in coordinates_df.columns and 'Longitude' in coordinates_df.columns:
        for idx, row in coordinates_df.iterrows():
            lat = row['Latitude']
            lon = row['Longitude']
            point_name = row['Formation'] if 'Formation' in row else f"Point {idx+1}"

            folium.Marker(
                location=[lat, lon],
                popup=point_name,
                icon=folium.Icon(color='red')
            ).add_to(points_layer)
    else:
        st.warning("Latitude or Longitude columns not found after conversion. Skipping marker display.")

    folium.LayerControl().add_to(m)

    st_folium(m, width=1200, height=600)


    ### 4. Data Exploration and Visualizations
    st.subheader("4. Data Visualizations")

    if 'Aufschlusswand?' in coordinates_df.columns and 'Formation' in coordinates_df.columns:
        aufschlusswand_df = coordinates_df[coordinates_df['Aufschlusswand?'] == 'Ja']
        if not aufschlusswand_df.empty:
            formation_counts = aufschlusswand_df['Formation'].value_counts().reset_index()
            formation_counts.columns = ['Formation', 'Häufigkeit']

            fig1, ax1 = plt.subplots(figsize=(12, 7))
            sns.barplot(x='Häufigkeit', y='Formation', data=formation_counts, palette='viridis', ax=ax1)
            ax1.set_title('Häufigkeit von Aufschlusswänden pro Formation')
            ax1.set_xlabel('Anzahl der Aufschlusswände')
            ax1.set_ylabel('Formation')
            ax1.grid(axis='x', linestyle='--', alpha=0.7)
            st.pyplot(fig1)
        else:
            st.info("No data available for 'Aufschlusswand?' == 'Ja' to plot.")

        all_formation_counts = coordinates_df['Formation'].value_counts().reset_index()
        all_formation_counts.columns = ['Formation', 'Häufigkeit']

        fig2, ax2 = plt.subplots(figsize=(12, 7))
        sns.barplot(x='Häufigkeit', y='Formation', data=all_formation_counts, palette='viridis', ax=ax2)
        ax2.set_title('Häufigkeit aller Formationen')
        ax2.set_xlabel('Anzahl der Vorkommen')
        ax2.set_ylabel('Formation')
        ax2.grid(axis='x', linestyle='--', alpha=0.7)
        st.pyplot(fig2)
    else:
        st.warning("Columns 'Aufschlusswand?' or 'Formation' not found in Excel file. Skipping visualizations.")
