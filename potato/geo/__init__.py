"""
Geographic annotation support (``annotation_type: geo_annotation``).

* :mod:`potato.geo.geojson` -- RFC 7946 normalisation (coordinate order,
  bounds, closed rings, right-hand winding), areas and bounding boxes.
* :mod:`potato.geo.overlap` -- the draw-a-map aggregate: a grid of cells with
  the share of participants whose polygons cover each one.
* :mod:`potato.geo.png` -- a dependency-free PNG writer for the heat-map
  preview.

numpy is the only dependency. There is no GDAL, shapely or pyproj here: the
annotations are stored in EPSG:4326 and every computation is done in
longitude/latitude.
"""
