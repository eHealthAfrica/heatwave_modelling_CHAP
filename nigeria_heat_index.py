import streamlit as st
import ee
from heatwave.auth import init_ee  # triggers heatwave package's blessings stub before geemap loads
import geemap.foliumap as geemap  # Folium backend for Streamlit

from heatwave.config import settings
from heatwave.data.boundary import load_ward_boundary
from heatwave.data.ingest import load_era5_land
from heatwave.science.heat_index import compute_relative_humidity, compute_heat_index


@st.cache_resource
def _cached_init_ee() -> None:
    init_ee()


# Initialize Earth Engine (credential source resolved by heatwave.auth)
_cached_init_ee()

# =======================
# STEP 2: Define boundary & dates
# =======================
boundary = load_ward_boundary()
startDate = settings.start_date
endDate = settings.end_date

# =======================
# STEP 3: Load datasets
# =======================
era5_land = load_era5_land(boundary, startDate, endDate)

relativeHumidity = era5_land.map(compute_relative_humidity)

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
Map.addLayer(boundary_styled, {}, 'Ward Boundaries')

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