# generate_video.py
import argparse, os, subprocess, sys, json, uuid, shutil
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--prompt', required=True)
parser.add_argument('--duration', type=int, default=15)
parser.add_argument('--seed_url', default=None)
parser.add_argument('--outdir', default='work')
args = parser.parse_args()

outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
jobname = 'vid_' + uuid.uuid4().hex[:8]
out_mp4 = outdir / f"{jobname}.mp4"

def ffmpeg_trim(src, dst, seconds=30):
    cmd = [
        'ffmpeg','-y','-i', str(src),
        '-t', str(seconds),
        '-vf', 'scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2',
        '-c:v','libx264','-preset','veryfast','-crf','18', str(dst)
    ]
    subprocess.check_call(cmd)

def try_animatediff(prompt, duration, dest):
    # Implement actual AnimateDiff invocation here if installed.
    return False

def try_cogvideo(prompt, duration, dest):
    # Implement actual CogVideo invocation here if installed.
    return False

if not try_animatediff(args.prompt, args.duration, out_mp4) and not try_cogvideo(args.prompt, args.duration, out_mp4):
    # Create a simple 1-frame video with prompt text (test fallback)
    try:
        from PIL import Image, ImageDraw, ImageFont
        tmp = outdir / (jobname + '.png')
        im = Image.new('RGB', (1080,1920), color=(20,20,30))
        draw = ImageDraw.Draw(im)
        text = args.prompt[:700]
        draw.text((40,40), text, fill=(240,240,240))
        im.save(tmp)
        subprocess.check_call(['ffmpeg','-y','-loop','1','-i', str(tmp), '-c:v','libx264','-t', str(min(args.duration,30)), '-pix_fmt','yuv420p', str(out_mp4)])
        tmp.unlink(missing_ok=True)
    except Exception:
        subprocess.check_call(['ffmpeg','-y','-f','lavfi','-i','color=c=0x202030:s=1080x1920:d=%s' % min(args.duration,30), '-c:v','libx264', str(out_mp4)])

final = outdir / (jobname + '_trimmed.mp4')
try:
    ffmpeg_trim(out_mp4, final, seconds=min(args.duration,30))
except Exception:
    shutil.copy(out_mp4, final)

print(json.dumps({'output': str(final.resolve())}))
sys.exit(0)
