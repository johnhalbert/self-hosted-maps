#!/usr/bin/env python3
import argparse
import math
import sys
from pathlib import Path


WEB_MERCATOR_LIMIT = 85.0511287798066


def require_apt_python_gdal():
    try:
        import numpy as np
        from PIL import Image
        from osgeo import gdal
    except ImportError as exc:
        raise SystemExit(
            "Missing terrain build dependencies. Install Debian packages: "
            "gdal-bin python3-gdal python3-numpy python3-pil. "
            "Do not install GDAL globally with pip."
        ) from exc
    return np, Image, gdal


def parse_bounds(value):
    try:
        west, south, east, north = [float(part) for part in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("bounds must be W,S,E,N") from exc
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise argparse.ArgumentTypeError("bounds are outside valid longitude/latitude ranges")
    return west, south, east, north


def lonlat_to_webmerc(lon, lat):
    lat = max(-WEB_MERCATOR_LIMIT, min(WEB_MERCATOR_LIMIT, lat))
    x = 6378137.0 * math.radians(lon)
    y = 6378137.0 * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))
    return x, y


def lonlat_to_tile(lon, lat, zoom):
    lat = max(-WEB_MERCATOR_LIMIT, min(WEB_MERCATOR_LIMIT, lat))
    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def tile_lonlat_bounds(z, x, y):
    n = 2**z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return west, south, east, north


def tile_ranges(bounds, zoom):
    west, south, east, north = bounds
    min_x, max_y = lonlat_to_tile(west, south, zoom)
    max_x, min_y = lonlat_to_tile(east, north, zoom)
    return range(min_x, max_x + 1), range(min_y, max_y + 1)


def encode_terrarium(np, elevation):
    shifted = np.clip(elevation + 32768.0, 0, 65535.996)
    red = np.floor(shifted / 256.0)
    green = np.floor(shifted - red * 256.0)
    blue = np.floor((shifted - np.floor(shifted)) * 256.0)
    return np.dstack([red, green, blue]).astype(np.uint8)


def encode_mapbox(np, elevation):
    shifted = np.clip((elevation + 10000.0) * 10.0, 0, 256**3 - 1)
    red = np.floor(shifted / (256 * 256))
    green = np.floor(shifted / 256) % 256
    blue = np.floor(shifted) % 256
    return np.dstack([red, green, blue]).astype(np.uint8)


def build_tile(np, Image, gdal, dataset, output_path, bounds, tile_size, encoding, resampling):
    west, south, east, north = bounds
    min_x, min_y = lonlat_to_webmerc(west, south)
    max_x, max_y = lonlat_to_webmerc(east, north)
    warped = gdal.Warp(
        "",
        dataset,
        format="MEM",
        dstSRS="EPSG:3857",
        outputBounds=(min_x, min_y, max_x, max_y),
        width=tile_size,
        height=tile_size,
        resampleAlg=resampling,
        multithread=True,
    )
    if warped is None:
        return False
    band = warped.GetRasterBand(1)
    elevation = band.ReadAsArray().astype("float32")
    nodata = band.GetNoDataValue()
    if nodata is not None:
        elevation = np.where(elevation == nodata, 0, elevation)
    elevation = np.where(np.isfinite(elevation), elevation, 0)
    rgb = encode_terrarium(np, elevation) if encoding == "terrarium" else encode_mapbox(np, elevation)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(output_path)
    return True


def main():
    parser = argparse.ArgumentParser(description="Build local raster-dem terrain PNG tiles from a DEM.")
    parser.add_argument("--dem", required=True, help="Input DEM readable by GDAL, such as GeoTIFF.")
    parser.add_argument("--output", required=True, help="Output directory. Tiles are written under output/dem.")
    parser.add_argument("--bounds", required=True, type=parse_bounds, help="W,S,E,N longitude/latitude bounds.")
    parser.add_argument("--minzoom", type=int, default=0)
    parser.add_argument("--maxzoom", type=int, required=True)
    parser.add_argument("--tile-size", type=int, choices=(256, 512), default=256)
    parser.add_argument("--encoding", choices=("terrarium", "mapbox"), default="terrarium")
    parser.add_argument("--resampling", default="bilinear", choices=("near", "bilinear", "cubic", "cubicspline"))
    args = parser.parse_args()

    if args.minzoom < 0 or args.maxzoom < args.minzoom or args.maxzoom > 22:
        raise SystemExit("zoom range must be 0..22 and maxzoom must be >= minzoom")

    np, Image, gdal = require_apt_python_gdal()
    gdal.UseExceptions()
    dataset = gdal.Open(args.dem)
    if dataset is None:
        raise SystemExit(f"Unable to open DEM: {args.dem}")
    if not dataset.GetProjection():
        raise SystemExit("Input DEM must have a coordinate reference system.")

    output_root = Path(args.output) / "dem"
    count = 0
    for zoom in range(args.minzoom, args.maxzoom + 1):
        x_range, y_range = tile_ranges(args.bounds, zoom)
        for x in x_range:
            for y in y_range:
                output_path = output_root / str(zoom) / str(x) / f"{y}.png"
                if build_tile(
                    np,
                    Image,
                    gdal,
                    dataset,
                    output_path,
                    tile_lonlat_bounds(zoom, x, y),
                    args.tile_size,
                    args.encoding,
                    args.resampling,
                ):
                    count += 1

    print(f"Wrote {count} {args.encoding} raster-dem tile(s) under {output_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
