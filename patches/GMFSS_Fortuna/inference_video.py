import os
import subprocess
import time
from pathlib import Path
import cv2
import torch
import argparse
import numpy as np

# scikit-video still references aliases removed from modern NumPy.
np.float = float
np.int = int

from tqdm import tqdm
from torch.nn import functional as F
import warnings
import _thread
import skvideo


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = PROJECT_ROOT / "tools"
FFMPEG_EXE = TOOLS_DIR / "ffmpeg.exe"
FFPROBE_EXE = TOOLS_DIR / "ffprobe.exe"
if FFMPEG_EXE.is_file() and FFPROBE_EXE.is_file():
    os.environ["PATH"] = str(TOOLS_DIR) + os.pathsep + os.environ.get("PATH", "")
    skvideo.setFFmpegPath(str(TOOLS_DIR))

import skvideo.io
from contextlib import nullcontext
from fractions import Fraction
from math import gcd
from queue import Queue, Empty

warnings.filterwarnings("ignore")

def transferAudio(sourceVideo, targetVideo):
    import shutil
    tempAudioFileName = "./temp/audio.mkv"

    # split audio from original video file and store in "temp" directory
    if True:

        # clear old "temp" directory if it exits
        if os.path.isdir("temp"):
            # remove temp directory
            shutil.rmtree("temp")
        # create new "temp" directory
        os.makedirs("temp")
        # extract audio from video
        subprocess.run(
            [str(FFMPEG_EXE if FFMPEG_EXE.is_file() else "ffmpeg"), "-y", "-i", sourceVideo, "-c:a", "copy", "-vn", tempAudioFileName],
            check=True,
        )

    targetNoAudio = os.path.splitext(targetVideo)[0] + "_noaudio" + os.path.splitext(targetVideo)[1]
    os.rename(targetVideo, targetNoAudio)
    # combine audio file and new video file
    subprocess.run(
        [str(FFMPEG_EXE if FFMPEG_EXE.is_file() else "ffmpeg"), "-y", "-i", targetNoAudio, "-i", tempAudioFileName, "-c", "copy", targetVideo],
        check=False,
    )

    if os.path.getsize(targetVideo) == 0: # if ffmpeg failed to merge the video and audio together try converting the audio to aac
        tempAudioFileName = "./temp/audio.m4a"
        subprocess.run(
            [str(FFMPEG_EXE if FFMPEG_EXE.is_file() else "ffmpeg"), "-y", "-i", sourceVideo, "-c:a", "aac", "-b:a", "160k", "-vn", tempAudioFileName],
            check=True,
        )
        subprocess.run(
            [str(FFMPEG_EXE if FFMPEG_EXE.is_file() else "ffmpeg"), "-y", "-i", targetNoAudio, "-i", tempAudioFileName, "-c", "copy", targetVideo],
            check=False,
        )
        if (os.path.getsize(targetVideo) == 0): # if aac is not supported by selected format
            os.rename(targetNoAudio, targetVideo)
            print("Audio transfer failed. Interpolated video will have no audio")
        else:
            print("Lossless audio transfer failed. Audio was transcoded to AAC (M4A) instead.")

            # remove audio-less video
            os.remove(targetNoAudio)
    else:
        os.remove(targetNoAudio)

    # remove temp directory
    shutil.rmtree("temp")

