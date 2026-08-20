import streamlit as st
import ee
import geemap.foliumap as geemap  # Folium backend for Streamlit
import json
import os
import tempfile
from io import StringIO
from branca.element import Template, MacroElement
import sys, types
sys.modules["blessings"] = types.ModuleType("blessings")
from google.oauth2 import service_account

# Fix blessing issue for Streamlit Cloud
sys.modules["blessings"] = types.ModuleType("blessings")

# Required scopes for Earth Engine
EE_SCOPES = ["https://www.googleapis.com/auth/earthengine"]

# Initialize Earth Engine credentials
if "earthengine" in st.secrets:
    # Streamlit Cloud secret
    sa_info = dict(st.secrets["earthengine"])
    credentials = service_account.Credentials.from_service_account_info(
        sa_info, scopes=EE_SCOPES
    )

elif os.getenv("EE_SA_JSON"):
    # GitHub Actions / CI environment variable
    sa_info = json.loads(os.getenv("EE_SA_JSON"))
    credentials = service_account.Credentials.from_service_account_info(
        sa_info, scopes=EE_SCOPES
    )

else:
    # Local development from file
    key_file = "keys/service_account.json"
    credentials = service_account.Credentials.from_service_account_file(
        key_file, scopes=EE_SCOPES
    )

# Initialize Earth Engine
ee.Initialize(credentials)

# =======================
# STEP 2: Define boundary & dates
# =======================
boundary = ee.FeatureCollection('projects/ee-victoridakwo/assets/Northern_Nigeria')
startDate = '1980-01-01'
endDate = '2025-09-15'

# =======================
# STEP 3: Load datasets
# =======================
era5_2mt = ee.ImageCollection('ECMWF/ERA5/DAILY') \
    .select('mean_2m_air_temperature') \
    .filter(ee.Filter.date(startDate, endDate)) \
    .map(lambda image: image.clip(boundary))

era5_2d = ee.ImageCollection('ECMWF/ERA5/DAILY') \
    .select('dewpoint_2m_temperature') \
    .filter(ee.Filter.date(startDate, endDate)) \
    .map(lambda image: image.clip(boundary))

# Compute Relative Humidity
def compute_relative_humidity(tempImage):
    tempDate = tempImage.date()
    dewpointImage = era5_2d.filterDate(tempDate, tempDate.advance(1, 'day')).first()

    rh = ee.Image(dewpointImage).expression(
        '100 - 5 * (T - D)',
        {'T': tempImage, 'D': ee.Image(dewpointImage)}
    ).rename('relative_humidity')

    return tempImage.addBands(rh.set('system:time_start', tempImage.get('system:time_start')))

relativeHumidity = era5_2mt.map(compute_relative_humidity)

# Compute Heat Index
def compute_heat_index(image):
    tempC = image.select('mean_2m_air_temperature')
    tempF = tempC.subtract(273.15).multiply(9/5).add(32)
    RH = image.select('relative_humidity')

    c1, c2, c3, c4, c5, c6, c7, c8, c9 = [
        -42.379, 2.04901523, 10.14333127, -0.22475541,
        -0.00683783, -0.05481717, 0.00122874,
        0.00085282, -0.00000199
    ]

    HI = tempF.expression(
        'c1 + c2*T + c3*R + c4*T*R + c5*T**2 + c6*R**2 + c7*T**2*R + c8*T*R**2 + c9*T**2*R**2',
        {'T': tempF, 'R': RH, 'c1': c1, 'c2': c2, 'c3': c3,
         'c4': c4, 'c5': c5, 'c6': c6, 'c7': c7, 'c8': c8, 'c9': c9}
    ).rename('heat_index')

    return image.addBands(HI.set('system:time_start', image.get('system:time_start')))

heatIndex = relativeHumidity.map(compute_heat_index)

# =======================
# STEP 4: Streamlit UI
# =======================
st.set_page_config(page_title="Climate Explorer", layout="wide")
st.title("🌍 Climate Data Explorer (1980–2025)")

col1, col2, col3 = st.columns(3)
year = col1.slider("Year", 1980, 2025, 2012)
month = col2.slider("Month", 1, 12, 7)
day = col3.slider("Day", 1, 31, 15)

selected_date = f"{year:04d}-{month:02d}-{day:02d}"
st.write(f"📅 Selected Date: **{selected_date}**")

# =======================
# STEP 5: Map Visualization
# =======================
Map = geemap.Map(center=[10, 9], zoom=6)

# Add Heat Index layer
visHI = {'min': 0, 'max': 150, 'palette': ['blue', 'cyan', 'green', 'yellow', 'orange', 'red', 'purple']}
Map.addLayer(heatIndex.filter(ee.Filter.date(selected_date)).select('heat_index'), visHI, "Heat Index")

# Add boundary
boundary_styled = boundary.style(color='black', fillColor='00000000', width=2)
Map.addLayer(boundary_styled, {}, 'Northern Nigeria')

# Add map to Streamlit
Map.to_streamlit(height=700)

# =======================
# STEP 6: Heat Index Legend (Streamlit-compatible)
# =======================

def display_heat_index_legend():
    legend_html = """
    <div style="
        position: fixed;
        bottom: 20px;
        right: 20px;
        background-color: white;
        padding: 10px;
        font-size: 12px;
        font-family: Arial, sans-serif;
        border: 1px solid black;
        border-radius: 5px;
        width: 180px;
        z-index: 9999;
    ">
        <b style="display:block; text-align:center; margin-bottom:5px;">Heat Index (°F)</b>
        <div style="margin-bottom:8px; text-align:center;">
            <span style="
                display:block; 
                width:100%; 
                height:12px; 
                background: linear-gradient(to right, blue, cyan, green, yellow, orange, red, purple);
                margin-bottom:3px;
            "></span>
            0 – 150 °F
        </div>
    </div>
    """
    st.markdown(legend_html, unsafe_allow_html=True)

display_heat_index_legend()