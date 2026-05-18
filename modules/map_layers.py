"""Plotly map layer functions for cell towers, no-fly zones, and coverage."""
import plotly.graph_objects as go
from shapely.geometry import box
from modules import faa_rf

def add_cell_towers_layer_to_plotly(fig, state_abbr, minx, miny, maxx, maxy):
    """Add OpenCelliD cell tower markers to map."""
    try:
        gdf = faa_rf.load_cached_regulatory_layers(state_abbr, "cell_towers")
        if gdf.empty: return

        # Clip to bounding box
        pad = 0.05
        bbox = box(minx-pad, miny-pad, maxx+pad, maxy+pad)
        clipped = gdf[gdf.geometry.intersects(bbox)]

        if not clipped.empty:
            fig.add_trace(go.Scattermap(
                lat=clipped.geometry.y,
                lon=clipped.geometry.x,
                mode='markers',
                marker=dict(size=5, color='#ff9500', opacity=0.6),
                name='Cell Towers',
                hovertext=['Cell Tower' for _ in clipped],
                hoverinfo='text',
                showlegend=True,
            ))
    except Exception as e:
        print(f"[BRINC] add_cell_towers_layer_to_plotly failed: {e}")

def add_no_fly_zones_layer_to_plotly(fig, minx, miny, maxx, maxy):
    """Add no-fly zones (parks, water, restricted areas) to map."""
    try:
        gdf = faa_rf.load_cached_regulatory_layers("US", "no_fly_zones")
        if gdf.empty: return

        # Clip to bounding box
        pad = 0.05
        bbox = box(minx-pad, miny-pad, maxx+pad, maxy+pad)
        clipped = gdf[gdf.geometry.intersects(bbox)]

        if not clipped.empty:
            for _, row in clipped.iterrows():
                geom = row.geometry
                if geom.geom_type == 'Polygon':
                    lon, lat = zip(*geom.exterior.coords)
                    fig.add_trace(go.Scattermap(
                        lat=lat, lon=lon,
                        mode='lines', fill='toself',
                        fillcolor='rgba(100,100,255,0.15)',
                        line=dict(color='#6464ff', width=1),
                        name='No-Fly Zone',
                        hovertext=row.get('zone_type', 'No-Fly Zone'),
                        hoverinfo='text',
                        showlegend=False,
                    ))
    except Exception as e:
        print(f"[BRINC] add_no_fly_zones_layer_to_plotly failed: {e}")