parser = argparse.ArgumentParser(description='Interpolation for a pair of images')
parser.add_argument('--video', dest='video', type=str, default=None)
parser.add_argument('--output', dest='output', type=str, default=None)
parser.add_argument('--img', dest='img', type=str, default=None)
parser.add_argument('--montage', dest='montage', action='store_true', help='montage origin video')
parser.add_argument('--model', dest='modelDir', type=str, default='train_log', help='directory with trained model files')
parser.add_argument('--fp16', dest='fp16', action='store_true', help='fp16 mode for faster and more lightweight inference on cards with Tensor Cores')
parser.add_argument('--amp', dest='amp', action='store_true', help='mixed precision inference on GPUs with Tensor Cores')
parser.add_argument('--throttle-ms', dest='throttle_ms', type=int, default=0, help='delay after each source frame')
parser.add_argument('--UHD', dest='UHD', action='store_true', help='support 4k video')
parser.add_argument('--scale', dest='scale', type=float, default=1.0, help='Try scale=0.5 for 4k video')
parser.add_argument('--skip', dest='skip', action='store_true', help='whether to remove static frames before processing')
parser.add_argument('--fps', dest='fps', type=float, default=None)
parser.add_argument('--png', dest='png', action='store_true', help='whether to vid_out png format vid_outs')
parser.add_argument('--ext', dest='ext', type=str, default='mp4', help='vid_out video extension')
parser.add_argument('--exp', dest='exp', type=int, default=1)
parser.add_argument('--multi', dest='multi', type=int, default=2)
parser.add_argument('--union', dest='union', action='store_true', help='use union model')
parser.add_argument('--scene-threshold', dest='scene_threshold', type=float, default=0.32,
                    help='hold the previous frame when mean normalized difference exceeds this value')
parser.add_argument('--static-threshold', dest='static_threshold', type=float, default=0.002,
                    help='repeat held frames when mean normalized difference is below this value')
parser.add_argument('--object-protection', dest='object_protection', action=argparse.BooleanOptionalAction,
                    default=False, help='experimental: preserve fast moving objects in high-motion regions')
parser.add_argument('--object-threshold', dest='object_threshold', type=float, default=0.08,
                    help='per-pixel normalized difference that marks a high-motion object region')
parser.add_argument('--object-min-area', dest='object_min_area', type=float, default=0.002,
                    help='minimum changed image area required for object protection')
parser.add_argument('--object-max-area', dest='object_max_area', type=float, default=0.45,
                    help='maximum changed image area before the frame is treated as scene-like motion')
parser.add_argument('--object-dilate', dest='object_dilate', type=int, default=9,
                    help='dilate high-motion object masks to cover object edges')
parser.add_argument('--object-feather', dest='object_feather', type=int, default=15,
                    help='feather high-motion object masks to reduce hard edges')

args = parser.parse_args()
if args.exp != 1:
    args.multi = (2 ** args.exp)
assert (not args.video is None or not args.img is None)
if args.skip:
    print("skip flag is abandoned, please refer to issue #207.")
if args.UHD and args.scale==1.0:
    args.scale = 0.5
assert args.scale in [0.25, 0.5, 0.75, 1.0, 2.0, 4.0]
if not args.img is None:
    args.png = True

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
torch.set_grad_enabled(False)
if torch.cuda.is_available():
    torch.backends.cudnn.enabled = True
    # cuDNN benchmarking can spend many seconds tuning the first frame.
    # Deterministic algorithm selection starts short jobs much faster.
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.set_float32_matmul_precision("high")
    if(args.fp16):
        torch.set_default_tensor_type(torch.cuda.HalfTensor)

if args.union == True:
    try:
        from model.GMFSS_infer_u import Model
    except:
        print("Please download model from model list or Check if it is a union model")
else:
    try:
        from model.GMFSS_infer_b import Model
    except:
        print("Please download model from model list or Check if it is a base model")    
        
model = Model()
if not hasattr(model, 'version'):
    model.version = 0
model.load_model(args.modelDir, -1)
print("Loaded model")
model.eval()
model.device()

if not args.video is None:
    videoCapture = cv2.VideoCapture(args.video)
    fps = videoCapture.get(cv2.CAP_PROP_FPS)
    tot_frame = videoCapture.get(cv2.CAP_PROP_FRAME_COUNT)
    videoCapture.release()
    if args.fps is None:
        fpsNotAssigned = True
        args.fps = fps * args.multi
    else:
        fpsNotAssigned = False
    videogen = skvideo.io.vreader(args.video)
    lastframe = next(videogen)
    fourcc = cv2.VideoWriter_fourcc('m', 'p', '4', 'v')
    video_path_wo_ext, ext = os.path.splitext(args.video)
    print('{}.{}, {} frames in total, {}FPS to {}FPS'.format(video_path_wo_ext, args.ext, tot_frame, fps, args.fps))
    if args.png == False and fpsNotAssigned == True:
        print("The audio will be merged after interpolation process")
    else:
        print("Will not merge audio because using png or fps flag!")
