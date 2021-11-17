import cv2
import pathlib as P
import time
import subprocess as sp
import numpy as np
import struct
import matplotlib.pyplot as plt

GOPRO_VIDEO_FOLDER = '/home/cosc/research/CVlab/General ROV Footage/Scallops/118'#'/home/cosc/research/CVlab/General ROV Footage/Marlborough Sounds - Mussel Farm/GOPRO'#
VID_IDENTIFIER = 'dive_1'
IMAGE_WRITE_DIR = '/local/ScallopReconstructions/gopro_115/left/'
SAVE_IMGS = True
START_FRAME = 400
END_FRAME = 2000
EXTRACT_DATA = True
EXTRACT_FPS = 10
CROP_MUL = 0.75
FRAME_SHAPE = (2160, 3840, 3)

if EXTRACT_DATA:
    first_file = list(P.Path(GOPRO_VIDEO_FOLDER).iterdir())[0]
    telem_cmnd = [ "ffmpeg",
                   '-i', first_file,
                   '-f', 'image2pipe',
                   '-r', str(EXTRACT_FPS),
                   '-codec', 'copy',
                   '-map', '0:3', '-']
    telem_pipe = sp.Popen(telem_cmnd, stdout=sp.PIPE, bufsize=10**8)
    cnt = 0
    labels = ["ACCL", "DEVC", "DVID", "DVNM", "EMPT", "GPRO", "GPS5", "GPSF", "GPSP", "GPSU", "GYRO", "HD5.", "SCAL", "SIUN",
                "STRM", "TMPC", "TSMP", "UNIT", "TICK", "STNM", "ISOG", "SHUT", "TYPE", "FACE", "FCNM", "ISOE", "WBAL", "WRGB",
                "MAGN", "STMP", "STPS", "SROT", "TIMO", "UNIF", "MTRX", "ORIN", "ALLD", "ORIO"]
    labels_bytes = [label.encode('utf-8') for label in labels]
    telem_buff = b''
    prev_label = None
    prev_label_cnt = 0
    data_buff = []
    while telem_pipe.stdout.readable() and cnt < 100000000:
        telem_buff += telem_pipe.stdout.read(1000)
        cnt += 1000
        print("Byte cnt: {} ".format(cnt), end='\r')
        telem_pipe.stdout.flush()
        while len(telem_buff) >= 8:
            lb = telem_buff[:4]
            if lb in labels_bytes:
                desc_0 = int(telem_buff[4])
                if desc_0 == 0 or lb == "EMPT".encode('utf-8'):
                    telem_buff = telem_buff[8:]
                    continue
                val_size = int(telem_buff[5])
                num_values = (int(telem_buff[6]) << 8) | int(telem_buff[7])
                length = val_size * num_values
                if len(telem_buff) < length+8:
                    break
                data_buff.append([lb.decode('utf-8'), num_values, val_size, telem_buff[8:8+length]])
                telem_buff = telem_buff[8+length:]

            else:
                telem_buff = telem_buff[1:]
    gpsf_array = np.array([int.from_bytes(data[3], "big", signed=False) for data in data_buff if data[0] == 'GPSF'])
    #print(gpsf_array)
    print("Max GPSF value: {}".format(np.max(gpsf_array)))
    #[print(data) for data in data_buff if data[0] == 'SCAL' and data[2] == 4]
    latlon = [[int.from_bytes(data[3][:4], "big", signed=True), int.from_bytes(data[3][4:8], "big", signed=False)] for data in data_buff if data[0] == 'GPS5']
    latlon = np.array(latlon) / np.array([1e7, 1e7])
    valid_latlon = latlon[gpsf_array > 0]
    latlon_avg = np.mean(latlon, axis=0)
    print(latlon_avg)
    plt.scatter(latlon[:, 0], latlon[:, 1])
    plt.scatter(valid_latlon[:, 0], valid_latlon[:, 1], color='r')
    plt.show()

    exit(0)

frame_cnt = 0
cv2.namedWindow("Frames", cv2.WINDOW_NORMAL)
cv2.namedWindow("Cropped", cv2.WINDOW_NORMAL)
for vid_path in P.Path(GOPRO_VIDEO_FOLDER).iterdir():
    command = [ "ffmpeg",
                '-i', vid_path,
                '-f', 'image2pipe',
                '-pix_fmt', 'rgb24',
                '-r', str(EXTRACT_FPS),
                '-vcodec', 'rawvideo', '-']
    pipe = sp.Popen(command, stdout=sp.PIPE, bufsize=10**8)

    while pipe.stdout.readable():
        raw_image = pipe.stdout.read(FRAME_SHAPE[0]*FRAME_SHAPE[1]*FRAME_SHAPE[2])
        image = np.fromstring(raw_image, dtype='uint8')
        frame = image.reshape((FRAME_SHAPE[0], FRAME_SHAPE[1], FRAME_SHAPE[2]))[:, :, ::-1]
        pipe.stdout.flush()
        frame_cnt += 1
        print("Frame cnt: {}    ".format(frame_cnt), end='\r')
        cv2.imshow('Frames', frame)

        if SAVE_IMGS and frame_cnt > START_FRAME and frame_cnt <= END_FRAME:
            center = np.array(frame.shape) / 2
            h, w, _ = (np.array(frame.shape) * CROP_MUL).astype(np.int)
            x = int(center[1] - w/2)
            y = int(center[0] - h/2)
            frame_cropped = frame[y:y+h, x:x+w]
            cv2.imshow("Cropped", frame_cropped)
            cv2.imwrite(IMAGE_WRITE_DIR+VID_IDENTIFIER+'_'+str(frame_cnt)+".png", frame_cropped)

        key = cv2.waitKey(1)
        if key == ord('q'):
            exit(0)
        elif key == ord(' '):
            break

cv2.destroyAllWindows()
