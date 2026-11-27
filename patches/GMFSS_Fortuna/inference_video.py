import os
import subprocess
import time
from pathlib import Path
import json
import copy
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
import threading
import skvideo


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = PROJECT_ROOT / "tools"
FFMPEG_EXE = TOOLS_DIR / "ffmpeg.exe"
FFPROBE_EXE = TOOLS_DIR / "ffprobe.exe"
if FFMPEG_EXE.is_file() and FFPROBE_EXE.is_file():
    os.environ["PATH"] = str(TOOLS_DIR) + os.pathsep + os.environ.get("PATH", "")
    skvideo.setFFmpegPath(str(TOOLS_DIR))

import skvideo.io

# The intermediate is re-encoded by Oniflow's mux step, so it must be close to
# lossless: OpenCV's mp4v writer cost about 2.5 VMAF points in the final file.
# Measured at 1080p 8x: HEVC NVENC qp 8 gives final VMAF 97.9 vs 95.5 for mp4v.
INTERMEDIATE_ENCODERS = (
    ["-c:v", "hevc_nvenc", "-preset", "p1", "-rc", "constqp", "-qp", "8"],
    ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "6"],
)
_intermediate_encoder = None


def ffmpeg_command():
    return str(FFMPEG_EXE) if FFMPEG_EXE.is_file() else "ffmpeg"


def pick_intermediate_encoder():
    """First encoder from INTERMEDIATE_ENCODERS that works here, else None."""
    global _intermediate_encoder
    if _intermediate_encoder is None:
        _intermediate_encoder = []
        for encoder in INTERMEDIATE_ENCODERS:
            probe = [ffmpeg_command(), "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
                     *encoder, "-pix_fmt", "yuv420p", "-f", "null", "-"]
            try:
                if subprocess.run(probe, capture_output=True, timeout=60).returncode == 0:
                    _intermediate_encoder = encoder
                    break
            except (OSError, subprocess.TimeoutExpired):
                break
    return _intermediate_encoder or None


def exact_rate(fps):
    """ffmpeg rate for fps: exact NTSC fraction (e.g. 192000/1001) when fps is one.

    --fps arrives rounded to 6 decimals; passing that on made ffmpeg store an
    approximation (871001/4541 instead of 192000/1001), and editors such as
    After Effects then showed the previous frame and never the last one.
    """
    for denominator in (1, 1001):
        numerator = round(fps * denominator)
        if abs(numerator / denominator - fps) < 1e-4:
            return f"{numerator}/{denominator}"
    rate = Fraction(fps).limit_denominator(1000000)
    return f"{rate.numerator}/{rate.denominator}"


class PipeVideoWriter:
    """cv2.VideoWriter-compatible writer that streams BGR frames into ffmpeg.

    4:2:0 video needs even dimensions, so an odd width or height loses its last
    pixel column or row (as OpenCV's writer did); Oniflow's mux step expects it.
    """

    def __init__(self, path, fps, width, height, encoder):
        self.width = width - width % 2
        self.height = height - height % 2
        command = [
            ffmpeg_command(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{self.width}x{self.height}", "-r", exact_rate(fps),
            "-i", "-", "-an", *encoder, "-pix_fmt", "yuv420p", path,
        ]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE)

    def write(self, frame):
        self.process.stdin.write(np.ascontiguousarray(frame[:self.height, :self.width]).tobytes())

    def release(self):
        try:
            self.process.stdin.close()
        except OSError:
            pass
        if self.process.wait() != 0:
            raise RuntimeError(f"ffmpeg failed to write the intermediate video (exit {self.process.returncode})")


def open_video_writer(path, fps, width, height, fourcc):
    encoder = pick_intermediate_encoder()
    if encoder is None:
        print("VFI_NOTICE ffmpeg intermediate encoder unavailable; using OpenCV mp4v", flush=True)
        return cv2.VideoWriter(path, fourcc, fps, (width, height))
    return PipeVideoWriter(path, fps, width, height, encoder)
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
parser.add_argument('--batch-manifest', dest='batch_manifest', type=str, default=None,
                    help='JSON manifest with video/output/fps/multi/scale jobs processed after one model load')
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
parser.add_argument('--scene-threshold', dest='scene_threshold', type=float, default=0.12,
                    help='hold the previous frame at a scene cut: the difference left after motion '
                         'compensation reaches this value (values of 1 or more turn detection off)')
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
assert (args.batch_manifest is not None or not args.video is None or not args.img is None)
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
from model.warplayer import warp as backward_warp