else:
    videogen = []
    for f in os.listdir(args.img):
        if 'png' in f:
            videogen.append(f)
    tot_frame = len(videogen)
    videogen.sort(key= lambda x:int(x[:-4]))
    lastframe = cv2.imread(os.path.join(args.img, videogen[0]), cv2.IMREAD_UNCHANGED)[:, :, ::-1].copy()
    videogen = videogen[1:]
h, w, _ = lastframe.shape
vid_out_name = None
vid_out = None
if args.png:
    if not os.path.exists('vid_out'):
        os.mkdir('vid_out')
else:
    if args.output is not None:
        vid_out_name = args.output
    else:
        vid_out_name = '{}_{}X_{}fps.{}'.format(video_path_wo_ext, args.multi, int(np.round(args.fps)), args.ext)
    vid_out = cv2.VideoWriter(vid_out_name, fourcc, args.fps, (w, h))

def clear_write_buffer(user_args, write_buffer):
    cnt = 0
    while True:
        item = write_buffer.get()
        if item is None:
            break
        if user_args.png:
            cv2.imwrite('vid_out/{:0>7d}.png'.format(cnt), item[:, :, ::-1])
            cnt += 1
        else:
            vid_out.write(item[:, :, ::-1])

def build_read_buffer(user_args, read_buffer, videogen):
    try:
        for frame in videogen:
            if not user_args.img is None:
                frame = cv2.imread(os.path.join(user_args.img, frame))[:, :, ::-1].copy()
            if user_args.montage:
                frame = frame[:, left: left + w]
            read_buffer.put(frame)
    except:
        pass
    read_buffer.put(None)

def build_object_protection_mask(previous_frame, next_frame, user_args):
    if not user_args.object_protection:
        return None
    if user_args.object_threshold <= 0:
        return None
    diff_map = np.mean(
        np.abs(previous_frame.astype(np.float32) - next_frame.astype(np.float32)),
        axis=2,
    ) / 255.0
    strong_motion = (diff_map >= user_args.object_threshold).astype(np.uint8)
    changed_area = float(np.mean(strong_motion))
    if changed_area < user_args.object_min_area or changed_area > user_args.object_max_area:
        return None

    dilate_size = max(1, int(user_args.object_dilate))
    if dilate_size > 1:
        kernel = np.ones((dilate_size, dilate_size), np.uint8)
        strong_motion = cv2.dilate(strong_motion, kernel, iterations=1)

    mask = strong_motion.astype(np.float32)
    feather = max(0, int(user_args.object_feather))
    if feather >= 3:
        if feather % 2 == 0:
            feather += 1
        mask = cv2.GaussianBlur(mask, (feather, feather), 0)
        peak = float(mask.max())
        if peak > 0:
            mask = mask / peak
    return mask[:, :, None]

def protect_interpolated_object(mid_frame, previous_frame, next_frame, mask, position, total_positions):
    if mask is None:
        return mid_frame
    source_frame = previous_frame if position <= (total_positions / 2) else next_frame
    protected = mid_frame.astype(np.float32) * (1.0 - mask) + source_frame.astype(np.float32) * mask
    return np.clip(protected, 0, 255).astype(np.uint8)

