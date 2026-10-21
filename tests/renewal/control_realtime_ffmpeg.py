#!/usr/local/bin/python
"""Disposable long-work acceptance only: real-time input to real CPU FFmpeg."""
import os
import sys
args=sys.argv[1:]
if '-i' in args and '-c:v' in args:
    args.insert(args.index('-i'),'-re')
os.execv('/usr/bin/ffmpeg.real',['ffmpeg',*args])