def clear_write_buffer(user_args, write_buffer, errors):
    cnt = 0
    while True:
        item = write_buffer.get()
        if item is None:
            break
        if errors:
            continue  # keep draining so the producer never blocks on a full queue
        try:
            if user_args.png:
                cv2.imwrite('vid_out/{:0>7d}.png'.format(cnt), item[:, :, ::-1])
                cnt += 1
            else:
                vid_out.write(item[:, :, ::-1])
        except Exception as exc:
            errors.append(exc)

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

def protect_interpolated_object(mid_frame, previous_frame, next_frame, mask, timestep):
    if mask is None:
        return mid_frame
    source_frame = previous_frame if timestep <= 0.5 else next_frame
    protected = mid_frame.astype(np.float32) * (1.0 - mask) + source_frame.astype(np.float32) * mask
    return np.clip(protected, 0, 255).astype(np.uint8)

# A cut also changes the colours on screen; fast motion in the same shot mostly does not.
SCENE_COLOR_CHANGE = 0.4

def color_change(previous_frame, next_frame):
    """Share of the colour distribution that differs: 0 = same colours, 1 = none in common."""
    def histogram(frame):
        small = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA).astype(np.int32) // 32
        bins = small[..., 0] * 64 + small[..., 1] * 8 + small[..., 2]
        return np.bincount(bins.ravel(), minlength=512) / bins.size
    return 0.5 * float(np.abs(histogram(previous_frame) - histogram(next_frame)).sum())

def motion_compensated_difference(I0, I1, flow01, flow10):
    """Mean difference left after moving each frame onto the other with the model's flow.

    Fast motion mostly cancels out here, so it is not mistaken for a cut the way
    the plain frame difference was; two different shots stay far apart.
    """
    img0 = F.interpolate(I0.float(), scale_factor=0.5, mode="bilinear", align_corners=False)
    img1 = F.interpolate(I1.float(), scale_factor=0.5, mode="bilinear", align_corners=False)
    difference01 = (backward_warp(img1, flow01.float()) - img0).abs().mean()
    difference10 = (backward_warp(img0, flow10.float()) - img1).abs().mean()
    return float((difference01 + difference10) / 2)

def is_scene_cut(motion_difference, color_difference, threshold):
    return motion_difference >= threshold or (
        motion_difference >= 0.75 * threshold and color_difference >= SCENE_COLOR_CHANGE
    )

def make_inference(I0, I1, reuse_things, timesteps):
    return [model.inference(I0, I1, reuse_things, timestep) for timestep in timesteps]

def output_frame_step(source_fps, output_fps, multi):
    """Distance between output frames, measured in source frames.

    Integer multipliers keep the exact 1/multi steps. Any other target, such
    as 23.976 -> 60 fps, places each output frame at its true time between two
    source frames and interpolates at that point.
    """
    if abs(source_fps * multi - output_fps) <= 0.02:
        return Fraction(1, multi)
    return Fraction(exact_rate(source_fps)) / Fraction(exact_rate(output_fps))

def pad_image(img):
    if(args.fp16):
        return F.pad(img, padding).half()
    else:
        return F.pad(img, padding)