def make_inference(I0, I1, reuse_things, n):    
    global model
    if model.version >= 3.9:
        res = []
        for i in range(n):
            res.append(model.inference(I0, I1, reuse_things, (i+1) * 1. / (n+1)))
        return res
    else:
        middle = model.inference(I0, I1, args.scale)
        if n == 1:
            return [middle]
        first_half = make_inference(I0, middle, n=n//2)
        second_half = make_inference(middle, I1, n=n//2)
        if n%2:
            return [*first_half, middle, *second_half]
        else:
            return [*first_half, *second_half]

def pad_image(img):
    if(args.fp16):
        return F.pad(img, padding).half()
    else:
        return F.pad(img, padding)

if args.montage:
    left = w // 4
    w = w // 2
scale_ratio = Fraction(str(args.scale))
tmp = max(64, 64 * scale_ratio.denominator // gcd(scale_ratio.numerator, 64 * scale_ratio.denominator))
ph = ((h - 1) // tmp + 1) * tmp
pw = ((w - 1) // tmp + 1) * tmp
padding = (0, pw - w, 0, ph - h)
pbar = tqdm(total=tot_frame)
processed_frames = 0
if args.montage:
    lastframe = lastframe[:, left: left + w]
write_buffer = Queue(maxsize=500)
read_buffer = Queue(maxsize=500)
_thread.start_new_thread(build_read_buffer, (args, read_buffer, videogen))
_thread.start_new_thread(clear_write_buffer, (args, write_buffer))

I1 = torch.from_numpy(np.transpose(lastframe, (2,0,1))).to(device, non_blocking=True).unsqueeze(0)
I1 = I1.half() if args.fp16 else I1.float()
I1 = I1 / 255.
I1 = F.interpolate(I1, (ph, pw), mode='bilinear', align_corners=False)
temp = None # save lastframe when processing static frame

while True:
    if temp is not None:
        frame = temp
        temp = None
    else:
        frame = read_buffer.get()
    if frame is None:
        break
    I0 = I1
    I1 = torch.from_numpy(np.transpose(frame, (2,0,1))).to(device, non_blocking=True).unsqueeze(0)
    I1 = I1.half() if args.fp16 else I1.float()
    I1 = I1 / 255.
    I1 = F.interpolate(I1, (ph, pw), mode='bilinear', align_corners=False)
    
    frame_difference = float(np.mean(np.abs(lastframe.astype(np.float32) - frame.astype(np.float32))) / 255.0)
    protection_mask = None
    if frame_difference <= args.static_threshold or frame_difference >= args.scene_threshold:
        output = [I0] * (args.multi - 1)
    else:
        protection_mask = build_object_protection_mask(lastframe, frame, args)
        amp_context = torch.autocast(device_type="cuda", dtype=torch.float16) if args.amp and torch.cuda.is_available() else nullcontext()
        with amp_context:
            reuse_things = model.reuse(I0, I1, args.scale)
            output = make_inference(I0, I1, reuse_things, args.multi-1)

    if args.montage:
        write_buffer.put(np.concatenate((lastframe, lastframe), 1))
        for index, mid in enumerate(output, start=1):
            mid = (((mid[0] * 255.).byte().cpu().numpy().transpose(1, 2, 0)))
            mid = protect_interpolated_object(mid[:h, :w], lastframe, frame, protection_mask, index, args.multi)
            write_buffer.put(np.concatenate((lastframe, mid[:h, :w]), 1))
    else:
        write_buffer.put(lastframe)
        for index, mid in enumerate(output, start=1):
            mid = F.interpolate(mid, (h, w), mode='bilinear', align_corners=False)
            mid = (((mid[0] * 255.).byte().cpu().numpy().transpose(1, 2, 0)))
            mid = protect_interpolated_object(mid, lastframe, frame, protection_mask, index, args.multi)
            write_buffer.put(mid)
    pbar.update(1)
    processed_frames += 1
    print('VFI_PROGRESS {} {}'.format(processed_frames, max(int(tot_frame) - 1, 1)), flush=True)
    if args.throttle_ms > 0:
        time.sleep(args.throttle_ms / 1000.0)
    lastframe = frame

if args.montage:
    write_buffer.put(np.concatenate((lastframe, lastframe), 1))
else:
    write_buffer.put(lastframe)
    # Preserve the source duration at high multipliers. There is no following
    # frame to interpolate against, so hold the final source frame.
    for _ in range(args.multi - 1):
        write_buffer.put(lastframe)
while(not write_buffer.empty()):
    time.sleep(0.1)
pbar.close()
if not vid_out is None:
    vid_out.release()

# move audio to new video file if appropriate
if args.png == False and fpsNotAssigned == True and not args.video is None:
    try:
        transferAudio(args.video, vid_out_name)
    except:
        print("Audio transfer failed. Interpolated video will have no audio")
        targetNoAudio = os.path.splitext(vid_out_name)[0] + "_noaudio" + os.path.splitext(vid_out_name)[1]
        os.rename(targetNoAudio, vid_out_name)
