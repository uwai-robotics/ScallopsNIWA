# import Metashape
# print("Metashape version {}".format(Metashape.version))
import os.path

from utils import VTKPointCloud as PC, polygon_functions as spf
from utils import geo_utils
from matplotlib import pyplot as plt
import numpy as np
from tqdm import tqdm
import re
import glob
from shapely.geometry import Polygon
import geopandas as gpd

# TODO: make single filtered polygon per cluster
# TODO: display valid/invalid polygon examples
# TODO: weighted confidence function?
# TODO: outlier removal


PROCESSED_BASEDIR = '/csse/research/CVlab/processed_bluerov_data/'
DONE_DIRS_FILE = PROCESSED_BASEDIR + 'dirs_annotation_log.txt'  # 'dirs_done.txt'


SHOW_SHAPE_PLOTS = False

SCALE_MUL = 1.025
RNN_DISTANCE = 0.03

SCALLOP_W_TO_L_RATIO = 1.3
W_TO_L_SCORE_STD = 0.4  # tolerance for width to length error

CLUSTER_TOP_N = 3
CLUSTER_TOPN_SCORE_THRESH = 0.80 * CLUSTER_TOP_N  # threshold for sum of top N scores
SHAPE_SCORE_MUL = 0.5


def process_dir(dirname):
    recon_dir = PROCESSED_BASEDIR + dirname + '/'
    print(f"----------- Processing {dirname} -----------")
    shape_file_3D = glob.glob(recon_dir + 'shapes_pred/*3D.gpkg')

    if len(shape_file_3D) != 1:
        print(f"{len(shape_file_3D)} shape files found! skipping.")
        return

    scallops_gpd = gpd.read_file(shape_file_3D[0])
    polygons_local = []
    polygon_scores = []
    datum = None
    print(f"Filtering {len(scallops_gpd)} detections...")
    for detection_row in tqdm(scallops_gpd.itertuples(), total=len(scallops_gpd)):
        poly_gps_3d = np.array(detection_row.geometry.exterior.coords)
        label = detection_row.NAME
        conf = float(label)
        if datum is None:
            datum = poly_gps_3d[0]

        poly_local = geo_utils.convert_gps2local(datum, poly_gps_3d)

        # Filter out-of-plane points
        poly_local_filtered = spf.plane_ransac_filter(poly_local, flatten=True)

        # TODO: score by symmetry - Phuong's code

        # Filter on polygon contour shape, CNN confidence, symmetry in width dimension, convexity, curve, pca statistics
        eig_vecs, eig_vals, center_pnt = spf.pca(poly_local_filtered)
        w_to_l = np.sqrt(eig_vals[0] / eig_vals[1])
        eig_shape_score = 1.0 - SHAPE_SCORE_MUL * min(W_TO_L_SCORE_STD, abs(w_to_l - SCALLOP_W_TO_L_RATIO)) / W_TO_L_SCORE_STD
        # print("W to L eigen ratio", w_to_l)
        # print(f"Eigen shape score: {eig_shape_score}")
        # print(f"CNN score: {conf}")

        combined_score = eig_shape_score * conf
        # print(f"Combined score: {combined_score}")

        polygons_local.append(poly_local_filtered)
        polygon_scores.append(combined_score)

        if SHOW_SHAPE_PLOTS:
            ax = plt.axes(projection='3d')
            ax.plot3D(poly_local[:, 0], poly_local[:, 1], poly_local[:, 2], 'r')
            ax.plot3D(poly_local_filtered[:, 0], poly_local_filtered[:, 1], poly_local_filtered[:, 2], 'b')
            plt.show()

    print(f"Got {len(polygons_local)} valid detections out of {len(scallops_gpd)}")

    print("RNN clustering polygons...")
    cluster_idxs = spf.rnn_clustering(polygons_local, RNN_DISTANCE)
    print("Number of clusters: {}".format(len(cluster_idxs)))

    print("Consolidating cluster polygons...")
    filtered_scallop_polys = []
    scores_debug = []
    for c_idxs in tqdm(cluster_idxs):
        cluster_polygons = [polygons_local[p_idx] for p_idx in c_idxs]
        scores = [polygon_scores[p_idx] for p_idx in c_idxs]
        combined_score = np.sum(np.sort(scores)[-CLUSTER_TOP_N:])
        scores_debug.append(combined_score)
        if combined_score > CLUSTER_TOPN_SCORE_THRESH:
            if len(cluster_polygons) > 1:
                combined_polygon = spf.cluster_avg_polygon(cluster_polygons, scores)
            else:
                combined_polygon = cluster_polygons[0]
            filtered_scallop_polys.append(combined_polygon)
    # counts, bins = np.histogram(scores_debug, bins=np.arange(start=0.0, stop=5.0, step=0.1))
    # plt.bar(bins[:-1], counts)
    # plt.title(f"Combined score distribution")
    # plt.show()
    print("Number of scallops after consolidating: {}".format(len(filtered_scallop_polys)))

    filtered_scallops_gps = [geo_utils.convert_local2gps(datum, p) for p in filtered_scallop_polys]

    print("Calculating sizes...")
    sizes = [spf.polygon_max_width(poly) for poly in filtered_scallop_polys]

    def s_format(size_m):
        return (str(round(size_m * 1000 * SCALE_MUL)) if not np.isnan(size_m) else 'nan ') + 'mm'

    shapes_3d_fn = recon_dir + 'shapes_pred/detections_filtered_3d.gpkg'
    shapes_2d_fn = recon_dir + 'shapes_pred/detections_filtered_2d.gpkg'
    if len(filtered_scallops_gps):
        names = [s_format(s) for s in sizes]
        geometry = [Polygon(poly) for poly in filtered_scallops_gps]
        polygons_3d_gpd = gpd.GeoDataFrame({'NAME': names, 'geometry': geometry}, geometry='geometry')
        polygons_3d_gpd.to_file(shapes_3d_fn)
        geometry = [Polygon(poly[:, :2]) for poly in filtered_scallops_gps]
        polygons_2d_gpd = gpd.GeoDataFrame({'NAME': names, 'geometry': geometry}, geometry='geometry')
        polygons_2d_gpd.to_file(shapes_2d_fn)
    else:
        for pth in [shapes_2d_fn, shapes_3d_fn]:
            if os.path.isfile(pth):
                os.remove(pth)


if __name__ == "__main__":
    with open(DONE_DIRS_FILE, 'r') as todo_file:
        data_dirs = todo_file.readlines()
    data_dirs = data_dirs[38:]
    for dir_line in data_dirs:
        if 'STOP' in dir_line:
            break
        # Check if this is a valid directory that needs processing
        if len(dir_line) == 1 or '#' in dir_line:
            continue
        data_dir = dir_line[:13]
        try:
            process_dir(data_dir)
        except:
            pass
