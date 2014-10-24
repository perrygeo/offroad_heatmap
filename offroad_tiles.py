from __future__ import print_function
import os
import requests
import mercantile
import mapnik
import numpy as np
from matplotlib import image

def tile_url(template, tile):
    return template.format(z=tile.z, x=tile.x, y=tile.y)


def tile_path(base, tile, ext):
    return os.path.join(base, str(tile.z), str(tile.x), str(tile.y) + "." + ext)


def prep_dirs(path):
    directory_name = os.path.dirname(path)
    if not os.path.exists(directory_name):
        os.makedirs(directory_name)
    return True

def save_tile(url, path):
    if os.path.exists(path):
        return
    prep_dirs(path)
    res = requests.get(url)
    if res.ok and res.content != '':
        with open(path, 'wb') as fh:
            fh.write(res.content)
        return True
    else:
        print("Could not save {}".format(url))
        return False

strava = "http://d2z9m7k9h4f0yp.cloudfront.net/tiles/cycling/color1/{z}/{x}/{y}.png"
osm_vect = "http://tile.openstreetmap.us/vectiles-highroad/{z}/{x}/{y}.json"
tiledir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'tiles'))


def seed_inputs(bounds, zooms):
    for tile in mercantile.tiles(*bounds, zooms=zooms):
        s = tile_url(strava, tile), tile_path(os.path.join(tiledir, 'strava'), tile, 'png')
        v = tile_url(osm_vect, tile), tile_path(os.path.join(tiledir, 'osm'), tile, 'json')
        save_tile(*s)
        save_tile(*v)

##################################################
m = mapnik.Map(256, 256)
m.srs = "+proj=merc +a=6378137 +b=6378137 +lat_ts=0.0 +lon_0=0.0 +x_0=0.0 +y_0=0 +k=1.0 +units=m +nadgrids=@null +no_defs +over"
s = mapnik.Style()
r = mapnik.Rule()
line_symbolizer = mapnik.LineSymbolizer(mapnik.Color('black'), 4)
r.symbols.append(line_symbolizer)
s.rules.append(r)
m.append_style('RoadStyle', s)
layer = mapnik.Layer('Roads from PostGIS')
layer.srs = "+init=epsg:3857"
ROADS = """
    (SELECT way
    FROM planet_osm_line
    WHERE roadbiking = TRUE) linestring
"""
layer.datasource = mapnik.PostGIS(host='localhost', user='mperry', password='mperry',
    dbname='osm_uswest', table=ROADS, geometry_field='way')
layer.styles.append('RoadStyle')
m.layers.append(layer)
##################################################

def vecttile_mask(jsonpath, bounds):
    ll = mercantile.xy(bounds.west, bounds.south)
    ur = mercantile.xy(bounds.east, bounds.north)
    extent = mapnik.Box2d(*(ll + ur))
    m.zoom_to_box(extent)  

    # mapnik.render_to_file(m, pngpath, 'png')
    # import ipdb; ipdb.set_trace()

    img = mapnik.Image(m.width, m.height)
    mapnik.render(m, img)

    imgdata = np.frombuffer(img.tostring(), dtype=np.uint8).reshape((256, 256, 4))

    # use alpha channel to get 0->1 scale for mask
    alpha = imgdata[:,:,3] / 255.0  

    # invert for easy multiplication w/ strava alpha channel
    #  1 = no road, keep strava heatmap values)
    #  0 = road, make strava heatmap transparent
    mask = 1 - alpha
    return mask

def seed_outputs(bounds, zooms):
    for tile in mercantile.tiles(*bounds, zooms=zooms):
        print(tile)
        render_offroad_tile(tile)


def heatmap_array(pngpath):
    arr = image.imread(pngpath)
    return arr


def adjust_alpha(rgba, mask):
    rgba_alpha = rgba[:,:,3]
    rgba[:,:,3] = rgba_alpha * mask
    return rgba


def render_offroad_tile(tile):
    mask = vecttile_mask(
        tile_path(os.path.join(tiledir, 'osm'), tile, 'json'), 
        mercantile.bounds(tile.x, tile.y, tile.z)
    )
    heatmap = heatmap_array(tile_path(os.path.join(tiledir, 'strava'), tile, 'png'))
    mod = adjust_alpha(heatmap.copy(), mask)
    path = tile_path(os.path.join(tiledir, 'offroad'), tile, 'png')
    prep_dirs(path)
    image.imsave(path, mod)
    return path


def test():
    bounds = -123.40, 45.47, -122.42, 46.33
    zooms = [10,11,12]

    print("Seeding inputs...")
    seed_inputs(bounds, zooms)
    print("Seeding outputs...")
    seed_outputs(bounds, zooms)


def make_tile(x, y, z):
    tile = mercantile.Tile(x, y, z)

    # cache inputs
    s = tile_url(strava, tile), tile_path(os.path.join(tiledir, 'strava'), tile, 'png')
    v = tile_url(osm_vect, tile), tile_path(os.path.join(tiledir, 'osm'), tile, 'json')
    save_tile(*s)
    save_tile(*v)

    # cache outputs
    return render_offroad_tile(tile)


from flask import Flask, make_response
app = Flask(__name__, static_url_path='')
app.debug = True
application = app

@app.route('/offroad/<z>/<x>/<y>.png', methods = ['GET'])
def tiles(x, y, z):
    x = int(x)
    y = int(y)
    z = int(z)
    path = tile_path(os.path.join(tiledir, 'offroad'), mercantile.Tile(x, y, z), 'png')
    if not os.path.exists(path):
        path = make_tile(x, y, z)
    with open(path, 'r') as fh:
        response = make_response(fh.read())
    response.mimetype = 'image/png'
    return response

if __name__ == '__main__':
    app.run(debug = True)