def process_video(user_args):
    global args, h, w, padding, left, vid_out
    args = user_args
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
        fpsNotAssigned = False
        fourcc = cv2.VideoWriter_fourcc('m', 'p', '4', 'v')
        video_path_wo_ext = args.img

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
        vid_out = open_video_writer(vid_out_name, args.fps, w, h, fourcc)

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
    if args.video is not None:
        step = output_frame_step(fps, args.fps, args.multi)
    else:
        step = Fraction(1, args.multi)  # image sequences have no source frame rate
    next_position = Fraction(0)  # time of the next output frame, in source frames
    scene_cuts = 0
    if args.montage:
        lastframe = lastframe[:, left: left + w]
    write_buffer = Queue(maxsize=500)
    read_buffer = Queue(maxsize=500)
    _thread.start_new_thread(build_read_buffer, (args, read_buffer, videogen))
    # A joinable writer thread: the video must not be released while the
    # writer is still encoding the last frame (lost frames / cv2.error).
    writer_errors = []
    writer_thread = threading.Thread(target=clear_write_buffer, args=(args, write_buffer, writer_errors), daemon=True)
    writer_thread.start()

    I1 = torch.from_numpy(np.transpose(lastframe, (2,0,1))).to(device, non_blocking=True).unsqueeze(0)
    I1 = I1.half() if args.fp16 else I1.float()
    I1 = I1 / 255.
    I1 = F.interpolate(I1, (ph, pw), mode='bilinear', align_corners=False)
    temp = None

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

        # Output frames that fall between source frame `processed_frames` and the next one.
        timesteps = []
        while next_position < processed_frames + 1:
            timesteps.append(next_position - processed_frames)
            next_position += step
        writes_source_frame = bool(timesteps) and timesteps[0] == 0
        mid_timesteps = [float(t) for t in timesteps if t != 0]

        frame_difference = float(np.mean(np.abs(lastframe.astype(np.float32) - frame.astype(np.float32))) / 255.0)
        protection_mask = None
        if not mid_timesteps:
            output = []
        elif frame_difference <= args.static_threshold:
            output = [I0] * len(mid_timesteps)
        else:
            amp_context = torch.autocast(device_type="cuda", dtype=torch.float16) if args.amp and torch.cuda.is_available() else nullcontext()
            with amp_context:
                reuse_things = model.reuse(I0, I1, args.scale)
                scene_cut = args.scene_threshold < 1 and is_scene_cut(
                    motion_compensated_difference(I0, I1, reuse_things[0], reuse_things[1]),
                    color_change(lastframe, frame),
                    args.scene_threshold,
                )
                if scene_cut:
                    # Keep the cut sharp: hold the last frame of the old shot.
                    output = [I0] * len(mid_timesteps)
                    scene_cuts += 1
                else:
                    protection_mask = build_object_protection_mask(lastframe, frame, args)
                    output = make_inference(I0, I1, reuse_things, mid_timesteps)

        if args.montage:
            if writes_source_frame:
                write_buffer.put(np.concatenate((lastframe, lastframe), 1))
            for timestep, mid in zip(mid_timesteps, output):
                mid = (((mid[0] * 255.).byte().cpu().numpy().transpose(1, 2, 0)))
                mid = protect_interpolated_object(mid[:h, :w], lastframe, frame, protection_mask, timestep)
                write_buffer.put(np.concatenate((lastframe, mid[:h, :w]), 1))
        else:
            if writes_source_frame:
                write_buffer.put(lastframe)
            for timestep, mid in zip(mid_timesteps, output):
                mid = F.interpolate(mid, (h, w), mode='bilinear', align_corners=False)
                mid = (((mid[0] * 255.).byte().cpu().numpy().transpose(1, 2, 0)))
                mid = protect_interpolated_object(mid, lastframe, frame, protection_mask, timestep)
                write_buffer.put(mid)
        pbar.update(1)
        processed_frames += 1
        print('VFI_PROGRESS {} {}'.format(processed_frames, max(int(tot_frame) - 1, 1)), flush=True)
        if args.throttle_ms > 0:
            time.sleep(args.throttle_ms / 1000.0)
        lastframe = frame

    # End on the last real frame when an output frame lands exactly on it.
    # Repeating it (multi - 1) more times only padded the duration with
    # frozen frames at the end of every clip.
    if next_position == processed_frames:
        if args.montage:
            write_buffer.put(np.concatenate((lastframe, lastframe), 1))
        else:
            write_buffer.put(lastframe)
    write_buffer.put(None)
    writer_thread.join()
    if scene_cuts:
        print('VFI_NOTICE scene cuts kept sharp: {}'.format(scene_cuts), flush=True)
    pbar.close()
    if not vid_out is None:
        vid_out.release()
    if writer_errors:
        raise RuntimeError('Writing interpolated frames failed: {}'.format(writer_errors[0]))

    if args.png == False and fpsNotAssigned == True and not args.video is None:
        try:
            transferAudio(args.video, vid_out_name)
        except:
            print("Audio transfer failed. Interpolated video will have no audio")
            targetNoAudio = os.path.splitext(vid_out_name)[0] + "_noaudio" + os.path.splitext(vid_out_name)[1]
            os.rename(targetNoAudio, vid_out_name)

def build_job_args(base_args, job):
    job_args = copy.copy(base_args)
    for key, value in job.items():
        if not hasattr(job_args, key):
            raise ValueError('Unknown batch job option: {}'.format(key))
        setattr(job_args, key, value)
    if job_args.exp != 1:
        job_args.multi = (2 ** job_args.exp)
    if job_args.UHD and job_args.scale == 1.0:
        job_args.scale = 0.5
    assert job_args.scale in [0.25, 0.5, 0.75, 1.0, 2.0, 4.0]
    if not job_args.img is None:
        job_args.png = True
    return job_args

if args.batch_manifest:
    with open(args.batch_manifest, 'r', encoding='utf-8') as handle:
        jobs = json.load(handle)
    if not isinstance(jobs, list) or not jobs:
        raise ValueError('Batch manifest must contain a non-empty list of jobs')
    for index, job in enumerate(jobs, start=1):
        print('VFI_BATCH_ITEM {} {}'.format(index, len(jobs)), flush=True)
        process_video(build_job_args(args, job))
else:
    process_video(args)
